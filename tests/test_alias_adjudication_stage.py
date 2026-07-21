"""The alias-adjudication stage pair — wiring, not adjudication.

Every test here is LLM-free: the verdict either comes from the cache or arrives
as the `alias-adjudication-verdict` call stage's output in the payload (STU-589).
Neither script may reach the network — the LLM invocation lives in the pipeline
YAML now, not in Python.
"""

import io
import json

import pytest
import yaml

from scripts import alias_adjudication as stage
from scripts import alias_adjudication_pre as pre_stage
from wiki_creator.alias_adjudication import roster_rows, save_merge_cache


REVEAL = "Lillian Gordaina was Celaena Sardothien, the world's most notorious assassin."

ENTITIES = [
    {"canonical_name": "Celaena Sardothien", "type": "PERSON", "aliases": ["Celaena"],
     "source_ids": ["e1"], "relevant": True},
    {"canonical_name": "Lillian Gordaina", "type": "PERSON", "aliases": ["Lady Lillian"],
     "source_ids": ["e2"], "relevant": True},
    {"canonical_name": "Dorian", "type": "PERSON", "aliases": ["Dorian"],
     "source_ids": ["e3"], "relevant": True},
    {"canonical_name": "Endovier", "type": "PLACE", "aliases": ["Endovier"],
     "source_ids": ["e4"], "relevant": True},
]

def _full(name, mentions_by_chapter):
    return {
        "type": "PERSON",
        "raw_mentions": [name],
        "first_seen": next(iter(mentions_by_chapter)),
        "mention_count": sum(len(v) for v in mentions_by_chapter.values()),
        "mentions_by_chapter": mentions_by_chapter,
    }


PERSONS_FULL = {
    "e1": _full("Celaena Sardothien", {"C40": [REVEAL], "C02": ["Celaena bowed to Dorian."]}),
    "e2": _full("Lillian Gordaina", {"C40": [REVEAL]}),
    "e3": _full("Dorian", {"C02": ["Dorian watched Celaena Sardothien."]}),
}


@pytest.fixture
def book(tmp_path):
    """A book laid out the way paths.py expects, with persons_full.json on disk."""
    books_dir = tmp_path / "author" / "series" / "books"
    books_dir.mkdir(parents=True)
    epub = books_dir / "01-a-book.epub"
    epub.write_bytes(b"not a real epub - only the path is used")

    processing = tmp_path / "author" / "series" / "processing_output" / "01-a-book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(
        json.dumps({"persons_full": PERSONS_FULL}), encoding="utf-8"
    )
    return epub, processing


def _payload(epub, entities=None, verdict=None):
    all_stage_outputs = {
        "alias-resolution": {
            "entities": [dict(e) for e in (entities or ENTITIES)],
            "narrator": "Celaena Sardothien",
            "stats": {"merges_applied": 0},
        }
    }
    if verdict is not None:
        all_stage_outputs["alias-adjudication-verdict"] = verdict
    return {
        "additional_context": yaml.safe_dump({"file_path": str(epub), "spacy_model": "en_core_web_lg"}),
        "all_stage_outputs": all_stage_outputs,
    }


def _run(monkeypatch, payload, module=stage) -> dict:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    module.main()
    return json.loads(out.getvalue())


def test_neither_script_can_shell_out():
    """The subprocess boundary is gone (STU-589): the LLM call lives in the
    pipeline YAML. A subprocess import reappearing here is the old loop back."""
    assert not hasattr(stage, "subprocess")
    assert not hasattr(pre_stage, "subprocess")


def _seed_cache(processing, merges, entities=None):
    persons = [e for e in (entities or ENTITIES) if e["type"] == "PERSON"]
    contexts = {
        "Celaena Sardothien": [REVEAL, "Celaena bowed to Dorian."],
        "Lillian Gordaina": [REVEAL],
        "Dorian": ["Dorian watched Celaena Sardothien."],
    }
    rows = roster_rows(persons, {p["canonical_name"]: contexts.get(p["canonical_name"], []) for p in persons})
    save_merge_cache(processing / "alias_adjudication.json", rows, merges)


def test_stage_merges_a_cached_pair_and_preserves_the_payload_shape(monkeypatch, book):
    epub, processing = book
    _seed_cache(processing, [{"a": "Celaena Sardothien", "b": "Lillian Gordaina",
                             "quote": REVEAL, "reason": "cover identity"}])
    result = _run(monkeypatch, _payload(epub))

    # Shape must survive: entity-classification reads this as all_stage_outputs.
    assert result["narrator"] == "Celaena Sardothien"
    assert result["stats"] == {"merges_applied": 0}

    merged = next(e for e in result["entities"] if "Lillian Gordaina" in e["aliases"])
    assert merged["aliases"] == ["Celaena", "Celaena Sardothien", "Lady Lillian", "Lillian Gordaina"]
    assert merged["alias_resolution"]["method"] == "context_adjudication"
    assert merged["alias_resolution"]["evidence"] == [
        {"method": "context_adjudication", "confidence": "medium", "snippet": REVEAL}
    ]
    assert merged["source_ids"] == ["e1", "e2"]


