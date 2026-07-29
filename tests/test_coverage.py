"""Coverage / faithfulness harness (STU-723).

Unit invariants on synthetic artifacts — one per bug class the harness turns into
a red test — plus a fixture-level invariant on the committed golden novella: on a
book small enough that no cap fires, nothing is silently dropped, so every ledger
is clean.
"""
import json
from pathlib import Path

import pytest

from wiki_creator import coverage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_DIR = PROJECT_ROOT / "tests" / "fixtures" / "e2e" / "golden"
SEED_DIR = GOLDEN_DIR / "seed"


# ── Ledger 1 — chapter coverage (STU-711/713) ──────────────────────────────

def _entity(name, sids, chapters_present, importance="secondary", etype="PERSON"):
    return {
        "canonical_name": name,
        "type": etype,
        "source_ids": sids,
        "aliases": [name],
        "chapters_present": chapters_present,
        "importance": importance,
    }


def _registry(sid, chapters, etype="PERSON", surface="X"):
    return {
        sid: {
            "type": etype,
            "raw_mentions": [surface],
            "mention_count": sum(len(v) for v in chapters.values()),
            "mentions_by_chapter": chapters,
        }
    }


def test_chapter_coverage_flags_page_built_from_a_fraction():
    """An entity in 8 chapters whose page context covers 2 is a drop (STU-711)."""
    regs = _registry("p1", {f"c{i}": ["m"] for i in range(8)})
    entities = [_entity("Alice", ["p1"], 8)]
    ledger = coverage.chapter_coverage_ledger(
        entities, regs, page_chapters={"Alice": ["c0", "c1"]}
    )
    (row,) = ledger
    assert row["flagged"] is True
    assert row["source_chapter_count"] == 8
    assert row["page_chapter_count"] == 2
    assert row["dropped_chapters"] == ["c2", "c3", "c4", "c5", "c6", "c7"]


def test_chapter_coverage_clean_when_page_covers_all():
    regs = _registry("p1", {f"c{i}": ["m"] for i in range(8)})
    entities = [_entity("Alice", ["p1"], 8)]
    page = {"Alice": [f"c{i}" for i in range(8)]}
    ledger = coverage.chapter_coverage_ledger(entities, regs, page_chapters=page)
    assert ledger[0]["flagged"] is False
    assert ledger[0]["coverage_ratio"] == 1.0


def test_chapter_coverage_ignores_short_span_figurants():
    """A 2-chapter entity covered in one chapter is below min_source — not a defect."""
    regs = _registry("p1", {"c0": ["m"], "c1": ["m"]})
    entities = [_entity("Bit", ["p1"], 2, importance="figurant")]
    ledger = coverage.chapter_coverage_ledger(
        entities, regs, page_chapters={"Bit": ["c0"]}
    )
    assert ledger[0]["flagged"] is False


def test_chapter_coverage_skips_ignored_entities():
    regs = _registry("p1", {f"c{i}": ["m"] for i in range(8)})
    entities = [_entity("Ghost", ["p1"], 8, importance="ignored")]
    assert coverage.chapter_coverage_ledger(entities, regs) == []


# ── Ledger 2 — floating alias coverage (STU-714/716) ───────────────────────

def test_floating_high_frequency_surface_form_is_flagged():
    """An extracted surface form seen 22× that no paged entity claims (STU-714)."""
    regs = {
        "p1": {"type": "PERSON", "raw_mentions": ["Alice"], "mention_count": 30,
               "mentions_by_chapter": {"c0": ["Alice"]}},
        "r9": {"type": "PERSON", "raw_mentions": ["the Rabbit"], "mention_count": 22,
               "mentions_by_chapter": {"c0": ["the Rabbit ran"] * 22}},
    }
    entities = [_entity("Alice", ["p1"], 1)]
    ledger = coverage.mention_coverage_ledger(entities, regs)
    (row,) = ledger
    assert row["source_id"] == "r9"
    assert row["mention_count"] == 22
    assert row["reason"] == "floating_alias"


def test_floating_below_floor_is_not_flagged():
    regs = {
        "p1": {"type": "PERSON", "raw_mentions": ["Alice"], "mention_count": 30,
               "mentions_by_chapter": {"c0": ["Alice"]}},
        "r9": {"type": "PERSON", "raw_mentions": ["a page"], "mention_count": 2,
               "mentions_by_chapter": {"c0": ["a page"] * 2}},
    }
    entities = [_entity("Alice", ["p1"], 1)]
    assert coverage.mention_coverage_ledger(entities, regs) == []


def test_name_only_in_reported_speech_is_marked_quoted(  ):
    """A nickname that only appears inside quotes is the STU-716 phantom shape."""
    regs = {
        "r9": {"type": "PERSON", "raw_mentions": ["Bill"], "mention_count": 6,
               "mentions_by_chapter": {
                   "c0": ['"Where is Bill?" she asked'] * 3,
                   "c1": ['The Rabbit shouted, "Bill! Bill!"'] * 3,
               }},
    }
    ledger = coverage.mention_coverage_ledger([], regs)
    (row,) = ledger
    assert row["quoted_speech_only"] is True
    assert row["reason"] == "quoted_speech_only"


def test_name_in_narration_is_not_quoted_only():
    regs = {
        "r9": {"type": "PERSON", "raw_mentions": ["Bill"], "mention_count": 6,
               "mentions_by_chapter": {"c0": ["Bill climbed the ladder"] * 6}},
    }
    ledger = coverage.mention_coverage_ledger([], regs)
    assert ledger[0]["quoted_speech_only"] is False


