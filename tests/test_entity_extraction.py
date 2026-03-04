"""Tests for scripts/entity_extraction.py — spaCy NER stage."""
import pytest
import spacy
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.entity_extraction import extract_entities, extract_context, split_entities, KEPT_LABELS, _is_valid_mention


@pytest.fixture(scope="module")
def nlp():
    """Small English model for fast tests."""
    return spacy.load("en_core_web_sm")


def test_extracts_person_entity(nlp):
    """A clearly named person should appear in the registry."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Harry Potter lived at number four, Privet Drive. He was a wizard."}
    ]
    result = extract_entities(chapters, nlp)
    all_mentions = [
        m
        for entry in result["entities"].values()
        for m in entry["raw_mentions"]
    ]
    assert any("Harry" in m or "Potter" in m for m in all_mentions), (
        f"Expected a Harry/Potter mention, got: {all_mentions}"
    )


def test_filters_irrelevant_types(nlp):
    """DATE and CARDINAL entities should be excluded."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "It was January 1st, 2024. There were 42 chairs."}
    ]
    result = extract_entities(chapters, nlp)
    assert result["entities"] == {}, (
        f"Expected empty registry, got: {result['entities']}"
    )


def test_accumulates_cross_chapter(nlp):
    """Same surface form in two chapters → one registry entry with both chapters."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into the room and greeted everyone."},
        {"id": "ch02", "title": "Chapter 2", "content": "Alice sat down quietly by the window."},
    ]
    result = extract_entities(chapters, nlp)
    alice_entries = [
        entry for entry in result["entities"].values()
        if any("alice" in m.lower() for m in entry["raw_mentions"])
    ]
    assert len(alice_entries) == 1, f"Expected 1 Alice entry, got {len(alice_entries)}"
    entry = alice_entries[0]
    assert "ch01" in entry["mentions_by_chapter"], "ch01 should be in mentions_by_chapter"
    assert "ch02" in entry["mentions_by_chapter"], "ch02 should be in mentions_by_chapter"


def test_context_does_not_exceed_3_sentences(nlp):
    """Context extracted around an entity should be at most ~3 sentences."""
    content = (
        "The wind blew hard across the moor. "
        "Alice entered the grand hall and looked around. "
        "She noticed the paintings on the wall. "
        "The flames in the fireplace danced wildly. "
        "Nobody spoke a single word."
    )
    chapters = [{"id": "ch01", "title": "Chapter 1", "content": content}]
    result = extract_entities(chapters, nlp)
    for entry in result["entities"].values():
        for contexts in entry["mentions_by_chapter"].values():
            for ctx in contexts:
                approx_sentences = ctx.count(". ") + ctx.count("! ") + ctx.count("? ") + 1
                assert approx_sentences <= 4, (
                    f"Context has too many sentences ({approx_sentences}): {ctx!r}"
                )


def test_no_raw_chapter_content_in_registry(nlp):
    """No registry value should equal the full chapter content."""
    content = (
        "Sherlock Holmes walked down Baker Street in the fog. "
        "He turned his collar up against the chill. "
        "Watson followed close behind."
    )
    chapters = [{"id": "ch01", "title": "Chapter 1", "content": content}]
    result = extract_entities(chapters, nlp)
    for entry in result["entities"].values():
        for contexts in entry["mentions_by_chapter"].values():
            for ctx in contexts:
                assert ctx != content, (
                    f"Context must not be the full chapter text. Got: {ctx!r}"
                )


def test_entity_ids_are_sequential(nlp):
    """Entity IDs should be entity_001, entity_002, etc."""
    chapters = [
        {
            "id": "ch01",
            "title": "Chapter 1",
            "content": "Elizabeth Bennet met Mr. Darcy at the ball in London.",
        }
    ]
    result = extract_entities(chapters, nlp)
    ids = sorted(result["entities"].keys())
    for i, entity_id in enumerate(ids, start=1):
        assert entity_id == f"entity_{i:03d}", f"Expected entity_{i:03d}, got {entity_id}"


def test_first_seen_is_correct(nlp):
    """first_seen should be the chapter ID where the entity first appears."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Sherlock Holmes visited London on a grey morning."},
        {"id": "ch02", "title": "Chapter 2", "content": "Sherlock Holmes walked through London again the next day."},
    ]
    result = extract_entities(chapters, nlp)
    london_entries = [
        entry for entry in result["entities"].values()
        if any("london" in m.lower() for m in entry["raw_mentions"])
    ]
    assert len(london_entries) >= 1, "London should be recognized as a GPE entity"
    assert london_entries[0]["first_seen"] == "ch01"


