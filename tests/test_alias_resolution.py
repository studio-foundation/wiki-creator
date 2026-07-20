"""Tests for scripts/alias_resolution.py."""
import json
import os
import subprocess
import sys
import unittest.mock as mock
from pathlib import Path

from scripts.alias_resolution import resolve_aliases, _pick_snippets, make_ollama_confirmer
from wiki_creator.lang import load_lang_config
from wiki_creator.types import EntityFull


def _pf(records: dict) -> dict:
    """Wrap plain *_full-shaped record dicts as EntityFull, as load_full_file yields."""
    return {
        eid: EntityFull(
            type=v.get("type", "PERSON"),
            raw_mentions=v.get("raw_mentions", []),
            first_seen=v.get("first_seen", ""),
            mention_count=v.get("mention_count", 0),
            mentions_by_chapter=v.get("mentions_by_chapter", {}),
            mention_spans_by_chapter=v.get("mention_spans_by_chapter", {}),
        )
        for eid, v in records.items()
    }

_EN_CFG = load_lang_config("en")
_EN_REVEAL_WORDS = tuple(_EN_CFG.get("reveal_words", ()))


PERSON_A = {
    "canonical_name": "Celaena",
    "type": "PERSON",
    "aliases": ["Celaena"],
    "source_ids": ["entity_001"],
    "relevant": True,
}

PERSON_B = {
    "canonical_name": "Lillian Gordaina",
    "type": "PERSON",
    "aliases": ["Lillian"],
    "source_ids": ["entity_002"],
    "relevant": True,
}

PLACE = {
    "canonical_name": "Rifthold",
    "type": "PLACE",
    "aliases": ["Rifthold"],
    "source_ids": ["place_001"],
    "relevant": True,
}


def test_non_person_entities_pass_through_unchanged():
    result = resolve_aliases([PLACE], persons_full={})
    assert result["entities"] == [PLACE]
    assert result["stats"]["candidates_considered"] == 0


def test_passthrough_when_no_alias_evidence_exists():
    persons_full = _pf({
        "entity_001": {"mentions_by_chapter": {"ch01": ["Celaena entered the room."]}},
        "entity_002": {"mentions_by_chapter": {"ch01": ["Lillian watched the door."]}},
    })
    result = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full)
    assert [e["canonical_name"] for e in result["entities"]] == ["Celaena", "Lillian Gordaina"]
    assert result["stats"]["merges_applied"] == 0



def test_self_introduction_does_not_merge_the_bystander_it_is_spoken_to():
    """STU-538: "you may call me X" names its speaker, who the snippet never names.

    Verbatim from Eragon ch. 19: Solembum the werecat introduces himself to Eragon.
    A template anchored on {b} alone is a property of one entity's context, so it
    fires on whatever entity happens to be paired with it.
    """
    solembum = {
        "canonical_name": "Solembum",
        "type": "PERSON",
        "aliases": ["Solembum"],
        "source_ids": ["entity_138"],
        "relevant": True,
    }
    eragon = {
        "canonical_name": "Eragon",
        "type": "PERSON",
        "aliases": ["Eragon"],
        "source_ids": ["entity_013"],
        "relevant": True,
    }
    snippet = (
        "Eragon gave up and turned to leave. However, you may call me Solembum. "
        "Thank you, said Eragon seriously."
    )
    persons_full = _pf({
        "entity_013": {"mentions_by_chapter": {"ch19": [snippet]}},
        "entity_138": {"mentions_by_chapter": {"ch19": [snippet]}},
    })
    result = resolve_aliases([eragon, solembum], persons_full=persons_full)
    assert [e["canonical_name"] for e in result["entities"]] == ["Eragon", "Solembum"]
    assert result["stats"]["merges_applied"] == 0


def test_medium_confidence_pair_requires_llm_confirmation():
    persons_full = _pf({
        "entity_001": {
            "mentions_by_chapter": {
                "ch05": ["Celaena, hidden under another name, stepped forward."],
            }
        },
        "entity_002": {
            "mentions_by_chapter": {
                "ch05": ["The court whispered that Lillian Gordaina was another name entirely."],
            }
        },
    })
    no_llm = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full, reveal_words=_EN_REVEAL_WORDS)
    assert len(no_llm["entities"]) == 2
    assert no_llm["stats"]["llm_attempts"] == 0

    def confirm(candidate):
        assert candidate["entity_a"]["canonical_name"] == "Celaena"
        assert candidate["entity_b"]["canonical_name"] == "Lillian Gordaina"
        return {"same_person": True, "confidence": "medium", "evidence": "reveal confirmed"}

    with_llm = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full, llm_confirmer=confirm, reveal_words=_EN_REVEAL_WORDS)
    assert len(with_llm["entities"]) == 1
    assert with_llm["stats"]["llm_attempts"] == 1
    assert with_llm["stats"]["llm_confirmed"] == 1


def test_llm_errors_degrade_gracefully():
    persons_full = _pf({
        "entity_001": {"mentions_by_chapter": {"ch05": ["Celaena used another name."]}},
        "entity_002": {"mentions_by_chapter": {"ch05": ["Lillian Gordaina was that other name."]}},
    })

    def boom(_candidate):
        raise RuntimeError("llm unavailable")

    result = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full, llm_confirmer=boom, reveal_words=_EN_REVEAL_WORDS)
    assert len(result["entities"]) == 2
    assert result["stats"]["llm_attempts"] == 1
    assert result["stats"]["llm_failed"] == 1


