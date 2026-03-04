"""Tests for scripts/entity_extraction.py — spaCy NER stage."""
import pytest
import spacy
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.entity_extraction import extract_entities, extract_context, KEPT_LABELS


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
        {"id": "ch01", "title": "Chapter 1", "content": "The city of London was quiet."},
        {"id": "ch02", "title": "Chapter 2", "content": "London was busy the next day."},
    ]
    result = extract_entities(chapters, nlp)
    london_entries = [
        entry for entry in result["entities"].values()
        if any("london" in m.lower() for m in entry["raw_mentions"])
    ]
    if london_entries:
        assert london_entries[0]["first_seen"] == "ch01"
