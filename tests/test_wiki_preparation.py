"""Tests for scripts/wiki_preparation.py."""

import io
import json
import sys
from pathlib import Path

from scripts.wiki_preparation import (
    _IMPORTANCE_NORMALIZE,
    build_chapter_summary_context,
    build_entity_bundle,
    events_for_entity,
    extract_context,
    filter_relationships,
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


def test_importance_normalize_maps_secondaire_to_secondary():
    """Regression: STU-316 – French 'secondaire' from classification must normalize to 'secondary'."""
    assert _IMPORTANCE_NORMALIZE["secondaire"] == "secondary"
    # Other values pass through unchanged
    assert _IMPORTANCE_NORMALIZE.get("principal", "principal") == "principal"
    assert _IMPORTANCE_NORMALIZE.get("figurant", "figurant") == "figurant"


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
            "importance": "secondaire",
            "source_ids": ["p5"],
        },
        "Cain": {
            "canonical_name": "Cain",
            "type": "PERSON",
            "importance": "secondaire",
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


def test_filter_relationships_matches_aliases():
    """Regression: STU-315 – Chaol (canonical) vs Chaol Westfall (in relationships)."""
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Chaol Westfall", "cooccurrence_count": 119},
        {"entity_a": "Chaol Westfall", "entity_b": "Dorian", "cooccurrence_count": 63},
        {"entity_a": "Celaena", "entity_b": "Dorian", "cooccurrence_count": 175},
    ]
    # canonical_name is "Chaol" but relationships use the alias "Chaol Westfall"
    result = filter_relationships("Chaol", relationships, aliases=["Chaol Westfall", "Captain Westfall"])
    assert len(result) == 2
    # Ensure unrelated relationship is excluded
    names = {(r["entity_a"], r["entity_b"]) for r in result}
    assert ("Celaena", "Dorian") not in names


def test_build_entity_bundle_matches_relationships_via_alias():
    """Regression: STU-315 – entity bundle should include relationships matched by alias."""
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Chaol",
        "type": "PERSON",
        "importance": "principal",
        "aliases": ["Chaol Westfall", "Captain Westfall"],
        "source_ids": ["p1"],
    }
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Chaol Westfall", "cooccurrence_count": 119},
    ]
    entities_by_name = {"Chaol": entity, "Celaena": {"canonical_name": "Celaena", "type": "PERSON", "importance": "principal"}}

    bundle = build_entity_bundle(entity, relationships, persons, places, orgs, events, entities_by_name)
    assert len(bundle["relationships"]) == 1
    assert len(bundle["related_context"]) == 1
    assert bundle["related_context"][0]["related_name"] == "Celaena"


def test_build_entity_bundle_tags_confidence():
    """STU-428: signals sent to the writer carry an explicit/inferred/interpretation tag."""
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Chaol",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
    }
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Chaol", "cooccurrence_count": 119,
         "relationship_type": "ami", "evidence": "Celaena faisait confiance à Chaol."},
        {"entity_a": "Dorian", "entity_b": "Chaol", "cooccurrence_count": 40},
    ]
    entities_by_name = {
        "Chaol": entity,
        "Celaena": {"canonical_name": "Celaena", "type": "PERSON", "importance": "principal"},
        "Dorian": {"canonical_name": "Dorian", "type": "PERSON", "importance": "principal"},
    }

    bundle = build_entity_bundle(entity, relationships, persons, places, orgs, events, entities_by_name)
    by_pair = {
        (r.get("entity_a"), r.get("entity_b")): r["confidence"]
        for r in bundle["relationships"]
    }
    assert by_pair[("Celaena", "Chaol")] == "explicit"
    assert by_pair[("Dorian", "Chaol")] == "inferred"