def test_entity_type_is_included(nlp):
    """Each entity entry should have a type field."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London."}
    ]
    result = extract_entities(chapters, nlp)
    for entry in result["entities"].values():
        assert "type" in entry, f"Missing 'type' field in entry: {entry}"
        assert entry["type"] in {"PERSON", "PLACE", "ORG", "OTHER"}


# --- split_entities tests ---

def test_split_entities_for_resolution_has_no_mentions_by_chapter(nlp):
    """entities_for_resolution must not include mentions_by_chapter."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London."}
    ]
    result = extract_entities(chapters, nlp)
    entities_for_resolution, _ = split_entities(result["entities"])
    for entry in entities_for_resolution.values():
        assert "mentions_by_chapter" not in entry, (
            f"entities_for_resolution must not contain mentions_by_chapter: {entry}"
        )


def test_split_entities_full_has_mentions_by_chapter(nlp):
    """entities_full must include mentions_by_chapter."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    for entry in entities_full.values():
        assert "mentions_by_chapter" in entry, (
            f"entities_full must contain mentions_by_chapter: {entry}"
        )


def test_split_entities_same_keys(nlp):
    """Both split outputs must have the same entity IDs."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Sherlock Holmes visited Watson in London."}
    ]
    result = extract_entities(chapters, nlp)
    entities_for_resolution, entities_full = split_entities(result["entities"])
    assert set(entities_for_resolution.keys()) == set(entities_full.keys())


def test_split_entities_for_resolution_has_core_fields(nlp):
    """entities_for_resolution entries must have type, raw_mentions, and first_seen."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Elizabeth Bennet met Mr. Darcy in London."}
    ]
    result = extract_entities(chapters, nlp)
    entities_for_resolution, _ = split_entities(result["entities"])
    for entity_id, entry in entities_for_resolution.items():
        assert "type" in entry, f"[{entity_id}] missing 'type'"
        assert "raw_mentions" in entry, f"[{entity_id}] missing 'raw_mentions'"
        assert "first_seen" in entry, f"[{entity_id}] missing 'first_seen'"


# --- --test mode integration test ---

def test_test_mode_exits_successfully():
    """python scripts/entity_extraction.py --test should exit 0 and print a summary."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "scripts/entity_extraction.py", "--test"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"--test mode failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    assert "Total entities extracted:" in result.stdout, (
        f"Expected entity count in output. Got:\n{result.stdout}"
    )
    assert "Sample (first 3 entities" in result.stdout, (
        f"Expected entity sample in output. Got:\n{result.stdout}"
    )

# --- _is_valid_mention filter tests ---


def test_is_valid_mention_rejects_too_short():
    assert _is_valid_mention("E") is False
    assert _is_valid_mention("Me") is False
    assert _is_valid_mention("II") is False
    assert _is_valid_mention("Ah") is False
    assert _is_valid_mention("Or") is False


def test_is_valid_mention_rejects_lowercase_start():
    assert _is_valid_mention("objectai") is False
    assert _is_valid_mention("plaidais-je") is False


def test_is_valid_mention_rejects_non_alpha_start():
    """Dash-prefixed dialog fragments like '— Liberté' must be rejected."""
    assert _is_valid_mention("— Liberté") is False
    assert _is_valid_mention("  ") is False


def test_is_valid_mention_accepts_valid_names():
    assert _is_valid_mention("David Martín") is True
    assert _is_valid_mention("Barcelone") is True
    assert _is_valid_mention("Merci") is True   # ambiguous — left to LLM
    assert _is_valid_mention("Balthazar") is True
    assert _is_valid_mention("Don Basilio") is True