def test_script_stdin_contract_reads_registry_from_processing_dir(tmp_path: Path):
    book_yaml = tmp_path / "library" / "author" / "series" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n", encoding="utf-8")

    processing = tmp_path / "library" / "author" / "series" / "processing_output" / "book"
    processing.mkdir(parents=True)
    # pure_title is the merge path that cannot fire without the on-disk contexts.
    persons_full = {
        "persons_full": {
            "title_001": {
                "type": "PERSON",
                "raw_mentions": ["Captain"],
                "first_seen": "ch03",
                "mention_count": 1,
                "mentions_by_chapter": {"ch03": ["Captain Chaol Westfall saluted."]},
            },
            "entity_003": {
                "type": "PERSON",
                "raw_mentions": ["Chaol Westfall"],
                "first_seen": "ch03",
                "mention_count": 1,
                "mentions_by_chapter": {"ch03": ["Captain Chaol Westfall saluted."]},
            },
        }
    }
    (processing / "persons_full.json").write_text(json.dumps(persons_full), encoding="utf-8")

    title_entity = {
        "canonical_name": "Captain",
        "type": "PERSON",
        "aliases": ["Captain"],
        "source_ids": ["title_001"],
        "relevant": True,
    }
    named_entity = {
        "canonical_name": "Chaol Westfall",
        "type": "PERSON",
        "aliases": ["Chaol Westfall"],
        "source_ids": ["entity_003"],
        "relevant": True,
    }
    payload = {
        "previous_outputs": {"resolve-clusters": {"entities": [title_entity, named_entity], "narrator": None}},
        "additional_context": (
            f"file_path: {book_yaml}\n"
            "classification:\n"
            "  roles_naming_one_character: [captain]\n"
        ),
    }
    result = subprocess.run(
        [sys.executable, "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert len(output["entities"]) == 1
    assert output["stats"]["merges_applied"] == 1



def test_pick_snippets_prioritises_canonical_name():
    entity = {
        "canonical_name": "Celaena",
        "aliases": ["Celaena"],
        "source_ids": ["e1"],
    }
    persons_full = _pf({
        "e1": {
            "mentions_by_chapter": {
                "ch01": ["Someone entered.", "Celaena smiled.", "A guard stood."],
                "ch02": ["Celaena ran.", "Another person spoke."],
            }
        }
    })
    snippets = _pick_snippets(entity, persons_full, n=3)
    assert len(snippets) == 3
    # Snippets containing the name come first
    assert snippets[0] in ("Celaena smiled.", "Celaena ran.")
    assert snippets[1] in ("Celaena smiled.", "Celaena ran.")


def test_pick_snippets_falls_back_when_name_not_in_any_snippet():
    entity = {
        "canonical_name": "The Stranger",
        "aliases": [],
        "source_ids": ["e2"],
    }
    persons_full = _pf({
        "e2": {
            "mentions_by_chapter": {
                "ch01": ["Someone appeared.", "A figure moved."],
            }
        }
    })
    snippets = _pick_snippets(entity, persons_full, n=3)
    assert len(snippets) == 2  # only 2 available


def test_pick_snippets_empty_when_no_source_ids():
    entity = {"canonical_name": "Ghost", "aliases": [], "source_ids": []}
    assert _pick_snippets(entity, {}, n=3) == []



_ENTITY_A = {
    "canonical_name": "Celaena",
    "aliases": ["Celaena"],
    "source_ids": ["e1"],
    "type": "PERSON",
    "relevant": True,
}
_ENTITY_B = {
    "canonical_name": "Lillian",
    "aliases": ["Lillian"],
    "source_ids": ["e2"],
    "type": "PERSON",
    "relevant": True,
}
_PERSONS_FULL_LLM = _pf({
    "e1": {"mentions_by_chapter": {"ch01": ["Celaena walked in."]}},
    "e2": {"mentions_by_chapter": {"ch01": ["Lillian watched her."]}},
})


def _mock_ollama_response(payload: dict) -> mock.MagicMock:
    body = json.dumps({"response": json.dumps(payload)}).encode()
    cm = mock.MagicMock()
    cm.__enter__ = lambda s: s
    cm.__exit__ = mock.Mock(return_value=False)
    cm.read.return_value = body
    return cm


def test_make_ollama_confirmer_returns_same_person_true():
    with mock.patch("urllib.request.urlopen", return_value=_mock_ollama_response(
        {"same_person": True, "confidence": "high", "evidence": "same person confirmed"}
    )):
        confirmer = make_ollama_confirmer("mistral", "http://localhost:11434", timeout=10)
        result = confirmer({
            "entity_a": _ENTITY_A,
            "entity_b": _ENTITY_B,
            "evidence": {"snippet": "her real name was Lillian"},
            "persons_full": _PERSONS_FULL_LLM,
        })
    assert result["same_person"] is True
    assert result["confidence"] == "high"


def test_make_ollama_confirmer_returns_same_person_false():
    with mock.patch("urllib.request.urlopen", return_value=_mock_ollama_response(
        {"same_person": False, "confidence": "low", "evidence": "different people"}
    )):
        confirmer = make_ollama_confirmer("mistral", "http://localhost:11434", timeout=10)
        result = confirmer({
            "entity_a": _ENTITY_A,
            "entity_b": _ENTITY_B,
            "evidence": {"snippet": "another name was mentioned"},
            "persons_full": _PERSONS_FULL_LLM,
        })
    assert result["same_person"] is False


def test_make_ollama_confirmer_handles_json_wrapped_in_prose():
    prose = 'Sure! Here is my answer: {"same_person": true, "confidence": "medium", "evidence": "yes"} Hope that helps.'
    body = json.dumps({"response": prose}).encode()
    cm = mock.MagicMock()
    cm.__enter__ = lambda s: s
    cm.__exit__ = mock.Mock(return_value=False)
    cm.read.return_value = body
    with mock.patch("urllib.request.urlopen", return_value=cm):
        confirmer = make_ollama_confirmer("mistral", "http://localhost:11434", timeout=10)
        result = confirmer({
            "entity_a": _ENTITY_A,
            "entity_b": _ENTITY_B,
            "evidence": {"snippet": "alias"},
            "persons_full": _PERSONS_FULL_LLM,
        })
    assert result is not None
    assert result["same_person"] is True


def test_make_ollama_confirmer_returns_none_on_unparseable_response():
    body = json.dumps({"response": "I cannot determine that."}).encode()
    cm = mock.MagicMock()
    cm.__enter__ = lambda s: s
    cm.__exit__ = mock.Mock(return_value=False)
    cm.read.return_value = body
    with mock.patch("urllib.request.urlopen", return_value=cm):
        confirmer = make_ollama_confirmer("mistral", "http://localhost:11434", timeout=10)
        result = confirmer({
            "entity_a": _ENTITY_A,
            "entity_b": _ENTITY_B,
            "evidence": {"snippet": "alias"},
            "persons_full": _PERSONS_FULL_LLM,
        })
    assert result is None


def test_script_use_llm_false_by_default(tmp_path):
    """use_llm defaults to false — no llm_confirmer instantiated, no Ollama call."""
    book_yaml = tmp_path / "library" / "a" / "s" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n")
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(json.dumps({"persons_full": {}}))

    payload = {
        "previous_outputs": {"resolve-clusters": {"entities": [], "narrator": None}},
        "additional_context": f"file_path: {book_yaml}\n",
    }
    result = subprocess.run(
        [sys.executable, "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, result.stderr
    # No Ollama warning when use_llm is false
    assert "ollama" not in result.stderr.lower()


def test_script_use_llm_false_emits_warning(tmp_path):
    """use_llm absent → warning printed to stderr."""
    book_yaml = tmp_path / "library" / "a" / "s" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n")
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(json.dumps({"persons_full": {}}))

    payload = {
        "previous_outputs": {"resolve-clusters": {"entities": [], "narrator": None}},
        "additional_context": f"file_path: {book_yaml}\n",
    }
    result = subprocess.run(
        [sys.executable, "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, result.stderr
    assert "use_llm" in result.stderr.lower()


def test_script_use_llm_true_warns_when_ollama_unavailable(tmp_path):
    """use_llm=true but Ollama unreachable → warn + graceful skip."""
    book_yaml = tmp_path / "library" / "a" / "s" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n")
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(json.dumps({"persons_full": {}}))

    payload = {
        "previous_outputs": {"resolve-clusters": {"entities": [], "narrator": None}},
        "additional_context": f"file_path: {book_yaml}\nuse_llm: true\nllm_model: mistral\n",
    }
    # Point to a port that's definitely not listening
    env = {**os.environ, "OLLAMA_URL": "http://127.0.0.1:19999"}
    result = subprocess.run(
        [sys.executable, "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "ollama" in result.stderr.lower()


# ---------------------------------------------------------------------------
# _detect_title_alias
# ---------------------------------------------------------------------------

def test_detect_title_alias_captain_westfall():
    from scripts.alias_resolution import _detect_title_alias
    entity_title = {"canonical_name": "Captain Westfall", "aliases": ["Captain Westfall"]}
    entity_full  = {"canonical_name": "Chaol Westfall",   "aliases": ["Chaol Westfall", "Chaol"]}
    result = _detect_title_alias(entity_title, entity_full, role_words=["captain"])
    assert result is not None
    assert result["method"] == "title_alias"
    assert result["confidence"] == "medium"


def test_detect_title_alias_no_match_remainder_absent():
    from scripts.alias_resolution import _detect_title_alias
    # "Princess Nehemia" — remainder "nehemia" not in "Dorian Havilliard"
    entity_title = {"canonical_name": "Princess Nehemia", "aliases": ["Princess Nehemia"]}
    entity_full  = {"canonical_name": "Dorian Havilliard", "aliases": ["Dorian Havilliard"]}
    assert _detect_title_alias(entity_title, entity_full, role_words=["princess"]) is None


def test_detect_title_alias_no_match_empty_remainder():
    from scripts.alias_resolution import _detect_title_alias
    # "Captain" alone — no remainder after role_word
    entity_a = {"canonical_name": "Captain", "aliases": ["Captain"]}
    entity_b = {"canonical_name": "Chaol Westfall", "aliases": ["Chaol Westfall"]}
    assert _detect_title_alias(entity_a, entity_b, role_words=["captain"]) is None


def test_detect_title_alias_empty_role_words():
    from scripts.alias_resolution import _detect_title_alias
    entity_a = {"canonical_name": "Captain Westfall", "aliases": ["Captain Westfall"]}
    entity_b = {"canonical_name": "Chaol Westfall", "aliases": ["Chaol Westfall"]}
    assert _detect_title_alias(entity_a, entity_b, role_words=[]) is None


def test_detect_title_alias_symmetric():
    from scripts.alias_resolution import _detect_title_alias
    # Order of arguments should not matter
    entity_title = {"canonical_name": "Captain Westfall", "aliases": ["Captain Westfall"]}
    entity_full  = {"canonical_name": "Chaol Westfall",   "aliases": ["Chaol Westfall"]}
    assert _detect_title_alias(entity_full, entity_title, role_words=["captain"]) is not None


def test_detect_title_alias_via_aliases_list():
    from scripts.alias_resolution import _detect_title_alias
    # Title is in entity's aliases list, not canonical_name
    entity_a = {"canonical_name": "Chaol Westfall", "aliases": ["Chaol Westfall", "Captain Westfall"]}
    entity_b = {"canonical_name": "Chaol Westfall (guard)", "aliases": ["Chaol Westfall (guard)"]}
    # "Captain Westfall" in aliases → remainder "westfall" in "Chaol Westfall (guard)"
    result = _detect_title_alias(entity_a, entity_b, role_words=["captain"])
    assert result is not None
    assert result["method"] == "title_alias"


def test_detect_title_alias_different_honorifics_same_surname():
    from scripts.alias_resolution import _detect_title_alias
    # Mr Beaver and Mrs Beaver are two characters: the shared surname cannot discriminate them
    entity_a = {"canonical_name": "Mrs Beaver", "aliases": ["Mrs Beaver"]}
    entity_b = {"canonical_name": "Mr Beaver", "aliases": ["Mr Beaver"]}
    assert _detect_title_alias(entity_a, entity_b, role_words=["mr", "mrs"]) is None


def test_detect_title_alias_titled_alias_blocks_transitive_remarriage():
    from scripts.alias_resolution import _detect_title_alias
    # Once bare "Beaver" carries "Mr Beaver" as an alias, it is Mr Beaver
    entity_a = {"canonical_name": "Beaver", "aliases": ["Beaver", "Mr Beaver"]}
    entity_b = {"canonical_name": "Mrs Beaver", "aliases": ["Mrs Beaver"]}
    assert _detect_title_alias(entity_a, entity_b, role_words=["mr", "mrs"]) is None


def test_detect_title_alias_plural_family_name():
    from scripts.alias_resolution import _detect_title_alias
    # "Beavers" is the couple, not either spouse — it is not the token "Beaver"
    entity_a = {"canonical_name": "Mrs Beaver", "aliases": ["Mrs Beaver"]}
    entity_b = {"canonical_name": "Beavers", "aliases": ["Beavers"]}
    assert _detect_title_alias(entity_a, entity_b, role_words=["mr", "mrs"]) is None


def _beaver_roster():
    return [
        {"canonical_name": "Mr Beaver", "aliases": ["Mr Beaver"], "type": "PERSON", "source_ids": ["e1"]},
        {"canonical_name": "Mrs Beaver", "aliases": ["Mrs Beaver"], "type": "PERSON", "source_ids": ["e2"]},
        {"canonical_name": "Beaver", "aliases": ["Beaver"], "type": "PERSON", "source_ids": ["e3"]},
    ]


def test_resolve_aliases_bare_surname_shared_by_two_honorifics_merges_with_neither():
    from itertools import permutations

    from scripts.alias_resolution import resolve_aliases

    for roster in permutations(_beaver_roster()):
        result = resolve_aliases(list(roster), {}, role_words=["mr", "mrs"])
        assert sorted(e["canonical_name"] for e in result["entities"]) == ["Beaver", "Mr Beaver", "Mrs Beaver"]
        assert result["stats"]["merges_applied"] == 0


def test_resolve_aliases_bare_name_of_a_single_honorific_still_merges():
    from scripts.alias_resolution import resolve_aliases

    entities = [
        {"canonical_name": "Mr Tumnus", "aliases": ["Mr Tumnus"], "type": "PERSON", "source_ids": ["e1"]},
        {"canonical_name": "Tumnus", "aliases": ["Tumnus"], "type": "PERSON", "source_ids": ["e2"]},
    ]
    result = resolve_aliases(entities, {}, role_words=["mr", "mrs"])
    assert len(result["entities"]) == 1
    assert result["stats"]["merges_by_method"]["title_alias"] == 1


def test_detect_title_alias_honorific_merges_untitled_name():
    from scripts.alias_resolution import _detect_title_alias
    entity_a = {"canonical_name": "Mr Tumnus", "aliases": ["Mr Tumnus"]}
    entity_b = {"canonical_name": "Tumnus", "aliases": ["Tumnus"]}
    result = _detect_title_alias(entity_a, entity_b, role_words=["mr", "mrs"])
    assert result is not None
    assert result["method"] == "title_alias"


def test_detect_title_alias_same_title_merges():
    from scripts.alias_resolution import _detect_title_alias
    entity_a = {"canonical_name": "Captain Westfall", "aliases": ["Captain Westfall"]}
    entity_b = {"canonical_name": "Captain Chaol Westfall", "aliases": ["Captain Chaol Westfall"]}
    assert _detect_title_alias(entity_a, entity_b, role_words=["captain"]) is not None


def test_empty_stats_has_title_alias_key():
    from scripts.alias_resolution import _empty_stats
    stats = _empty_stats()
    assert "title_alias" in stats["merges_by_method"]
    assert stats["merges_by_method"]["title_alias"] == 0


def test_resolve_aliases_title_alias_with_llm_merges():
    """Title alias pair is auto-merged (structural evidence is unambiguous; LLM is not consulted)."""
    from scripts.alias_resolution import resolve_aliases
    captain = {
        "canonical_name": "Captain Westfall",
        "type": "PERSON",
        "aliases": ["Captain Westfall"],
        "source_ids": [],
        "relevant": True,
    }
    chaol = {
        "canonical_name": "Chaol Westfall",
        "type": "PERSON",
        "aliases": ["Chaol Westfall", "Chaol"],
        "source_ids": [],
        "relevant": True,
    }

    def confirm_yes(candidate):
        return {"same_person": True, "confidence": "high", "evidence": "same person"}

    result = resolve_aliases(
        [captain, chaol],
        persons_full={},
        llm_confirmer=confirm_yes,
        role_words=["captain"],
    )
    assert len(result["entities"]) == 1
    entity = result["entities"][0]
    assert "Captain Westfall" in entity["aliases"] or "Chaol Westfall" in entity["aliases"]
    assert result["stats"]["merges_applied"] == 1


def test_resolve_aliases_title_alias_without_llm_merges():
    """Title alias pair is auto-merged even without an LLM confirmer."""
    from scripts.alias_resolution import resolve_aliases
    captain = {
        "canonical_name": "Captain Westfall",
        "type": "PERSON",
        "aliases": ["Captain Westfall"],
        "source_ids": [],
        "relevant": True,
    }
    chaol = {
        "canonical_name": "Chaol Westfall",
        "type": "PERSON",
        "aliases": ["Chaol Westfall"],
        "source_ids": [],
        "relevant": True,
    }
    result = resolve_aliases(
        [captain, chaol],
        persons_full={},
        llm_confirmer=None,
        role_words=["captain"],
    )
    assert len(result["entities"]) == 1
    assert result["stats"]["merges_applied"] == 1
    assert result["stats"]["merges_by_method"]["title_alias"] == 1


def test_title_alias_merges_without_llm_confirmer():
    """STU-275: _detect_title_alias must auto-confirm without requiring llm_confirmer."""
    from scripts.alias_resolution import resolve_aliases

    entities = [
        {
            "canonical_name": "Chaol Westfall",
            "type": "PERSON",
            "relevant": True,
            "aliases": ["Chaol Westfall", "Westfall"],
            "source_ids": ["e1"],
        },
        {
            "canonical_name": "Captain Westfall",
            "type": "PERSON",
            "relevant": True,
            "aliases": ["Captain Westfall"],
            "source_ids": ["e2"],
        },
    ]
    result = resolve_aliases(
        entities,
        persons_full={},
        narrator=None,
        llm_confirmer=None,  # no LLM — must still merge
        role_words=["captain"],
    )
    resolved = result["entities"]
    assert len(resolved) == 1, f"Expected 1 merged entity, got {len(resolved)}: {resolved}"
    names = {e["canonical_name"] for e in resolved}
    aliases = {a for e in resolved for a in e.get("aliases", [])}
    assert "Chaol Westfall" in names | aliases
    assert "Captain Westfall" in names | aliases
    assert result["stats"]["merges_by_method"]["title_alias"] == 1


def test_script_role_words_propagated_from_ctx(tmp_path):
    """main() passes role_words from book YAML ctx to resolve_aliases."""
    import subprocess, json, textwrap
    from pathlib import Path
    ctx_yaml = textwrap.dedent("""
        file_path: dummy.epub
        use_llm: false
        classification:
          role_words:
            - captain
    """)
    payload = {
        "additional_context": ctx_yaml,
        "previous_outputs": {
            "resolve-clusters": {
                "entities": [
                    {"canonical_name": "Captain Xander", "type": "PERSON",
                     "aliases": ["Captain Xander"], "source_ids": [], "relevant": True},
                    {"canonical_name": "Xander", "type": "PERSON",
                     "aliases": ["Xander"], "source_ids": [], "relevant": True},
                ],
                "narrator": None,
            }
        },
        "all_stage_outputs": {},
    }
    project_root = str(Path(__file__).parents[1])
    result = subprocess.run(
        ["python", "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=project_root,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    # Title aliases are auto-confirmed without LLM; expect a merge, not an ambiguous pair
    assert output["stats"]["merges_by_method"]["title_alias"] >= 1




def test_main_reads_entities_from_resolve_clusters_when_available(tmp_path):
    """STU-590: alias-resolution reads resolve-clusters output from all_stage_outputs."""
    import subprocess, json
    from pathlib import Path
    book_yaml = tmp_path / "library" / "a" / "s" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n")
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(json.dumps({"persons_full": {}}))

    merged_entity = {
        "canonical_name": "Brullo",
        "type": "PERSON",
        "aliases": ["Brullo"],
        "source_ids": [],
        "relevant": True,
    }
    payload = {
        "additional_context": f"file_path: {book_yaml}\n",
        "previous_outputs": {
            "resolve-clusters": {"entities": [merged_entity], "narrator": None},
        },
        "all_stage_outputs": {
            "resolve-clusters": {"entities": [merged_entity], "narrator": None},
            "relationship-extraction": {"relationships": []},
        },
    }
    result = subprocess.run(
        ["python", "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=str(Path(__file__).parents[1]),
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert len(output["entities"]) == 1
    assert output["entities"][0]["canonical_name"] == "Brullo"


def test_pick_canonical_name_prefers_proper_name_over_pure_title():
    """'Brullo' must win over 'Master' when 'master' is a role_word."""
    from scripts.alias_resolution import _pick_canonical_name
    brullo = {
        "canonical_name": "Brullo",
        "aliases": ["Brullo"],
        "source_ids": [],
    }
    master = {
        "canonical_name": "Master",
        "aliases": ["Master"],
        "source_ids": [],
    }
    # Frequency is equal (no persons_full context); proper name must still win.
    canonical = _pick_canonical_name(brullo, master, persons_full={}, role_words=["master"])
    assert canonical == "Brullo"


def test_pick_canonical_name_keeps_frequency_when_no_pure_title():
    """With no pure title involved, frequency still wins."""
    from scripts.alias_resolution import _pick_canonical_name
    celaena = {
        "canonical_name": "Celaena",
        "aliases": ["Celaena"],
        "source_ids": ["e1"],
    }
    aelin = {
        "canonical_name": "Aelin",
        "aliases": ["Aelin"],
        "source_ids": ["e2"],
    }
    persons_full = _pf({
        "e1": {"mentions_by_chapter": {"ch01": ["Celaena Celaena Celaena walked in."]}},
        "e2": {"mentions_by_chapter": {"ch01": ["Aelin smiled."]}},
    })
    canonical = _pick_canonical_name(celaena, aelin, persons_full=persons_full, role_words=["captain"])
    assert canonical == "Celaena"  # higher frequency


def test_resolve_aliases_title_alias_auto_merges_regardless_of_llm():
    """Title alias pair is auto-merged; LLM rejection is not consulted."""
    from scripts.alias_resolution import resolve_aliases
    captain = {
        "canonical_name": "Captain Flint",
        "type": "PERSON",
        "aliases": ["Captain Flint"],
        "source_ids": [],
        "relevant": True,
    }
    flint = {
        "canonical_name": "Flint",
        "type": "PERSON",
        "aliases": ["Flint"],
        "source_ids": [],
        "relevant": True,
    }

    def confirm_no(candidate):
        return {"same_person": False, "confidence": "high", "evidence": "different people"}

    result = resolve_aliases(
        [captain, flint],
        persons_full={},
        llm_confirmer=confirm_no,
        role_words=["captain"],
    )
    assert len(result["entities"]) == 1
    assert result["stats"]["merges_applied"] == 1
    assert result["stats"]["merges_by_method"]["title_alias"] == 1


def test_build_role_index_groups_by_third_party_and_rel_type():
    from scripts.alias_resolution import _build_role_index
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Master", "relationship_type": "mentor/protégé", "cooccurrence_count": 12},
        {"entity_a": "Brullo",  "entity_b": "Celaena", "relationship_type": "mentor/protégé", "cooccurrence_count": 8},
        {"entity_a": "Dorian",  "entity_b": "Celaena", "relationship_type": "ami",            "cooccurrence_count": 5},
    ]
    index = _build_role_index(relationships)
    # ("Celaena", "mentor/protégé") should have both Master and Brullo
    key = ("Celaena", "mentor/protégé")
    assert key in index
    assert set(index[key]) == {"master", "brullo"}


def test_build_role_index_skips_unclassified():
    from scripts.alias_resolution import _build_role_index
    relationships = [
        {"entity_a": "A", "entity_b": "C", "relationship_type": None, "cooccurrence_count": 3},
    ]
    index = _build_role_index(relationships)
    assert index == {}


def test_detect_role_symmetric_finds_brullo_old_brullo():
    """'Brullo' and 'Old Brullo' share a name token and identical role buckets → valid candidate."""
    from scripts.alias_resolution import _detect_role_symmetric_pairs
    brullo = {
        "canonical_name": "Brullo",
        "type": "PERSON",
        "aliases": ["Brullo"],
        "source_ids": [],
        "relevant": True,
    }
    old_brullo = {
        "canonical_name": "Old Brullo",
        "type": "PERSON",
        "aliases": ["Old Brullo"],
        "source_ids": [],
        "relevant": True,
    }
    celaena = {
        "canonical_name": "Celaena Sardothien",
        "type": "PERSON",
        "aliases": ["Celaena Sardothien", "Celaena"],
        "source_ids": [],
        "relevant": True,
    }
    dorian = {
        "canonical_name": "Dorian",
        "type": "PERSON",
        "aliases": ["Dorian"],
        "source_ids": [],
        "relevant": True,
    }
    relationships = [
        # Both Brullo and Old Brullo share: Celaena as mentor/protégé AND Dorian as connaissance
        {"entity_a": "Celaena Sardothien", "entity_b": "Old Brullo", "relationship_type": "mentor/protégé", "cooccurrence_count": 12},
        {"entity_a": "Brullo", "entity_b": "Celaena Sardothien", "relationship_type": "mentor/protégé", "cooccurrence_count": 8},
        {"entity_a": "Dorian",  "entity_b": "Old Brullo",  "relationship_type": "connaissance", "cooccurrence_count": 3},
        {"entity_a": "Dorian",  "entity_b": "Brullo",  "relationship_type": "connaissance", "cooccurrence_count": 2},
    ]
    pairs = _detect_role_symmetric_pairs(
        [brullo, old_brullo, celaena, dorian],
        relationships,
        min_shared=2,
        direct_cooc_max=3,
    )
    assert len(pairs) == 1
    names = {pairs[0][0]["canonical_name"], pairs[0][1]["canonical_name"]}
    assert names == {"Brullo", "Old Brullo"}


def test_detect_role_symmetric_no_false_positive_with_one_shared_third_party():
    """Two guards sharing only one common (third_party, rel_type) bucket do not trigger."""
    from scripts.alias_resolution import _detect_role_symmetric_pairs
    guard_a = {"canonical_name": "Guard A", "type": "PERSON", "aliases": ["Guard A"], "source_ids": [], "relevant": True}
    guard_b = {"canonical_name": "Guard B", "type": "PERSON", "aliases": ["Guard B"], "source_ids": [], "relevant": True}
    lord = {"canonical_name": "Lord X", "type": "PERSON", "aliases": ["Lord X"], "source_ids": [], "relevant": True}
    relationships = [
        {"entity_a": "Lord X", "entity_b": "Guard A", "relationship_type": "employeur/employé", "cooccurrence_count": 5},
        {"entity_a": "Lord X", "entity_b": "Guard B", "relationship_type": "employeur/employé", "cooccurrence_count": 3},
    ]
    pairs = _detect_role_symmetric_pairs(
        [guard_a, guard_b, lord],
        relationships,
        min_shared=2,  # only 1 shared bucket → no merge
        direct_cooc_max=3,
    )
    assert pairs == []


def test_resolve_aliases_role_symmetric_with_llm_merges():
    """Role-symmetric pairs with shared token go to LLM; confirmed pairs are merged."""
    from scripts.alias_resolution import resolve_aliases
    brullo = {
        "canonical_name": "Brullo",
        "type": "PERSON",
        "aliases": ["Brullo"],
        "source_ids": [],
        "relevant": True,
    }
    old_brullo = {
        "canonical_name": "Old Brullo",
        "type": "PERSON",
        "aliases": ["Old Brullo"],
        "source_ids": [],
        "relevant": True,
    }
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Old Brullo", "relationship_type": "mentor/protégé", "cooccurrence_count": 12},
        {"entity_a": "Brullo",  "entity_b": "Celaena",    "relationship_type": "mentor/protégé", "cooccurrence_count": 8},
        {"entity_a": "Dorian",  "entity_b": "Old Brullo", "relationship_type": "connaissance",   "cooccurrence_count": 3},
        {"entity_a": "Dorian",  "entity_b": "Brullo",     "relationship_type": "connaissance",   "cooccurrence_count": 2},
    ]

    def confirm_yes(candidate):
        return {"same_person": True, "confidence": "medium", "evidence": "same role toward Celaena"}

    result = resolve_aliases(
        [brullo, old_brullo],
        persons_full={},
        llm_confirmer=confirm_yes,
        relationships=relationships,
        role_words=[],
        role_symmetric_min_shared=2,
    )
    assert len(result["entities"]) == 1
    # With no persons_full context both names have count=0; _pick_canonical_name prefers
    # longer multi-token names, so "Old Brullo" wins over "Brullo" in this unit test.
    assert "Brullo" in result["entities"][0]["canonical_name"]
    assert result["stats"]["merges_by_method"].get("role_symmetric", 0) >= 1


def test_resolve_aliases_role_symmetric_no_llm_stays_ambiguous():
    """Without LLM confirmer, role-symmetric candidates with shared token stay as ambiguous_pairs."""
    from scripts.alias_resolution import resolve_aliases
    brullo = {"canonical_name": "Brullo", "type": "PERSON", "aliases": ["Brullo"], "source_ids": [], "relevant": True}
    old_brullo = {"canonical_name": "Old Brullo", "type": "PERSON", "aliases": ["Old Brullo"], "source_ids": [], "relevant": True}
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Old Brullo", "relationship_type": "mentor/protégé", "cooccurrence_count": 12},
        {"entity_a": "Brullo",  "entity_b": "Celaena",    "relationship_type": "mentor/protégé", "cooccurrence_count": 8},
        {"entity_a": "Dorian",  "entity_b": "Old Brullo", "relationship_type": "connaissance",   "cooccurrence_count": 3},
        {"entity_a": "Dorian",  "entity_b": "Brullo",     "relationship_type": "connaissance",   "cooccurrence_count": 2},
    ]
    result = resolve_aliases(
        [brullo, old_brullo],
        persons_full={},
        llm_confirmer=None,
        relationships=relationships,
        role_words=[],
        role_symmetric_min_shared=2,
    )
    assert len(result["entities"]) == 2  # not merged
    assert result["stats"]["ambiguous_pairs"] >= 1


def test_detect_role_symmetric_skips_high_direct_cooccurrence():
    """If A and B already co-occur heavily, they are likely already handled."""
    from scripts.alias_resolution import _detect_role_symmetric_pairs
    a = {"canonical_name": "A", "type": "PERSON", "aliases": ["A"], "source_ids": [], "relevant": True}
    b = {"canonical_name": "B", "type": "PERSON", "aliases": ["B"], "source_ids": [], "relevant": True}
    c = {"canonical_name": "C", "type": "PERSON", "aliases": ["C"], "source_ids": [], "relevant": True}
    d = {"canonical_name": "D", "type": "PERSON", "aliases": ["D"], "source_ids": [], "relevant": True}
    relationships = [
        {"entity_a": "A", "entity_b": "C", "relationship_type": "ami", "cooccurrence_count": 5},
        {"entity_a": "B", "entity_b": "C", "relationship_type": "ami", "cooccurrence_count": 5},
        {"entity_a": "A", "entity_b": "D", "relationship_type": "ami", "cooccurrence_count": 5},
        {"entity_a": "B", "entity_b": "D", "relationship_type": "ami", "cooccurrence_count": 5},
        # A and B also appear directly together with high cooccurrence
        {"entity_a": "A", "entity_b": "B", "relationship_type": "ami", "cooccurrence_count": 20},
    ]
    pairs = _detect_role_symmetric_pairs(
        [a, b, c, d],
        relationships,
        min_shared=2,
        direct_cooc_max=3,  # 20 > 3 → skip
    )
    assert pairs == []


# ---------------------------------------------------------------------------
# _detect_pure_title_in_context  (STU-281)
# ---------------------------------------------------------------------------

def test_detect_pure_title_in_context_master_brullo():
    """'Master' (pure role title) whose context mentions 'Brullo' must be detected as alias."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    brullo = {
        "canonical_name": "Brullo",
        "aliases": ["Brullo"],
        "source_ids": ["e_brullo"],
    }
    master = {
        "canonical_name": "Master",
        "aliases": ["Master"],
        "source_ids": ["e_master"],
    }
    persons_full = _pf({
        "e_master": {
            "mentions_by_chapter": {
                "ch05": [
                    "Master Brullo corrected her stance.",
                    "Brullo — the Master — nodded at Celaena.",
                ]
            }
        },
        "e_brullo": {
            "mentions_by_chapter": {
                "ch05": ["Brullo watched the competitors."]
            }
        },
    })
    result = _detect_pure_title_in_context(
        brullo, master, persons_full, roles_naming_one_character=["master"],
        connective_words=["the"],
    )
    assert result is not None
    assert result["method"] == "pure_title"
    assert result["confidence"] == "medium"


def test_detect_pure_title_in_context_no_match_when_name_absent_from_context():
    """No match when the proper-name entity does not appear in the title entity's context."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    brullo = {"canonical_name": "Brullo", "aliases": ["Brullo"], "source_ids": ["e_brullo"]}
    master = {"canonical_name": "Master", "aliases": ["Master"], "source_ids": ["e_master"]}
    persons_full = _pf({
        "e_master": {
            "mentions_by_chapter": {"ch05": ["The Master stood silently."]}
        },
        "e_brullo": {
            "mentions_by_chapter": {"ch05": ["Brullo watched the competitors."]}
        },
    })
    result = _detect_pure_title_in_context(
        brullo, master, persons_full, roles_naming_one_character=["master"],
        connective_words=["the"],
    )
    assert result is None


def test_detect_pure_title_in_context_not_triggered_for_title_with_surname():
    """'Captain Westfall' is NOT a pure title — function must not fire."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    captain = {"canonical_name": "Captain Westfall", "aliases": ["Captain Westfall"], "source_ids": []}
    chaol = {"canonical_name": "Chaol Westfall", "aliases": ["Chaol Westfall"], "source_ids": []}
    result = _detect_pure_title_in_context(
        captain, chaol, {}, roles_naming_one_character=["captain"]
    )
    assert result is None


def test_detect_pure_title_in_context_multi_word_phrase_title():
    """'Crown Prince' is a pure multi-word role phrase and must be detected as alias of Dorian."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    dorian = {
        "canonical_name": "Dorian Havilliard",
        "aliases": ["Dorian Havilliard", "Dorian"],
        "source_ids": ["e_dorian"],
    }
    crown_prince = {
        "canonical_name": "Crown Prince",
        "aliases": ["Crown Prince"],
        "source_ids": ["e_crown_prince"],
    }
    persons_full = _pf({
        "e_crown_prince": {
            "mentions_by_chapter": {
                "ch01": [
                    "The Crown Prince Dorian Havilliard smiled.",
                    "Crown Prince Dorian watched from the dais.",
                ]
            }
        },
        "e_dorian": {
            "mentions_by_chapter": {"ch01": ["Dorian Havilliard offered her a deal."]}
        },
    })
    result = _detect_pure_title_in_context(
        dorian, crown_prince, persons_full,
        roles_naming_one_character=["crown prince"],
        connective_words=["the"],
    )
    assert result is not None
    assert result["method"] == "pure_title"


def test_detect_pure_title_in_context_finds_apposition_in_proper_entity_snippets():
    """STU-440: the apposition evidence may live in the proper-name entity's snippets
    (NER attributes 'Dorian Havilliard, Crown Prince of Adarlan' to Dorian, not to the
    title entity). Both entities' contexts must be scanned."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    dorian = {
        "canonical_name": "Dorian Havilliard",
        "aliases": ["Dorian Havilliard", "Dorian"],
        "source_ids": ["e_dorian"],
    }
    crown_prince = {
        "canonical_name": "Crown Prince",
        "aliases": ["Crown Prince"],
        "source_ids": ["e_crown_prince"],
    }
    persons_full = _pf({
        # Title entity's own snippets contain only the conjunction sentence — correctly rejected.
        "e_crown_prince": {
            "mentions_by_chapter": {
                "ch05": [
                    "The Crown Prince, of course, sat with Perrington on their own two logs, far from her.",
                ]
            }
        },
        # The apposition lives in the proper entity's snippets.
        "e_dorian": {
            "mentions_by_chapter": {
                "ch02": [
                    "But, as you probably know, I'm Dorian Havilliard, Crown Prince of Adarlan.",
                ]
            }
        },
    })
    result = _detect_pure_title_in_context(
        dorian, crown_prince, persons_full,
        roles_naming_one_character=["crown prince"],
        connective_words=["the", "of"],
        determiners=["the"],
    )
    assert result is not None
    assert result["method"] == "pure_title"


def test_detect_pure_title_in_context_no_match_when_names_in_different_sentences():
    """
    'Crown Prince' and 'Cain' in the same multi-sentence snippet but different sentences
    must NOT be matched — they are distinct characters, not aliases.
    """
    from scripts.alias_resolution import _detect_pure_title_in_context
    cain = {
        "canonical_name": "Cain",
        "aliases": ["Cain"],
        "source_ids": ["e_cain"],
    }
    crown_prince = {
        "canonical_name": "Crown Prince",
        "aliases": ["Crown Prince"],
        "source_ids": ["e_crown_prince"],
    }
    persons_full = _pf({
        "e_crown_prince": {
            "mentions_by_chapter": {
                "ch07": [
                    # Cain and Crown Prince appear in different sentences — NOT the same person
                    "She managed to keep from killing Cain when he taunted her at training. "
                    "The Crown Prince didn't bother to show his face in her rooms again.",
                ]
            }
        },
        "e_cain": {
            "mentions_by_chapter": {"ch07": ["Cain flexed his muscles."]}
        },
    })
    result = _detect_pure_title_in_context(
        cain, crown_prince, persons_full,
        roles_naming_one_character=["crown prince"],
    )
    assert result is None


def test_resolve_aliases_pure_title_auto_merges_without_llm():
    """STU-281: 'Master' entity merged into 'Brullo' when its context contains 'Brullo'."""
    from scripts.alias_resolution import resolve_aliases
    brullo = {
        "canonical_name": "Brullo",
        "type": "PERSON",
        "aliases": ["Brullo"],
        "source_ids": ["e_brullo"],
        "relevant": True,
    }
    master = {
        "canonical_name": "Master",
        "type": "PERSON",
        "aliases": ["Master"],
        "source_ids": ["e_master"],
        "relevant": True,
    }
    persons_full = _pf({
        "e_master": {
            "mentions_by_chapter": {
                "ch05": [
                    "Master Brullo corrected her stance.",
                    "Brullo — the Master — nodded.",
                ]
            }
        },
        "e_brullo": {
            "mentions_by_chapter": {"ch05": ["Brullo watched the competitors."]}
        },
    })
    result = resolve_aliases(
        [brullo, master],
        persons_full=persons_full,
        llm_confirmer=None,
        roles_naming_one_character=["master"],
        connective_words=["the"],
    )
    assert len(result["entities"]) == 1
    entity = result["entities"][0]
    assert entity["canonical_name"] == "Brullo"
    assert "Master" in entity["aliases"]
    assert result["stats"]["merges_applied"] == 1
    assert result["stats"]["merges_by_method"].get("pure_title", 0) == 1


# ---------------------------------------------------------------------------
# STU-471: a modifier+role title ('Crown Prince') is a pure title even when the
# full phrase is NOT enumerated in role_words — only its head noun ('prince') is.
# The real cue_words role_words list carries 'prince', never 'crown prince'.
# ---------------------------------------------------------------------------

def test_is_pure_title_recognizes_modifier_plus_role_head():
    """'Crown Prince' is a title because its head noun 'prince' is a role word,
    without 'crown prince' being enumerated (STU-471). Title+surname stays non-title."""
    from scripts.alias_resolution import _is_pure_title
    role_words = ["prince", "king", "captain", "lord"]
    assert _is_pure_title("Crown Prince", role_words) is True
    assert _is_pure_title("High Lord", role_words) is True
    assert _is_pure_title("King", role_words) is True
    # title + surname must remain a title_alias case, not a pure title
    assert _is_pure_title("Captain Westfall", role_words) is False
    assert _is_pure_title("Dorian Havilliard", role_words) is False


def test_resolve_aliases_merges_crown_prince_without_phrase_in_role_words():
    """STU-471 gold case: 'Crown Prince' merges into 'Dorian Havilliard' via
    apposition, with role_words mirroring cue_words (head 'prince', no 'crown prince')."""
    from scripts.alias_resolution import resolve_aliases
    dorian = {
        "canonical_name": "Dorian Havilliard",
        "type": "PERSON",
        "aliases": ["Dorian Havilliard", "Dorian"],
        "source_ids": ["e_dorian"],
        "relevant": True,
    }
    crown_prince = {
        "canonical_name": "Crown Prince",
        "type": "PERSON",
        "aliases": ["Crown Prince"],
        "source_ids": ["e_crown_prince"],
        "relevant": True,
    }
    persons_full = _pf({
        "e_dorian": {
            "mentions_by_chapter": {
                "ch02": [
                    "But, as you probably know, I'm Dorian Havilliard, "
                    "Crown Prince of Adarlan.",
                ]
            }
        },
        "e_crown_prince": {
            "mentions_by_chapter": {
                "ch05": ["The Crown Prince strode from the court."]
            }
        },
    })
    result = resolve_aliases(
        [dorian, crown_prince],
        persons_full=persons_full,
        llm_confirmer=None,
        role_words=["prince", "king", "captain", "lord"],
        roles_naming_one_character=["crown prince"],
        connective_words=["the", "of"],
        determiners=["the"],
    )
    assert len(result["entities"]) == 1
    entity = result["entities"][0]
    assert entity["canonical_name"] == "Dorian Havilliard"
    assert "Crown Prince" in entity["aliases"]
    assert result["stats"]["merges_by_method"].get("pure_title", 0) == 1


# ---------------------------------------------------------------------------
# STU-559: a species is not a role
# ---------------------------------------------------------------------------

def _eragon_pair(title: str, other: str, sentence: str) -> tuple[dict, dict, dict]:
    title_entity = {
        "canonical_name": title, "type": "PERSON", "aliases": [title],
        "source_ids": ["e_title"], "relevant": True,
    }
    other_entity = {
        "canonical_name": other, "type": "PERSON", "aliases": [other],
        "source_ids": ["e_other"], "relevant": True,
    }
    persons_full = _pf({
        "e_title": {"mentions_by_chapter": {"ch01": [sentence]}},
        "e_other": {"mentions_by_chapter": {"ch01": []}},
    })
    return title_entity, other_entity, persons_full


def test_pure_title_never_fires_for_a_role_the_book_does_not_declare():
    """An undeclared book merges nothing here. 'rider' reaches role_words like any
    other role, but Eragon, Brom and Morzan are all Riders, so the bare name
    designates nobody — and the apposition ('a young Rider, Morzan') is genuine, so
    the apposition rule cannot catch this one."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    rider, morzan, persons_full = _eragon_pair(
        "Rider", "Morzan",
        "Then through some ill fortune he met a young Rider, Morzan—strong of body.",
    )
    assert _detect_pure_title_in_context(
        rider, morzan, persons_full,
        roles_naming_one_character=[], connective_words=["the", "a"], determiners=["the", "a"],
    ) is None
    # …and fires once the book declares the role names one character.
    assert _detect_pure_title_in_context(
        rider, morzan, persons_full,
        roles_naming_one_character=["rider"], connective_words=["the", "a"],
        determiners=["the", "a"],
    ) is not None


def test_a_title_two_characters_wear_names_neither():
    """Narnia declares no role: it writes 'Queen Lucy' and 'Queen Susan' both, so bare
    'Queen' names neither sister and merging it into Lucy steals Susan's mentions —
    STU-541's Mr/Mrs Beaver, reached through this detector. The question the book
    answers is whether the word names ONE character, not whether it is a title."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    queen, lucy, persons_full = _eragon_pair("Queen", "Lucy", "Long Live Queen Lucy!")
    assert _detect_pure_title_in_context(
        queen, lucy, persons_full, roles_naming_one_character=[],
    ) is None


def test_pure_title_reads_the_declared_roles_not_role_words():
    """The two vocabularies must not be confusable: role_words carries the species
    that caused the defect, so it is not what gates this path."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    shade, zarroc, persons_full = _eragon_pair(
        "Shade", "Zar'roc", "The Shade Durza raised his blade.",
    )
    assert _detect_pure_title_in_context(
        shade, zarroc, persons_full, roles_naming_one_character=["urgal"],
    ) is None


def test_a_comma_plus_a_determiner_is_enumeration_not_apposition():
    """Even when the book declares the role, a comma followed by a fresh determined
    noun phrase opens a new phrase that heads its own clause — the title is the
    subject of 'might have' / 'ceased', not a second name for the entity before it.
    Both sentences are live merges on main before STU-559: the antagonist into a
    sword, a species into a mountain."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    for title, other, sentence in [
        ("Shade", "Zar'roc", "As for Zar'roc, the Shade might have it with him ."),
        ("Urgal", "Farthen Dûr",
         "When the Shade's spirits flew across Farthen Dûr, the Urgals ceased fighting."),
    ]:
        title_entity, other_entity, persons_full = _eragon_pair(title, other, sentence)
        assert _detect_pure_title_in_context(
            title_entity, other_entity, persons_full,
            roles_naming_one_character=[title.lower()],
            connective_words=["the", "a", "of"], determiners=["the", "a"],
        ) is None, sentence


def test_a_dash_keeps_its_determiner():
    """The comma is the gate, not the determiner: 'Brullo — the Master —' is the
    appositive dash form STU-281 was built for and must keep merging."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    master, brullo, persons_full = _eragon_pair(
        "Master", "Brullo", "Brullo — the Master — nodded at Celaena.",
    )
    assert _detect_pure_title_in_context(
        master, brullo, persons_full,
        roles_naming_one_character=["master"],
        connective_words=["the"], determiners=["the"],
    ) is not None


def test_apposition_that_renames_without_re_determining_still_merges():
    """The measured true positives: no determiner after the comma."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    for title, other, sentence in [
        ("Crown Prince", "Dorian Havilliard",
         "I'm Dorian Havilliard, Crown Prince of Adarlan, perhaps now Crown Prince of Erilea."),
        ("Captain", "Chaol Westfall",
         "He introduced himself as Chaol Westfall, Captain of the Royal Guard, and bowed."),
    ]:
        title_entity, other_entity, persons_full = _eragon_pair(title, other, sentence)
        assert _detect_pure_title_in_context(
            title_entity, other_entity, persons_full,
            roles_naming_one_character=[title.lower()],
            connective_words=["the", "of"], determiners=["the"],
        ) is not None, sentence


# ---------------------------------------------------------------------------
# STU-430: pure_title must require apposition, not mere same-sentence presence
# ---------------------------------------------------------------------------

def test_detect_pure_title_in_context_no_match_when_title_and_name_conjoined():
    """STU-430: 'Crown Prince' and 'Perrington' in the SAME sentence but joined by
    'sat with' (conjunction, not apposition) are two distinct people — must NOT match.

    This is the exact Run 16 snippet that produced the bad merge.
    """
    from scripts.alias_resolution import _detect_pure_title_in_context
    crown_prince = {
        "canonical_name": "Crown Prince",
        "aliases": ["Crown Prince"],
        "source_ids": ["e_crown_prince"],
    }
    perrington = {
        "canonical_name": "Perrington",
        "aliases": ["Perrington", "Duke Perrington"],
        "source_ids": ["e_perrington"],
    }
    persons_full = _pf({
        "e_crown_prince": {
            "mentions_by_chapter": {
                "ch02": [
                    "The Crown Prince, of course, sat with Perrington "
                    "on their own two logs, far from her.",
                ]
            }
        },
        "e_perrington": {
            "mentions_by_chapter": {"ch02": ["Perrington scowled at the competitors."]}
        },
    })
    result = _detect_pure_title_in_context(
        crown_prince, perrington, persons_full,
        roles_naming_one_character=["crown prince"],
        connective_words=["the", "a", "an", "of"],
    )
    assert result is None


def test_resolve_aliases_does_not_merge_conjoined_title_and_name():
    """STU-430 regression: the Run 16 snippet must leave Crown Prince and Perrington
    as two separate entities — no bad fusion."""
    from scripts.alias_resolution import resolve_aliases
    crown_prince = {
        "canonical_name": "Crown Prince",
        "type": "PERSON",
        "aliases": ["Crown Prince"],
        "source_ids": ["e_crown_prince"],
        "relevant": True,
    }
    perrington = {
        "canonical_name": "Perrington",
        "type": "PERSON",
        "aliases": ["Perrington", "Duke Perrington"],
        "source_ids": ["e_perrington"],
        "relevant": True,
    }
    persons_full = _pf({
        "e_crown_prince": {
            "mentions_by_chapter": {
                "ch02": [
                    "The Crown Prince, of course, sat with Perrington "
                    "on their own two logs, far from her.",
                ]
            }
        },
        "e_perrington": {
            "mentions_by_chapter": {"ch02": ["Perrington scowled at the competitors."]}
        },
    })
    result = resolve_aliases(
        [crown_prince, perrington],
        persons_full=persons_full,
        llm_confirmer=None,
        roles_naming_one_character=["crown prince"],
        connective_words=["the", "a", "an", "of"],
    )
    names = sorted(e["canonical_name"] for e in result["entities"])
    assert names == ["Crown Prince", "Perrington"]
    assert result["stats"]["merges_applied"] == 0


def test_detect_pure_title_in_context_matches_apposition_with_connectors():
    """STU-430: true apposition ('Brullo — the Master —') must still merge when the
    only tokens between name and title are connective words / punctuation."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    brullo = {"canonical_name": "Brullo", "aliases": ["Brullo"], "source_ids": ["e_brullo"]}
    master = {"canonical_name": "Master", "aliases": ["Master"], "source_ids": ["e_master"]}
    persons_full = _pf({
        "e_master": {
            "mentions_by_chapter": {"ch05": ["Brullo — the Master — nodded at Celaena."]}
        },
        "e_brullo": {"mentions_by_chapter": {"ch05": ["Brullo watched."]}},
    })
    result = _detect_pure_title_in_context(
        brullo, master, persons_full,
        roles_naming_one_character=["master"], connective_words=["the", "a", "an"],
    )
    assert result is not None
    assert result["method"] == "pure_title"


def test_detect_role_symmetric_no_false_positive_zero_token_overlap():
    """
    Hollin and Queen Georgina share ≥2 family-relation buckets (via Dorian and the King)
    and have low direct cooccurrence, but share ZERO name tokens.
    They must NOT be flagged as a role-symmetric alias candidate.
    """
    from scripts.alias_resolution import _detect_role_symmetric_pairs

    hollin = {
        "canonical_name": "Hollin",
        "type": "PERSON",
        "aliases": ["Hollin"],
        "source_ids": [],
        "relevant": True,
    }
    queen_georgina = {
        "canonical_name": "Queen Georgina",
        "type": "PERSON",
        "aliases": ["Queen Georgina", "Georgina"],
        "source_ids": [],
        "relevant": True,
    }
    dorian = {
        "canonical_name": "Dorian",
        "type": "PERSON",
        "aliases": ["Dorian"],
        "source_ids": [],
        "relevant": True,
    }
    king = {
        "canonical_name": "King",
        "type": "PERSON",
        "aliases": ["King"],
        "source_ids": [],
        "relevant": True,
    }
    relationships = [
        # Both Hollin and Queen Georgina have a family relation toward Dorian and the King
        {"entity_a": "Hollin", "entity_b": "Dorian", "relationship_type": "family", "cooccurrence_count": 3},
        {"entity_a": "Queen Georgina", "entity_b": "Dorian", "relationship_type": "family", "cooccurrence_count": 5},
        {"entity_a": "Hollin", "entity_b": "King", "relationship_type": "family", "cooccurrence_count": 2},
        {"entity_a": "Queen Georgina", "entity_b": "King", "relationship_type": "family", "cooccurrence_count": 4},
        # Hollin and Queen Georgina rarely appear together
        {"entity_a": "Hollin", "entity_b": "Queen Georgina", "relationship_type": "family", "cooccurrence_count": 1},
    ]
    pairs = _detect_role_symmetric_pairs(
        [hollin, queen_georgina, dorian, king],
        relationships,
        min_shared=2,
        direct_cooc_max=3,
    )
    assert pairs == [], (
        f"Expected no candidates but got: "
        f"{[(p[0]['canonical_name'], p[1]['canonical_name']) for p in pairs]}"
    )


def test_detect_pure_title_in_context_no_match_when_sentences_split_by_curly_quote():
    """Snippet with !" between sentences (curly quote) must split correctly — Crown Prince and Philippa in different sentences → None."""
    from scripts.alias_resolution import _detect_pure_title_in_context
    snippet = (
        "\u201cThe Crown Prince won\u2019t be pleased if you\u2019re late!\u201d "
        "Celaena paused in the doorway, then looked back at Philippa."
    )
    # persons_full must be a dict keyed by source_id, with mentions_by_chapter
    persons_full = _pf({
        "entity_crown_prince": {
            "mentions_by_chapter": {"ch01": [snippet]},
        },
    })
    crown_prince = {
        "canonical_name": "Crown Prince",
        "type": "PERSON",
        "aliases": ["Crown Prince"],
        "source_ids": ["entity_crown_prince"],
    }
    philippa = {
        "canonical_name": "Philippa",
        "type": "PERSON",
        "aliases": ["Philippa"],
        "source_ids": [],
    }
    result = _detect_pure_title_in_context(
        crown_prince, philippa, persons_full=persons_full,
        roles_naming_one_character=["crown prince"],
    )
    assert result is None, f"Should not merge across curly-quote sentence boundary, got: {result}"


# --- Series seeding (STU-485) --------------------------------------------------


def _series_seed_registry() -> "Registry":
    from wiki_creator.registry import Registry

    return Registry.from_dict({
        "version": 1,
        "entities": [
            {
                "entity_id": "celaena_sardothien",
                "canonical_name": "Celaena",
                "entity_type": "PERSON",
                "aliases": ["Celaena", "Lillian Gordaina"],
                "mentions": [],
                "decisions": ["d_seed"],
                "books": ["01-book"],
                "first_book": "01-book",
            },
            {
                "entity_id": "nehemia",
                "canonical_name": "Nehemia",
                "entity_type": "PERSON",
                "aliases": ["Nehemia"],
                "mentions": [],
                "decisions": [],
                "books": ["01-book"],
                "first_book": "01-book",
            },
        ],
        "decisions": [
            {
                "decision_id": "d_seed",
                "strategy": "llm",
                "inputs": ["celaena_sardothien", "lillian_gordaina"],
                "evidence": "call me Lillian",
                "confidence": "high",
                "reversible": True,
            }
        ],
        "warnings": [],
    })


def test_series_seed_merges_known_aliases_without_local_evidence():
    """STU-485: identity established in tome 1 carries into tome 2 — no snippet
    in this tome links Celaena and Lillian, the series registry does."""
    seed = _series_seed_registry().seed_table()
    result = resolve_aliases([PERSON_A, PERSON_B], persons_full={}, seed_lookup=seed)
    assert len(result["entities"]) == 1
    merged = result["entities"][0]
    assert set(merged["aliases"]) >= {"Celaena", "Lillian Gordaina"}
    assert merged["alias_resolution"]["method"] == "series_seed"
    assert merged["alias_resolution"]["confidence"] == "high"
    assert "series registry" in merged["alias_resolution"]["evidence"][0]["snippet"]
    assert result["stats"]["merges_by_method"]["series_seed"] == 1


def test_series_seed_does_not_merge_distinct_known_entities():
    nehemia = {
        "canonical_name": "Nehemia",
        "type": "PERSON",
        "aliases": ["Nehemia"],
        "source_ids": ["entity_003"],
        "relevant": True,
    }
    seed = _series_seed_registry().seed_table()
    result = resolve_aliases([PERSON_A, nehemia], persons_full={}, seed_lookup=seed)
    assert len(result["entities"]) == 2
    assert result["stats"]["merges_by_method"]["series_seed"] == 0


def test_series_seed_ignores_same_surface_duplicates():
    """Two entities carrying the same known name are not folded by the seed —
    only distinct surfaces of one series entity replay a known alias link."""
    twin = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "aliases": ["Celaena"],
        "source_ids": ["entity_004"],
        "relevant": True,
    }
    seed = _series_seed_registry().seed_table()
    result = resolve_aliases([PERSON_A, twin], persons_full={}, seed_lookup=seed)
    assert len(result["entities"]) == 2
    assert result["stats"]["merges_by_method"]["series_seed"] == 0


def test_script_stdin_seeds_from_series_registry(tmp_path: Path):
    """End-to-end: a series registry on disk makes tome-N alias resolution
    merge known aliases with method=series_seed."""
    book_yaml = tmp_path / "library" / "author" / "series" / "books" / "02-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n", encoding="utf-8")
    processing = tmp_path / "library" / "author" / "series" / "processing_output" / "02-book"
    processing.mkdir(parents=True)

    series_path = tmp_path / "library" / "author" / "series" / "registry.json"
    _series_seed_registry().save(series_path)

    payload = {
        "previous_outputs": {"resolve-clusters": {"entities": [PERSON_A, PERSON_B], "narrator": None}},
        "additional_context": f"file_path: {book_yaml}\n",
    }
    result = subprocess.run(
        [sys.executable, "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, result.stderr
    assert "series seeding active" in result.stderr
    output = json.loads(result.stdout)
    assert len(output["entities"]) == 1
    assert output["entities"][0]["alias_resolution"]["method"] == "series_seed"


# tests/test_alias_resolution.py  (append)
import numpy as np

from wiki_creator.embedding_disambiguation import EmbeddingJudge
from scripts.alias_resolution import resolve_aliases


class _StubBackend:
    """Encodes by looking up the first token of each context in a table."""
    def __init__(self, table, dim=3):
        self.table = table
        self.dim = dim
    def encode(self, texts):
        rows = []
        for t in texts:
            key = t.split()[0].lower() if t.split() else ""
            vec = np.asarray(self.table.get(key, [0.0] * self.dim), dtype=np.float32)
            n = np.linalg.norm(vec)
            rows.append(vec / n if n else vec)
        return np.vstack(rows) if rows else np.zeros((0, self.dim), dtype=np.float32)


def _person(idx, name, source_id):
    return {
        "id": f"e{idx}", "canonical_name": name, "type": "PERSON",
        "relevant": True, "aliases": [name], "source_ids": [source_id],
    }


def _persons_full(mapping):
    # mapping: source_id -> list[str] context sentences
    return _pf({sid: {"mentions_by_chapter": {"c1": ctxs}, "mention_count": len(ctxs)}
                for sid, ctxs in mapping.items()})


def test_judge_none_is_backward_compatible():
    entities = [_person(0, "Celaena", "s0"), _person(1, "Nehemia", "s1")]
    pf = _persons_full({"s0": ["Celaena fought."], "s1": ["Nehemia ruled."]})
    without = resolve_aliases(list(entities), persons_full=pf, judge=None)
    baseline = resolve_aliases(list(entities), persons_full=pf)
    assert without == baseline


def test_embedding_proposer_merges_no_overlap_pair():
    # "Celaena" and "assassin" share no chars but share context direction.
    entities = [_person(0, "Celaena", "s0"), _person(1, "the assassin", "s1")]
    pf = _persons_full({"s0": ["Celaena drew steel."], "s1": ["assassin drew steel."]})
    backend = _StubBackend({"celaena": [1.0, 0.0, 0.0], "assassin": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, propose_threshold=0.86, veto_threshold=0.80)
    result = resolve_aliases(entities, persons_full=pf, judge=judge)
    assert len(result["entities"]) == 1
    assert result["stats"]["merges_by_method"]["embedding_disambiguation"] == 1


def test_embedding_veto_blocks_ambiguous_merge():
    # Reveal signal would fire, but dissimilar contexts must veto (no LLM call).
    entities = [_person(0, "Dorian", "s0"), _person(1, "Perrington", "s1")]
    pf = _persons_full({"s0": ["Dorian smiled warmly."], "s1": ["Perrington schemed coldly."]})
    reveal = ("revealed",)
    # Force a reveal signal by giving both a shared reveal context.
    pf["s0"].mentions_by_chapter["c1"].append("revealed Dorian Perrington")
    pf["s1"].mentions_by_chapter["c1"].append("revealed Dorian Perrington")
    backend = _StubBackend({"dorian": [1.0, 0.0, 0.0], "perrington": [0.0, 1.0, 0.0],
                            "revealed": [0.0, 0.0, 1.0]})
    judge = EmbeddingJudge(backend, propose_threshold=0.86, veto_threshold=0.80)

    def _llm(_payload):  # must never be called once vetoed
        raise AssertionError("LLM confirmer called despite veto")

    result = resolve_aliases(entities, persons_full=pf, reveal_words=reveal,
                             llm_confirmer=_llm, judge=judge)
    assert len(result["entities"]) == 2
    assert result["stats"]["embedding_vetoes"] >= 1