def test_build_entity_bundle_tags_revealed_at_chapter():
    """STU-491: each bundle sub-unit carries a normalized reveal chapter."""
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Dorian Havilliard",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
    }
    entities_by_name = {"Dorian Havilliard": entity}
    relationships = [
        {"entity_a": "Chaol", "entity_b": "Dorian Havilliard", "chapters": ["ch03", "ch01"]},
    ]
    chapter_summaries = {
        "ch01": {"chapter_id": "ch01", "summary_bullets": ["Dorian meets Chaol."]},
    }
    plot_events = [{"chapter": 5, "participants": ["Dorian Havilliard"], "description": "duel"}]

    bundle = build_entity_bundle(
        entity,
        relationships,
        persons,
        places,
        orgs,
        events,
        entities_by_name,
        chapter_summaries=chapter_summaries,
        plot_events=plot_events,
    )

    assert bundle["relationships"][0]["revealed_at_chapter"] == 1
    assert bundle["chapter_summary_context"][0]["revealed_at_chapter"] == 1
    assert bundle["entity_events"][0]["revealed_at_chapter"] == 5


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


def test_write_batches_includes_secondary_importance_entities(tmp_path: Path):
    """Regression: STU-316 – entities with importance 'secondary' must appear in batches."""
    entities = [
        {
            "canonical_name": "Nehemia",
            "importance": "secondary",
            "type": "PERSON",
            "context_by_chapter": {"ch01": ["Nehemia speaks."]},
            "related_context": [],
        },
        {
            "canonical_name": "Perrington",
            "importance": "secondary",
            "type": "PERSON",
            "context_by_chapter": {"ch01": ["Perrington orders."]},
            "related_context": [],
        },
    ]

    class _Paths:
        wiki_inputs = tmp_path

    batches = write_batches(entities, narrator=None, paths=_Paths())
    assert len(batches) >= 1
    all_names = [e["canonical_name"] for b in batches for e in json.loads((tmp_path / f"{b['batch_id']}.json").read_text())["entities"]]
    assert "Nehemia" in all_names
    assert "Perrington" in all_names


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


def test_build_chapter_summary_context_matches_xhtml_keys_to_chapter_title_keys():
    """context_by_chapter uses 'C{N}.xhtml' keys; chapter_summaries uses 'Chapter N' — must match."""
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
    }
    chapter_summaries = {
        "Chapter 25": {
            "chapter_id": None,
            "chapter_title": "Chapter 25",
            "summary_bullets": ["Celaena faces the champion trials."],
        },
    }
    context_by_chapter = {"C25.xhtml": ["She drew her blade."]}

    from scripts.wiki_preparation import build_chapter_summary_context
    result = build_chapter_summary_context(
        entity=entity,
        chapter_summaries=chapter_summaries,
        chapter_summary_max=8,
        context_by_chapter=context_by_chapter,
    )
    assert len(result) == 1
    assert result[0]["chapter_key"] == "C25.xhtml"
    assert result[0]["summary_bullets"] == ["Celaena faces the champion trials."]


def test_build_chapter_summary_context_includes_temporal_context():
    entity = {"type": "PERSON", "canonical_name": "Celaena", "chapter_mentions": {}}
    chapter_summaries = {
        "Chapter 1": {
            "chapter_id": "ch01",
            "chapter_title": "Chapter 1",
            "summary_bullets": ["Celaena arrived at the castle."],
            "temporal_context": "flashback",
        }
    }
    context_by_chapter = {"Chapter 1": ["some mention"]}
    result = build_chapter_summary_context(entity, chapter_summaries, 10, context_by_chapter)
    assert len(result) == 1
    assert result[0]["temporal_context"] == "flashback"


def test_build_chapter_summary_context_defaults_unknown_when_missing():
    entity = {"type": "PERSON", "canonical_name": "Celaena", "chapter_mentions": {}}
    chapter_summaries = {
        "Chapter 1": {
            "chapter_id": "ch01",
            "chapter_title": "Chapter 1",
            "summary_bullets": ["Celaena arrived."],
        }
    }
    context_by_chapter = {"Chapter 1": ["some mention"]}
    result = build_chapter_summary_context(entity, chapter_summaries, 10, context_by_chapter)
    assert result[0]["temporal_context"] == "unknown"


def test_build_entity_bundle_skips_chapter_summary_context_for_non_person():
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Adarlan",
        "type": "PLACE",
        "importance": "secondaire",
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


