"""Tests for scripts/wiki_preparation.py."""

from pathlib import Path

from scripts.wiki_preparation import (
    build_entity_bundle,
    write_batches,
)


def _registries():
    persons = {
        "p1": {
            "first_seen": "ch01",
            "mentions_by_chapter": {
                "ch01": ["Dorian parle avec Chaol."],
                "ch02": ["Dorian rencontre Celaena."],
            },
        },
        "p2": {
            "first_seen": "ch01",
            "mentions_by_chapter": {
                "ch01": ["Celaena observe Dorian."],
            },
        },
        "p3": {
            "first_seen": "ch02",
            "mentions_by_chapter": {
                "ch02": ["Chaol protège Dorian."],
            },
        },
        "p4": {
            "first_seen": "ch03",
            "mentions_by_chapter": {
                "ch03": ["Le roi parle a Dorian."],
            },
        },
        "p5": {
            "first_seen": "ch04",
            "mentions_by_chapter": {
                "ch04": ["Nehemia voit Dorian."],
            },
        },
        "p6": {
            "first_seen": "ch05",
            "mentions_by_chapter": {
                "ch05": ["Cain defie Dorian."],
            },
        },
        "p7": {
            "first_seen": "ch06",
            "mentions_by_chapter": {
                "ch06": ["Nox suit Dorian."],
            },
        },
    }
    return persons, {}, {}, {}


def test_build_entity_bundle_builds_sorted_limited_related_context():
    persons, places, orgs, events = _registries()
    entities_by_name = {
        "Dorian Havilliard": {
            "canonical_name": "Dorian Havilliard",
            "type": "PERSON",
            "importance": "principal",
            "source_ids": ["p1"],
        },
        "Celaena": {
            "canonical_name": "Celaena",
            "type": "PERSON",
            "importance": "principal",
            "source_ids": ["p2"],
        },
        "Chaol Westfall": {
            "canonical_name": "Chaol Westfall",
            "type": "PERSON",
            "importance": "principal",
            "source_ids": ["p3"],
        },
        "The King": {
            "canonical_name": "The King",
            "type": "PERSON",
            "importance": "principal",
            "source_ids": ["p4"],
        },
        "Nehemia": {
            "canonical_name": "Nehemia",
            "type": "PERSON",
            "importance": "secondary",
            "source_ids": ["p5"],
        },
        "Cain": {
            "canonical_name": "Cain",
            "type": "PERSON",
            "importance": "secondary",
            "source_ids": ["p6"],
        },
        "Nox": {
            "canonical_name": "Nox",
            "type": "PERSON",
            "importance": "figurant",
            "source_ids": ["p7"],
        },
    }
    relationships = [
        {"entity_a": "Dorian Havilliard", "entity_b": "Celaena", "cooccurrence_count": 175},
        {"entity_a": "Chaol Westfall", "entity_b": "Dorian Havilliard", "cooccurrence_count": 116},
        {"entity_a": "Dorian Havilliard", "entity_b": "The King", "cooccurrence_count": 99},
        {"entity_a": "Nehemia", "entity_b": "Dorian Havilliard", "cooccurrence_count": 95},
        {"entity_a": "Dorian Havilliard", "entity_b": "Cain", "cooccurrence_count": 70},
        {"entity_a": "Nox", "entity_b": "Dorian Havilliard", "cooccurrence_count": 40},
        {"entity_a": "Dorian Havilliard", "entity_b": "", "cooccurrence_count": 999},
    ]

    bundle = build_entity_bundle(
        entities_by_name["Dorian Havilliard"],
        relationships,
        persons,
        places,
        orgs,
        events,
        entities_by_name,
    )

    related = bundle["related_context"]
    assert len(related) == 5
    assert [r["related_name"] for r in related] == [
        "Celaena",
        "Chaol Westfall",
        "The King",
        "Nehemia",
        "Cain",
    ]
    assert related[0]["cooccurrence_count"] == 175
    assert related[0]["related_type"] == "PERSON"
    assert related[0]["related_importance"] == "principal"
    assert len(related[0]["support_snippets"]) <= 2


def test_build_entity_bundle_related_context_empty_without_relationships():
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Dorian Havilliard",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
    }
    entities_by_name = {
        "Dorian Havilliard": entity,
    }

    bundle = build_entity_bundle(
        entity,
        [],
        persons,
        places,
        orgs,
        events,
        entities_by_name,
    )

    assert bundle["related_context"] == []


def test_write_batches_counts_related_context_chars_for_splitting(tmp_path: Path):
    long_snippet = "x" * 12000
    entities = [
        {
            "canonical_name": "Dorian Havilliard",
            "importance": "principal",
            "type": "PERSON",
            "context_by_chapter": {"ch01": ["court"]},
            "related_context": [{"support_snippets": [long_snippet]}],
        },
        {
            "canonical_name": "Chaol Westfall",
            "importance": "principal",
            "type": "PERSON",
            "context_by_chapter": {"ch01": ["guard"]},
            "related_context": [{"support_snippets": [long_snippet]}],
        },
    ]

    class _Paths:
        wiki_inputs = tmp_path

    batches = write_batches(entities, narrator=None, paths=_Paths())

    assert len(batches) == 2