# ── Ledger 3 — relationship support (STU-715/700) ──────────────────────────

def test_relationship_below_cooccurrence_gate_is_flagged():
    """A one-off co-occurrence typed ally/enemy is a hard infobox slot (STU-715)."""
    rels = [{
        "entity_a": "Alice", "entity_b": "Bill", "relationship_type": "enemy",
        "cooccurrence_count": 1, "sample_contexts": ["they met once"],
    }]
    (row,) = coverage.relationship_support_ledger(rels)
    assert row["flagged"] is True
    assert "below_cooccurrence_gate" in row["reasons"]


def test_relationship_empty_evidence_is_flagged():
    """A relation reaching a slot with no evidence behind it (STU-700)."""
    rels = [{
        "entity_a": "Alice", "entity_b": "Cat", "relationship_type": "friend",
        "cooccurrence_count": 9, "sample_contexts": [], "key_moments": [],
        "evolution": None,
    }]
    (row,) = coverage.relationship_support_ledger(rels)
    assert row["flagged"] is True
    assert row["reasons"] == ["empty_evidence"]


def test_supported_relationship_is_clean():
    rels = [{
        "entity_a": "Alice", "entity_b": "Cat", "relationship_type": "friend",
        "cooccurrence_count": 9, "sample_contexts": ["they spoke often"],
    }]
    (row,) = coverage.relationship_support_ledger(rels)
    assert row["flagged"] is False


def test_weak_or_specific_type_reaches_no_slot():
    """acquaintance/other never render as an infobox slot — not the harness's concern."""
    rels = [{
        "entity_a": "Alice", "entity_b": "Dodo", "relationship_type": "acquaintance",
        "cooccurrence_count": 1, "sample_contexts": [],
    }]
    assert coverage.relationship_support_ledger(rels) == []


# ── Drop log aggregation ───────────────────────────────────────────────────

def test_aggregate_drops_folds_every_flagged_row():
    chapter = [{"entity": "Alice", "flagged": True, "source_chapter_count": 8,
                "page_chapter_count": 2, "dropped_chapters": ["c2", "c3"]}]
    mention = [{"source_id": "r9", "surface_forms": ["the Rabbit"],
                "mention_count": 22, "chapters": ["c0"], "reason": "floating_alias"}]
    relationship = [{"entity_a": "A", "entity_b": "B", "cooccurrence_count": 1,
                     "reasons": ["below_cooccurrence_gate"], "flagged": True}]
    drops = coverage.aggregate_drops(chapter, mention, relationship)
    stages = {d["stage"] for d in drops}
    assert stages == {
        "wiki-preparation.extract_context",
        "entity-extraction/classification",
        "relationship-discovery/infobox",
    }


# ── Runtime drop logger ────────────────────────────────────────────────────

def test_log_drop_is_noop_on_empty(capsys):
    coverage.log_drop("stage", "Alice", 0, "nothing")
    assert capsys.readouterr().err == ""


def test_log_drop_emits_structured_line(capsys):
    coverage.log_drop("wiki-preparation.extract_context", "Alice", 3, "budget")
    err = capsys.readouterr().err
    assert "[DROP]" in err and "Alice" in err and "count=3" in err


# ── Fixture-level invariant: nothing drops on the golden novella ───────────

def _load_full(path: Path, key: str) -> dict:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return raw.get(key, raw)


def _golden_registries_and_entities():
    from wiki_creator import studio_io
    from wiki_creator.entity_taxonomy import full_registry_files

    by_type = {}
    for _etype, filename, json_key in full_registry_files():
        p = SEED_DIR / filename
        if p.exists():
            by_type[json_key] = _load_full(p, json_key)
    registries = coverage.merge_registries(by_type)

    with open(GOLDEN_DIR / "stages" / "entity-classification.json", encoding="utf-8") as f:
        classified = json.load(f)
    return registries, classified


def test_fixture_novella_has_no_silent_chapter_drop():
    """The golden novella is 4 chapters — far under every cap — so every paged
    entity's page context covers all its source chapters (ratio 1.0)."""
    from wiki_creator import studio_io
    from scripts.wiki_preparation import extract_context

    registries, classified = _golden_registries_and_entities()
    persons = studio_io.load_full_file(SEED_DIR / "persons_full.json", "persons_full")
    places = studio_io.load_full_file(SEED_DIR / "places_full.json", "places_full")
    orgs = studio_io.load_full_file(SEED_DIR / "orgs_full.json", "orgs_full")
    events = studio_io.load_full_file(SEED_DIR / "events_full.json", "events_full")

    page_chapters = {}
    for entity in classified["entities"]:
        ctx = extract_context(entity, persons, places, orgs, events)
        page_chapters[entity["canonical_name"]] = sorted(ctx.keys())

    ledger = coverage.chapter_coverage_ledger(
        classified["entities"], registries, page_chapters=page_chapters
    )
    flagged = [r for r in ledger if r["flagged"]]
    assert flagged == [], flagged


def test_fixture_novella_has_no_floating_alias():
    """Every high-frequency surface form in the fixture is folded into a paged entity."""
    registries, classified = _golden_registries_and_entities()
    ledger = coverage.mention_coverage_ledger(classified["entities"], registries)
    assert ledger == [], ledger