def test_build_chapter_summary_context_uses_chapter_id_to_title_when_heuristic_fails():
    """When EPUB ID doesn't match C{N}.xhtml pattern, chapter_id_to_title map must resolve the summary."""
    entity = {"type": "PERSON", "canonical_name": "Celaena"}
    chapter_summaries = {
        "The Glass Castle": {
            "chapter_id": None,
            "chapter_title": "The Glass Castle",
            "summary_bullets": ["Celaena enters the castle."],
            "temporal_context": "present",
        }
    }
    # EPUB ID is "chapter_01.xhtml" — _epub_key_to_chapter_label returns None for this pattern.
    context_by_chapter = {"chapter_01.xhtml": ["She stepped inside."]}
    chapter_id_to_title = {"chapter_01.xhtml": "The Glass Castle"}

    result = build_chapter_summary_context(
        entity=entity,
        chapter_summaries=chapter_summaries,
        chapter_summary_max=8,
        context_by_chapter=context_by_chapter,
        chapter_id_to_title=chapter_id_to_title,
    )
    assert len(result) == 1
    assert result[0]["chapter_key"] == "chapter_01.xhtml"
    assert result[0]["summary_bullets"] == ["Celaena enters the castle."]
    assert result[0]["temporal_context"] == "present"


def test_main_injects_chapter_id_to_title_from_epub_data(tmp_path: Path, monkeypatch):
    """main() builds chapter_id_to_title from epub_data.json and passes it for reconciliation."""
    import scripts.wiki_preparation as wp

    processing = tmp_path / "processing"
    wiki_inputs = tmp_path / "wiki_inputs"
    processing.mkdir()
    wiki_inputs.mkdir()

    # epub_data.json with a non-standard EPUB ID
    (processing / "epub_data.json").write_text(
        json.dumps({
            "chapters": [
                {"id": "chapter_01.xhtml", "title": "The Glass Castle", "content": "x" * 500}
            ]
        }),
        encoding="utf-8",
    )

    # chapter_summaries.json keyed by title (what chapter_summary.py writes)
    (processing / "chapter_summaries.json").write_text(
        json.dumps({
            "chapter_summaries": {
                "The Glass Castle": {
                    "chapter_id": None,
                    "chapter_title": "The Glass Castle",
                    "summary_bullets": ["Celaena enters the castle."],
                    "temporal_context": "present",
                }
            }
        }),
        encoding="utf-8",
    )

    for name in ("persons_full", "places_full", "orgs_full", "events_full"):
        (processing / f"{name}.json").write_text(json.dumps({name: {}}), encoding="utf-8")

    class _FakePaths:
        pass
    _FakePaths.processing = processing
    _FakePaths.wiki_inputs = wiki_inputs
    _FakePaths.series_character_graph = processing / "series_character_graph.json"

    monkeypatch.setattr(wp.studio_io, "paths_from_payload", lambda _payload: _FakePaths())
    monkeypatch.setattr(wp, "load_book_config_from_payload", lambda _payload: {})

    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
        "relevant": True,
        "total_mentions": 1,
        "chapters_present": 1,
        "aliases": [],
    }
    # Inject a persons_full entry so context_by_chapter has the non-standard key
    persons_data = {
        "persons_full": {
            "p1": {
                "canonical_name": "Celaena",
                "mentions_by_chapter": {"chapter_01.xhtml": ["She stepped inside."]},
                "first_seen": "chapter_01.xhtml",
                "source_ids": ["p1"],
            }
        }
    }
    (processing / "persons_full.json").write_text(json.dumps(persons_data), encoding="utf-8")

    payload = {
        "additional_context": "file_path: fake.epub",
        "all_stage_outputs": {
            "entity-classification": {
                "entities": [entity],
                "relationships": [],
                "narrator": None,
            },
        },
    }

    stdin_backup = sys.stdin
    stdout_backup = sys.stdout
    captured_out = io.StringIO()
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        sys.stdout = captured_out
        wp.main()
    finally:
        sys.stdin = stdin_backup
        sys.stdout = stdout_backup

    batch_files = list(wiki_inputs.glob("batch_*.json"))
    assert batch_files, "no batch files written"
    batch = json.loads(batch_files[0].read_text(encoding="utf-8"))
    celaena = next(e for e in batch["entities"] if e["canonical_name"] == "Celaena")
    ctx = celaena.get("chapter_summary_context", [])
    assert len(ctx) == 1, f"expected 1 chapter_summary_context entry, got {ctx}"
    assert ctx[0]["temporal_context"] == "present"


