"""Tests for scripts/wiki_preparation.py."""

from pathlib import Path

from scripts.wiki_preparation import (
    build_entity_bundle,
    extract_context,
    stage_outputs_from_payload,
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


def test_extract_context_falls_back_across_registries_for_retyped_entity():
    persons, places, orgs, events = _registries()
    # Source id exists in persons registry, but entity type was retagged to PLACE.
    entity = {
        "canonical_name": "Adarlan",
        "type": "PLACE",
        "source_ids": ["p1"],
    }
    ctx = extract_context(entity, persons, places, orgs, events)
    assert "ch01" in ctx
    assert ctx["ch01"][0] == "Dorian parle avec Chaol."


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


def test_build_entity_bundle_adds_chapter_summary_context_for_person():
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Dorian Havilliard",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
    }
    entities_by_name = {"Dorian Havilliard": entity}
    chapter_summaries = {
        "ch01": {
            "chapter_id": "ch01",
            "chapter_title": "Chapter 1",
            "summary_bullets": ["Dorian meets Chaol."],
        },
        "ch02": {
            "chapter_id": "ch02",
            "chapter_title": "Chapter 2",
            "summary_bullets": ["Dorian discusses strategy."],
        },
        "ch03": {
            "chapter_id": "ch03",
            "chapter_title": "Chapter 3",
            "summary_bullets": ["This chapter should be ignored for Dorian."],
        },
    }

    bundle = build_entity_bundle(
        entity,
        [],
        persons,
        places,
        orgs,
        events,
        entities_by_name,
        chapter_summaries=chapter_summaries,
        chapter_summary_max=8,
    )

    assert [x["chapter_key"] for x in bundle["chapter_summary_context"]] == ["ch01", "ch02"]


def test_build_entity_bundle_adds_chapter_summary_context_when_summaries_are_keyed_by_title():
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Dorian Havilliard",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
    }
    entities_by_name = {"Dorian Havilliard": entity}
    chapter_summaries = {
        "Chapter 1": {
            "chapter_id": "ch01",
            "chapter_title": "Chapter 1",
            "summary_bullets": ["Dorian meets Chaol."],
        },
        "Chapter 2": {
            "chapter_id": "ch02",
            "chapter_title": "Chapter 2",
            "summary_bullets": ["Dorian discusses strategy."],
        },
    }

    bundle = build_entity_bundle(
        entity,
        [],
        persons,
        places,
        orgs,
        events,
        entities_by_name,
        chapter_summaries=chapter_summaries,
        chapter_summary_max=8,
    )

    assert [x["chapter_key"] for x in bundle["chapter_summary_context"]] == ["ch01", "ch02"]


def test_build_entity_bundle_skips_chapter_summary_context_for_non_person():
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Adarlan",
        "type": "PLACE",
        "importance": "secondary",
        "source_ids": [],
    }
    entities_by_name = {"Adarlan": entity}
    chapter_summaries = {
        "ch01": {
            "chapter_id": "ch01",
            "chapter_title": "Chapter 1",
            "summary_bullets": ["Dorian enters the city."],
        }
    }

    bundle = build_entity_bundle(
        entity,
        [],
        persons,
        places,
        orgs,
        events,
        entities_by_name,
        chapter_summaries=chapter_summaries,
        chapter_summary_max=8,
    )

    assert bundle["chapter_summary_context"] == []


def test_build_entity_bundle_limits_chapter_summary_context_size():
    persons, places, orgs, events = _registries()
    persons["p1"]["mentions_by_chapter"] = {
        f"ch{i:02d}": [f"Dorian mention {i}."] for i in range(1, 13)
    }
    entity = {
        "canonical_name": "Dorian Havilliard",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
    }
    entities_by_name = {"Dorian Havilliard": entity}
    chapter_summaries = {
        f"ch{i:02d}": {
            "chapter_id": f"ch{i:02d}",
            "chapter_title": f"Chapter {i}",
            "summary_bullets": [f"Bullet {i}"],
        }
        for i in range(1, 13)
    }

    bundle = build_entity_bundle(
        entity,
        [],
        persons,
        places,
        orgs,
        events,
        entities_by_name,
        chapter_summaries=chapter_summaries,
        chapter_summary_max=4,
    )

    assert len(bundle["chapter_summary_context"]) == 4


def test_write_batches_counts_chapter_summary_context_chars_for_splitting(tmp_path: Path):
    long_bullet = "y" * 12000
    entities = [
        {
            "canonical_name": "Dorian Havilliard",
            "importance": "principal",
            "type": "PERSON",
            "context_by_chapter": {"ch01": ["court"]},
            "related_context": [],
            "chapter_summary_context": [{"chapter_key": "ch01", "summary_bullets": [long_bullet]}],
        },
        {
            "canonical_name": "Chaol Westfall",
            "importance": "principal",
            "type": "PERSON",
            "context_by_chapter": {"ch01": ["guard"]},
            "related_context": [],
            "chapter_summary_context": [{"chapter_key": "ch01", "summary_bullets": [long_bullet]}],
        },
    ]

    class _Paths:
        wiki_inputs = tmp_path

    batches = write_batches(entities, narrator=None, paths=_Paths())

    assert len(batches) == 2


def test_stage_outputs_from_payload_reads_all_stage_outputs():
    payload = {
        "all_stage_outputs": {
            "entity-classification": {"entities": [{"canonical_name": "Dorian"}]},
            "chapter-summary": {"chapter_summaries": {"ch01": {"summary_bullets": ["x"]}}},
        }
    }
    classification, chapter_summary = stage_outputs_from_payload(payload)
    assert len(classification["entities"]) == 1
    assert "ch01" in chapter_summary["chapter_summaries"]
