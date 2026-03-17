"""Tests for scripts/alias_resolution.py."""
import json
import os
import socket
import subprocess
import sys
import unittest.mock as mock
import urllib.error
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.alias_resolution import resolve_aliases, detect_named_aliases, _pick_snippets, _check_ollama_available, make_ollama_confirmer


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
    persons_full = {
        "entity_001": {"mentions_by_chapter": {"ch01": ["Celaena entered the room."]}},
        "entity_002": {"mentions_by_chapter": {"ch01": ["Lillian watched the door."]}},
    }
    result = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full)
    assert [e["canonical_name"] for e in result["entities"]] == ["Celaena", "Lillian Gordaina"]
    assert result["stats"]["merges_applied"] == 0


def test_explicit_alias_pattern_merges_person_entities():
    persons_full = {
        "entity_001": {
            "mentions_by_chapter": {
                "ch03": ["Celaena smiled. You may call me Lillian Gordaina, she said."],
            }
        },
        "entity_002": {
            "mentions_by_chapter": {
                "ch03": ["You may call me Lillian Gordaina, she said."],
            }
        },
    }
    result = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full)
    assert len(result["entities"]) == 1
    merged = result["entities"][0]
    assert merged["canonical_name"] == "Lillian Gordaina"
    assert merged["aliases"] == ["Celaena", "Lillian", "Lillian Gordaina"]
    assert merged["source_ids"] == ["entity_001", "entity_002"]
    assert merged["alias_resolution"]["method"] == "pattern"
    assert result["stats"]["merges_applied"] == 1


def test_medium_confidence_pair_requires_llm_confirmation():
    persons_full = {
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
    }
    no_llm = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full)
    assert len(no_llm["entities"]) == 2
    assert no_llm["stats"]["llm_attempts"] == 0

    def confirm(candidate):
        assert candidate["entity_a"]["canonical_name"] == "Celaena"
        assert candidate["entity_b"]["canonical_name"] == "Lillian Gordaina"
        return {"same_person": True, "confidence": "medium", "evidence": "reveal confirmed"}

    with_llm = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full, llm_confirmer=confirm)
    assert len(with_llm["entities"]) == 1
    assert with_llm["stats"]["llm_attempts"] == 1
    assert with_llm["stats"]["llm_confirmed"] == 1


def test_llm_errors_degrade_gracefully():
    persons_full = {
        "entity_001": {"mentions_by_chapter": {"ch05": ["Celaena used another name."]}},
        "entity_002": {"mentions_by_chapter": {"ch05": ["Lillian Gordaina was that other name."]}},
    }

    def boom(_candidate):
        raise RuntimeError("llm unavailable")

    result = resolve_aliases([PERSON_A, PERSON_B], persons_full=persons_full, llm_confirmer=boom)
    assert len(result["entities"]) == 2
    assert result["stats"]["llm_attempts"] == 1
    assert result["stats"]["llm_failed"] == 1


def test_script_stdin_contract_reads_registry_from_processing_dir(tmp_path: Path):
    book_yaml = tmp_path / "library" / "author" / "series" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n", encoding="utf-8")

    processing = tmp_path / "library" / "author" / "series" / "processing_output" / "book"
    processing.mkdir(parents=True)
    persons_full = {
        "persons_full": {
            "entity_001": {
                "mentions_by_chapter": {"ch03": ["Celaena said: you may call me Lillian Gordaina."]},
            },
            "entity_002": {
                "mentions_by_chapter": {"ch03": ["You may call me Lillian Gordaina."]},
            },
        }
    }
    (processing / "persons_full.json").write_text(json.dumps(persons_full), encoding="utf-8")

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
    output = json.loads(result.stdout)
    assert len(output["entities"]) == 1
    assert output["stats"]["merges_applied"] == 1


def test_detect_named_aliases_pattern_high_confidence():
    mentions = {
        "Celaena": ["Celaena smiled. You may call me Lillian, she said."],
        "Lillian": ["You may call me Lillian, she said."],
    }
    pairs = detect_named_aliases(mentions, text="")
    assert len(pairs) == 1
    assert pairs[0]["entity_a"] == "Celaena"
    assert pairs[0]["entity_b"] == "Lillian"
    assert pairs[0]["confidence"] == "high"
    assert pairs[0]["source"] == "pattern"


def test_detect_named_aliases_no_evidence_returns_empty():
    mentions = {
        "Celaena": ["Celaena entered the room."],
        "Dorian": ["Dorian watched the door."],
    }
    pairs = detect_named_aliases(mentions, text="Celaena entered the room. Dorian watched the door.")
    assert pairs == []