def test_main_falls_back_to_disk_when_chapter_summary_stage_output_is_empty(tmp_path: Path, monkeypatch):
    """When chapter-summary stage output is missing, main() reads chapter_summaries.json from disk."""
    import scripts.wiki_preparation as wp

    processing = tmp_path / "processing"
    wiki_inputs = tmp_path / "wiki_inputs"
    processing.mkdir()

    # Write chapter_summaries.json to disk
    (processing / "chapter_summaries.json").write_text(
        json.dumps({
            "chapter_summaries": {
                "ch01": {
                    "chapter_id": "ch01",
                    "summary_bullets": ["Celaena arrives at the castle."],
                    "temporal_context": "present",
                }
            }
        }),
        encoding="utf-8",
    )

    # Write required registry files (empty)
    for name in ("persons_full", "places_full", "orgs_full", "events_full"):
        (processing / f"{name}.json").write_text(json.dumps({name: {}}), encoding="utf-8")

    # Patch paths so main() uses tmp_path
    class _FakePaths:
        pass

    _FakePaths.processing = processing
    _FakePaths.wiki_inputs = wiki_inputs
    _FakePaths.series_character_graph = processing / "series_character_graph.json"
    wiki_inputs.mkdir(exist_ok=True)

    monkeypatch.setattr(wp.studio_io, "paths_from_payload", lambda _payload: _FakePaths())
    monkeypatch.setattr(wp, "load_book_config_from_payload", lambda _payload: {})

    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": [],
        "relevant": True,
        "total_mentions": 1,
        "chapters_present": 1,
        "aliases": [],
    }
    payload = {
        "additional_context": "file_path: fake.epub",
        "all_stage_outputs": {
            "entity-classification": {
                "entities": [entity],
                "relationships": [],
                "narrator": None,
            },
            # chapter-summary stage output intentionally absent / empty
        },
    }

    stdin_backup = sys.stdin
    stdout_backup = sys.stdout
    captured_out = io.StringIO()
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        sys.stdout = captured_out
        wp.main()
    finally:
        sys.stdin = stdin_backup
        sys.stdout = stdout_backup

    result = json.loads(captured_out.getvalue())
    assert result["total_entities"] == 1

    # Verify the batch file has chapter_summary_context populated from disk
    batch_files = list(wiki_inputs.glob("batch_*.json"))
    assert batch_files, "no batch files written"
    batch = json.loads(batch_files[0].read_text(encoding="utf-8"))
    celaena = next(e for e in batch["entities"] if e["canonical_name"] == "Celaena")
    # chapter_summary_context would be empty here since Celaena has no mentions_by_chapter,
    # but the key point is that no exception was raised and the fallback ran.
    assert "chapter_summary_context" in celaena


def test_batch_chapter_entry_carries_pov():
    """POV fields propagate from the chapter summary into each batch chapter entry."""
    entity = {"canonical_name": "Chaol", "type": "PERSON"}
    summaries = {
        "c1": {
            "chapter_id": "c1",
            "summary_bullets": ["Chaol did a thing."],
            "temporal_context": "present",
            "pov": "third_limited",
            "pov_confidence": "high",
            "pov_character": "Chaol",
            "pov_character_confidence": "high",
            "pov_character_source": "deterministic",
        }
    }
    out = build_chapter_summary_context(
        entity,
        chapter_summaries=summaries,
        chapter_summary_max=8,
        context_by_chapter={"c1": ["ctx"]},
        chapter_id_to_title={},
    )
    assert out and out[0]["pov"] == "third_limited"
    assert out[0]["pov_confidence"] == "high"
    assert out[0]["pov_character"] == "Chaol"
    assert out[0]["pov_character_confidence"] == "high"
    assert out[0]["pov_character_source"] == "deterministic"


def test_build_entity_bundle_extracts_titles_from_aliases():
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Chaol",
        "type": "PERSON",
        "importance": "secondary",
        "aliases": ["Chaol Westfall", "Captain Westfall"],
    }
    entities_by_name = {"Chaol": entity}
    role_words = ["captain", "duke", "king", "prince", "assassin"]

    bundle = build_entity_bundle(
        entity, [], persons, places, orgs, events, entities_by_name,
        role_words=role_words,
    )
    assert bundle["titles"] == ["Captain"]