def test_stage_leaves_non_person_and_unmerged_entities_alone(monkeypatch, book):
    epub, processing = book
    _seed_cache(processing, [{"a": "Celaena Sardothien", "b": "Lillian Gordaina",
                             "quote": REVEAL, "reason": "cover identity"}])
    result = _run(monkeypatch, _payload(epub))

    # One merged PERSON in the pair's place, the untouched PERSON and the PLACE after it.
    assert [e["canonical_name"] for e in result["entities"]] == ["Celaena", "Dorian", "Endovier"]
    assert next(e for e in result["entities"] if e["canonical_name"] == "Endovier")["type"] == "PLACE"


def test_stage_merges_nothing_when_the_verdict_is_empty(monkeypatch, book):
    epub, processing = book
    _seed_cache(processing, [])
    result = _run(monkeypatch, _payload(epub))

    assert result["entities"] == ENTITIES


def test_stage_merges_nothing_when_the_verdict_cannot_be_obtained(monkeypatch, book, capsys):
    """No cache and no call output (child failed under on_failure: continue, or
    was skipped): merge nothing, and say so.

    STU-538's asymmetry: a false merge deletes a real character and propagates to
    every later tome; a false negative leaves two individually-correct pages.
    """
    epub, _ = book

    result = _run(monkeypatch, _payload(epub))

    assert result["entities"] == ENTITIES
    assert "no verdict" in capsys.readouterr().err


def test_stage_applies_the_call_verdict_and_caches_it(monkeypatch, book):
    epub, processing = book
    verdict = {"merge": [{"a": "Celaena Sardothien", "b": "Lillian Gordaina",
                          "quote": REVEAL, "reason": "cover identity"}]}

    result = _run(monkeypatch, _payload(epub, verdict=verdict))

    merged = next(e for e in result["entities"] if "Lillian Gordaina" in e["aliases"])
    assert merged["alias_resolution"]["method"] == "context_adjudication"
    cached = json.loads((processing / "alias_adjudication.json").read_text(encoding="utf-8"))
    assert cached["merge"] == [
        {"a": "Celaena Sardothien", "b": "Lillian Gordaina", "quote": REVEAL, "reason": "cover identity"}
    ]


def test_stage_ignores_a_verdict_for_a_roster_of_one(monkeypatch, book):
    epub, _ = book
    entities = [ENTITIES[0], ENTITIES[3]]
    assert _run(monkeypatch, _payload(epub, entities))["entities"] == entities


def test_pre_asks_for_a_verdict_when_the_cache_is_cold(monkeypatch, book):
    epub, _ = book

    result = _run(monkeypatch, _payload(epub), module=pre_stage)

    assert result["needs_verdict"] is True
    assert "Celaena Sardothien" in result["roster"]
    assert "Lillian Gordaina" in result["roster"]
    assert "Endovier" not in result["roster"]


def test_pre_skips_the_call_on_a_cache_hit(monkeypatch, book):
    epub, processing = book
    _seed_cache(processing, [])

    assert _run(monkeypatch, _payload(epub), module=pre_stage)["needs_verdict"] is False


def test_pre_skips_the_call_for_a_roster_of_one(monkeypatch, book):
    epub, _ = book
    entities = [ENTITIES[0], ENTITIES[3]]
    assert _run(monkeypatch, _payload(epub, entities), module=pre_stage)["needs_verdict"] is False


def test_a_same_named_entity_of_another_type_is_not_touched(monkeypatch, book):
    """A PERSON and a PLACE may legally share a canonical_name (STU-506); only the
    PERSON was on the roster, so only the PERSON may be folded."""
    epub, processing = book
    homonym = {"canonical_name": "Dorian", "type": "PLACE", "aliases": ["Dorian"],
               "source_ids": ["e5"], "relevant": True}
    entities = ENTITIES + [homonym]
    _seed_cache(processing, [{"a": "Celaena Sardothien", "b": "Lillian Gordaina",
                             "quote": REVEAL, "reason": "cover identity"}], entities)
    result = _run(monkeypatch, _payload(epub, entities))

    assert homonym in result["entities"]
    assert [e["type"] for e in result["entities"]] == ["PERSON", "PERSON", "PLACE", "PLACE"]


def test_stage_skips_a_second_merge_that_chains_off_the_first(monkeypatch, book, capsys):
    """A=B and B=C is a transitive claim the classifier was never asked to make."""
    epub, processing = book
    _seed_cache(processing, [
        {"a": "Celaena Sardothien", "b": "Lillian Gordaina", "quote": REVEAL, "reason": "cover identity"},
        {"a": "Lillian Gordaina", "b": "Dorian", "quote": REVEAL, "reason": "chained"},
    ])
    result = _run(monkeypatch, _payload(epub))

    assert "Dorian" in [e["canonical_name"] for e in result["entities"]]
    assert "already merged" in capsys.readouterr().err
