"""Tests for scripts/entity_classification.py — importance classification."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.entity_classification import (
    _apply_entity_overrides,
    _canonicalize_role_entities,
    _normalize_entity_type,
    get_total_mentions,
    compute_auto_thresholds,
    assign_importance,
    classify_entities,
)


# --- Fixtures ---

PERSONS_FULL = {
    "persons_full": {
        "entity_001": {
            "type": "PERSON",
            "raw_mentions": ["David Martín", "Martín"],
            "first_seen": "ch01",
            "mentions_by_chapter": {
                "ch01": ["David Martín entra.", "Martín sourit."],
                "ch02": ["Martín écrivait."],
                "ch03": ["David Martín sortit.", "Il rêvait."],
            },
        },
        "entity_002": {
            "type": "PERSON",
            "raw_mentions": ["Pedro Vidal"],
            "first_seen": "ch02",
            "mentions_by_chapter": {
                "ch02": ["Pedro Vidal arriva."],
            },
        },
        "entity_003": {
            "type": "PERSON",
            "raw_mentions": ["le libraire"],
            "first_seen": "ch05",
            "mentions_by_chapter": {
                "ch05": ["le libraire ferma."],
            },
        },
    }
}

PLACES_FULL = {
    "places_full": {
        "place_001": {
            "type": "PLACE",
            "raw_mentions": ["Barcelone"],
            "first_seen": "ch01",
            "mentions_by_chapter": {
                "ch01": ["à Barcelone", "dans Barcelone"],
                "ch02": ["Barcelone s'endormait."],
            },
        }
    }
}

ORGS_FULL = {"orgs_full": {}}


# --- get_total_mentions ---

def test_get_total_mentions_sums_across_chapters():
    entity = {"type": "PERSON", "source_ids": ["entity_001"]}
    persons = PERSONS_FULL["persons_full"]
    total, chapters = get_total_mentions(entity, persons, {}, {})
    assert total == 5  # ch01: 2, ch02: 1, ch03: 2
    assert chapters == 3


def test_get_total_mentions_multiple_source_ids():
    # entity_001 has 5 mentions, entity_002 has 1 — combined entity has 6
    entity = {"type": "PERSON", "source_ids": ["entity_001", "entity_002"]}
    persons = PERSONS_FULL["persons_full"]
    total, chapters = get_total_mentions(entity, persons, {}, {})
    assert total == 6
    assert chapters == 3  # ch01, ch02, ch03 (entity_002's ch02 already counted)


def test_get_total_mentions_place():
    entity = {"type": "PLACE", "source_ids": ["place_001"]}
    places = PLACES_FULL["places_full"]
    total, chapters = get_total_mentions(entity, {}, places, {})
    assert total == 3
    assert chapters == 2


def test_get_total_mentions_unknown_source_id():
    entity = {"type": "PERSON", "source_ids": ["nonexistent"]}
    total, chapters = get_total_mentions(entity, {}, {}, {})
    assert total == 0
    assert chapters == 0


def test_get_total_mentions_unknown_type():
    entity = {"type": "EVENT", "source_ids": ["entity_001"]}
    total, chapters = get_total_mentions(entity, {}, {}, {})
    assert total == 0
    assert chapters == 0


# --- compute_auto_thresholds ---

def test_compute_auto_thresholds_returns_thresholds_per_type():
    mention_counts = [
        ("A", "PERSON", 100),
        ("B", "PERSON", 50),
        ("C", "PERSON", 20),
        ("D", "PERSON", 10),
        ("E", "PERSON", 5),
        ("F", "PERSON", 2),
        ("G", "PERSON", 1),
        ("H", "PERSON", 1),
        ("I", "PERSON", 0),
        ("J", "PERSON", 0),
    ]
    thresholds = compute_auto_thresholds(mention_counts)
    assert "PERSON" in thresholds
    t = thresholds["PERSON"]
    assert t["principal"] > t["secondary"] > t["figurant"] >= 0


def test_compute_auto_thresholds_single_entity():
    mention_counts = [("A", "PERSON", 10)]
    thresholds = compute_auto_thresholds(mention_counts)
    # Should not crash with a single entity
    assert "PERSON" in thresholds


def test_compute_auto_thresholds_separate_types():
    mention_counts = [
        ("Paris", "PLACE", 30),
        ("Lyon", "PLACE", 5),
        ("Acme", "ORG", 15),
    ]
    thresholds = compute_auto_thresholds(mention_counts)
    assert "PLACE" in thresholds
    assert "ORG" in thresholds
    assert "PERSON" not in thresholds


# --- assign_importance (auto thresholds) ---

def test_assign_importance_principal():
    thresholds = {"PERSON": {"principal": 90, "secondary": 40, "figurant": 10}}
    importance = assign_importance("PERSON", 100, 15, thresholds)
    assert importance == "principal"


def test_assign_importance_secondary():
    thresholds = {"PERSON": {"principal": 90, "secondary": 40, "figurant": 10}}
    importance = assign_importance("PERSON", 50, 5, thresholds)
    assert importance == "secondary"


def test_assign_importance_figurant():
    thresholds = {"PERSON": {"principal": 90, "secondary": 40, "figurant": 10}}
    importance = assign_importance("PERSON", 15, 2, thresholds)
    assert importance == "figurant"


def test_assign_importance_ignored():
    thresholds = {"PERSON": {"principal": 90, "secondary": 40, "figurant": 10}}
    importance = assign_importance("PERSON", 3, 1, thresholds)
    assert importance == "ignored"


def test_assign_importance_unknown_type_defaults_figurant():
    # EVENT type: no threshold defined → conservative default
    importance = assign_importance("EVENT", 5, 1, {})
    assert importance == "figurant"


# --- classify_entities (integration) ---

def test_classify_entities_enriches_with_importance():
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "source_ids": ["entity_001"], "relevant": True},
        {"canonical_name": "le libraire", "type": "PERSON", "source_ids": ["entity_003"], "relevant": True},
    ]
    enriched = classify_entities(
        entities,
        PERSONS_FULL["persons_full"],
        PLACES_FULL["places_full"],
        ORGS_FULL["orgs_full"],
        thresholds_config="auto",
    )
    assert len(enriched) == 2
    martín = next(e for e in enriched if e["canonical_name"] == "David Martín")
    libraire = next(e for e in enriched if e["canonical_name"] == "le libraire")
    assert "total_mentions" in martín
    assert "chapters_present" in martín
    assert "importance" in martín
    assert martín["total_mentions"] == 5
    # David Martín has more mentions → higher importance than le libraire
    importance_order = ["principal", "secondary", "figurant", "ignored"]
    assert importance_order.index(martín["importance"]) <= importance_order.index(libraire["importance"])


def test_classify_entities_skips_irrelevant():
    entities = [
        {"canonical_name": "Artefact", "type": "PERSON", "source_ids": [], "relevant": False},
    ]
    enriched = classify_entities(entities, {}, {}, {}, thresholds_config="auto")
    # Irrelevant entities are still in output but with importance = "ignored"
    assert enriched[0]["importance"] == "ignored"


def test_classify_entities_passthrough_extra_fields():
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "source_ids": ["entity_001"],
         "relevant": True, "aliases": ["Martín"]},
    ]
    enriched = classify_entities(
        entities, PERSONS_FULL["persons_full"], {}, {}, thresholds_config="auto"
    )
    assert enriched[0]["aliases"] == ["Martín"]


def test_normalize_entity_type_retags_geopolitical_name_to_place():
    entities = {
        "entity_x": {
            "mentions_by_chapter": {
                "ch01": ["She left the kingdom of Adarlan."],
                "ch02": ["Across the country, Adarlan prepared for war."],
            }
        }
    }
    entity = {"canonical_name": "Adarlan", "type": "PERSON", "source_ids": ["entity_x"], "aliases": []}
    new_type = _normalize_entity_type(entity, entities, {}, {}, {})
    assert new_type == "PLACE"


def test_canonicalize_role_entities_merges_unambiguous_assassin_alias():
    entities = [
        {"canonical_name": "Celaena", "type": "PERSON", "aliases": [], "source_ids": ["e1"], "relevant": True},
        {"canonical_name": "Assassin", "type": "PERSON", "aliases": [], "source_ids": ["e2"], "relevant": True},
    ]
    relationships = [
        {"entity_a": "Assassin", "entity_b": "Celaena", "cooccurrence_count": 12},
    ]
    persons_full = {
        "e2": {
            "mentions_by_chapter": {
                "ch01": ["I am Celaena Sardothien, Adarlan's Assassin."],
            }
        }
    }

    out_entities, out_relationships, merge_map = _canonicalize_role_entities(
        entities, relationships, persons_full, {}, {}, {}
    )
    assert merge_map == {"Assassin": "Celaena"}
    assert all(e["canonical_name"] != "Assassin" for e in out_entities)
    celaena = next(e for e in out_entities if e["canonical_name"] == "Celaena")
    assert "Assassin" in celaena["aliases"]
    assert out_relationships == []


def test_apply_entity_overrides_force_type_exclude_and_merge():
    entities = [
        {"canonical_name": "Arobynn", "type": "PLACE", "aliases": [], "source_ids": ["a"], "relevant": True},
        {"canonical_name": "Arobynn Hamel", "type": "PERSON", "aliases": [], "source_ids": ["b"], "relevant": True},
        {"canonical_name": "King's Champion", "type": "PERSON", "aliases": [], "source_ids": ["c"], "relevant": True},
    ]
    relationships = [
        {"entity_a": "Arobynn", "entity_b": "Celaena", "cooccurrence_count": 4},
        {"entity_a": "King's Champion", "entity_b": "Celaena", "cooccurrence_count": 8},
    ]
    overrides = {
        "Arobynn": {"merge_into": "Arobynn Hamel"},
        "King's Champion": {"exclude": True, "force_type": "OTHER"},
    }

    out_entities, out_relationships, merge_map = _apply_entity_overrides(
        entities, relationships, overrides
    )
    assert merge_map == {"Arobynn": "Arobynn Hamel"}
    assert all(e["canonical_name"] != "Arobynn" for e in out_entities)
    merged_target = next(e for e in out_entities if e["canonical_name"] == "Arobynn Hamel")
    assert "Arobynn" in merged_target["aliases"]
    role_entity = next(e for e in out_entities if e["canonical_name"] == "King's Champion")
    assert role_entity["relevant"] is False
    assert role_entity["type"] == "OTHER"
    assert all(rel["entity_a"] != "Arobynn" and rel["entity_b"] != "Arobynn" for rel in out_relationships)