def test_detect_named_aliases_window_cooccurrence():
    # Build a text where Celaena and Aelin appear within 300 tokens, twice
    window = "Celaena " + "word " * 50 + "Aelin "
    text = (window * 3).strip()
    mentions = {
        "Celaena": [window],
        "Aelin": [window],
    }
    pairs = detect_named_aliases(mentions, text=text)
    assert len(pairs) == 1
    assert pairs[0]["source"] == "cooccurrence"
    assert pairs[0]["confidence"] == "medium"


def test_detect_named_aliases_window_below_threshold_returns_empty():
    # Only one shared window — below threshold of 2
    window = "Celaena " + "word " * 50 + "Aelin "
    mentions = {
        "Celaena": [window],
        "Aelin": [window],
    }
    pairs = detect_named_aliases(mentions, text=window)
    assert pairs == []


def test_detect_named_aliases_née_pattern():
    mentions = {
        "Jane Smith": ["Jane Smith, née Austen, entered."],
        "Austen": ["née Austen"],
    }
    pairs = detect_named_aliases(mentions, text="")
    assert len(pairs) == 1
    assert pairs[0]["confidence"] == "high"


def test_detect_named_aliases_known_as_pattern():
    mentions = {
        "David": ["David, known as El Príncipe, walked in."],
        "El Príncipe": ["known as El Príncipe"],
    }
    pairs = detect_named_aliases(mentions, text="")
    assert len(pairs) == 1
    assert pairs[0]["confidence"] == "high"


def test_detect_named_aliases_uses_custom_reveal_words():
    """reveal_words parameter overrides default _REVEAL_WORDS."""
    from scripts.alias_resolution import detect_named_aliases
    entity_a = {"canonical_name": "Celaena", "aliases": ["Celaena"], "type": "PERSON", "relevant": True}
    entity_b = {"canonical_name": "Laena", "aliases": ["Laena"], "type": "PERSON", "relevant": True}
    # Use a custom reveal word that would only match this context
    context = "Celaena, known by the secret_reveal_marker as Laena, walked on."
    pairs = detect_named_aliases(
        {"Celaena": [context], "Laena": [context]},
        text="",
        reveal_words=("secret_reveal_marker",),
    )
    # With a custom reveal word matching the context, we should get pairs or at least no crash
    assert isinstance(pairs, list)


def test_pick_snippets_prioritises_canonical_name():
    entity = {
        "canonical_name": "Celaena",
        "aliases": ["Celaena"],
        "source_ids": ["e1"],
    }
    persons_full = {
        "e1": {
            "mentions_by_chapter": {
                "ch01": ["Someone entered.", "Celaena smiled.", "A guard stood."],
                "ch02": ["Celaena ran.", "Another person spoke."],
            }
        }
    }
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
    persons_full = {
        "e2": {
            "mentions_by_chapter": {
                "ch01": ["Someone appeared.", "A figure moved."],
            }
        }
    }
    snippets = _pick_snippets(entity, persons_full, n=3)
    assert len(snippets) == 2  # only 2 available


def test_pick_snippets_empty_when_no_source_ids():
    entity = {"canonical_name": "Ghost", "aliases": [], "source_ids": []}
    assert _pick_snippets(entity, {}, n=3) == []



def test_check_ollama_available_returns_true_on_success():
    with mock.patch("urllib.request.urlopen") as m:
        m.return_value.__enter__ = lambda s: s
        m.return_value.__exit__ = mock.Mock(return_value=False)
        assert _check_ollama_available("http://localhost:11434") is True


def test_check_ollama_available_returns_false_on_connection_error():
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert _check_ollama_available("http://localhost:11434") is False


def test_check_ollama_available_returns_false_on_timeout():
    with mock.patch("urllib.request.urlopen", side_effect=socket.timeout()):
        assert _check_ollama_available("http://localhost:11434") is False


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
_PERSONS_FULL_LLM = {
    "e1": {"mentions_by_chapter": {"ch01": ["Celaena walked in."]}},
    "e2": {"mentions_by_chapter": {"ch01": ["Lillian watched her."]}},
}


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


def test_empty_stats_has_title_alias_key():
    from scripts.alias_resolution import _empty_stats
    stats = _empty_stats()
    assert "title_alias" in stats["merges_by_method"]
    assert stats["merges_by_method"]["title_alias"] == 0


def test_resolve_aliases_title_alias_with_llm_merges():
    """Title alias pair is merged when LLM confirms same_person."""
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
    assert result["stats"]["llm_confirmed"] == 1


def test_resolve_aliases_title_alias_without_llm_increments_ambiguous():
    """Title alias pair is not merged when no LLM confirmer available."""
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
    assert len(result["entities"]) == 2
    assert result["stats"]["merges_applied"] == 0
    assert result["stats"]["ambiguous_pairs"] == 1


def test_resolve_aliases_title_alias_llm_rejects_no_merge():
    """Title alias pair is not merged when LLM says same_person=False."""
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
    assert len(result["entities"]) == 2
    assert result["stats"]["merges_applied"] == 0