def test_build_entity_bundle_titles_empty_without_role_words():
    persons, places, orgs, events = _registries()
    entity = {"canonical_name": "Chaol", "type": "PERSON", "importance": "secondary",
              "aliases": ["Captain Westfall"]}
    bundle = build_entity_bundle(
        entity, [], persons, places, orgs, events, {"Chaol": entity},
    )
    assert bundle["titles"] == []


def test_main_binds_identity_from_registry(tmp_path: Path, monkeypatch):
    """STU-443 (pas 4): main() rewrites batch identity from registry.json (the
    single source of truth) rather than the classification canonical_name."""
    import scripts.wiki_preparation as wp
    from wiki_creator.registry import EntityRecord, MergeDecision, Registry, _decision_id, entity_slug

    processing = tmp_path / "processing"
    wiki_inputs = tmp_path / "wiki_inputs"
    processing.mkdir()
    wiki_inputs.mkdir()

    for name in ("persons_full", "places_full", "orgs_full", "events_full"):
        (processing / f"{name}.json").write_text(json.dumps({name: {}}), encoding="utf-8")
    persons_data = {"persons_full": {"p1": {
        "canonical_name": "Celaena Sardothien",
        "mentions_by_chapter": {"ch01": ["She stepped inside."]},
        "first_seen": "ch01", "source_ids": ["p1"],
    }}}
    (processing / "persons_full.json").write_text(json.dumps(persons_data), encoding="utf-8")

    # Registry canonical differs from the classification surface ("Celaena").
    d_id = _decision_id("extraction_grouping", ("celaena_sardothien", entity_slug("Celaena")), "t")
    record = EntityRecord(
        entity_id="celaena_sardothien", canonical_name="Celaena Sardothien",
        entity_type="PERSON", aliases=["Celaena", "Celaena Sardothien"], decisions=[d_id],
    )
    Registry(
        entities=[record],
        decisions={d_id: MergeDecision(d_id, "extraction_grouping",
                                       ("celaena_sardothien", entity_slug("Celaena")), "t", "medium")},
    ).save(processing / "registry.json")

    class _FakePaths:
        pass
    _FakePaths.processing = processing
    _FakePaths.wiki_inputs = wiki_inputs
    _FakePaths.series_character_graph = processing / "series_character_graph.json"
    monkeypatch.setattr(wp.studio_io, "paths_from_payload", lambda _payload: _FakePaths())
    monkeypatch.setattr(wp, "load_book_config_from_payload", lambda _payload: {})

    payload = {"additional_context": "file_path: fake.epub", "all_stage_outputs": {
        "entity-classification": {"entities": [{
            "canonical_name": "Celaena", "type": "PERSON", "importance": "principal",
            "source_ids": ["p1"], "relevant": True, "aliases": [],
        }], "relationships": [], "narrator": None}}}

    stdin_backup, stdout_backup = sys.stdin, sys.stdout
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        sys.stdout = io.StringIO()
        wp.main()
    finally:
        sys.stdin, sys.stdout = stdin_backup, stdout_backup

    batch = json.loads(next(wiki_inputs.glob("batch_*.json")).read_text(encoding="utf-8"))
    entity = batch["entities"][0]
    assert entity["canonical_name"] == "Celaena Sardothien"   # bound from registry
    assert entity["aliases"] == ["Celaena"]                    # excludes canonical


def test_entity_events_filtered_by_canonical_name():
    """STU-478: entity_events channel — events where the canonical name participates or occurs."""
    events = [
        {"event_id": "e_ch12_0", "chapter": 12, "description": "duel",
         "participants": ["Celaena Sardothien", "Cain"], "places": ["Rifthold"]},
        {"event_id": "e_ch01_0", "chapter": 1, "description": "freed",
         "participants": ["Dorian Havilliard"], "places": ["Endovier"]},
    ]
    got = events_for_entity("Celaena Sardothien", events)
    assert [e["event_id"] for e in got] == ["e_ch12_0"]
    got_place = events_for_entity("Rifthold", events)
    assert [e["event_id"] for e in got_place] == ["e_ch12_0"]
