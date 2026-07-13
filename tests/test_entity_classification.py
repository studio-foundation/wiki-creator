"""Tests for scripts/entity_classification.py — importance classification."""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pytest
from scripts.entity_classification import (
    _apply_entity_overrides,
    _apply_llm_type_corrections,
    _build_alias_merge_map,
    _canonicalize_role_entities,
    _filter_intra_entity_relationships,
    _is_role_entity_name,
    _load_type_corrections,
    _normalize_entity_type,
    get_total_mentions,
    build_surface_index,
    compute_auto_thresholds,
    assign_importance,
    classify_entities,
)
from wiki_creator.lang import load_lang_config

_EN = load_lang_config("en")
_GEO_SUFFIXES = frozenset(_EN.get("geo_suffixes", []))
_ROLE_WORDS = frozenset(_EN.get("role_words", []))
_ROLE_PATTERNS = tuple(_EN.get("role_patterns", []))


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


# --- STU-474: surface-form aggregation across un-merged clusters ---

# A central character whose surfaces landed in three separate extraction
# clusters; only the junk 1-mention cluster made it into source_ids.
NEHEMIA_PERSONS = {
    "entity_048": {  # junk cluster that source_ids points at
        "type": "PERSON",
        "raw_mentions": ["Ianticipate"],
        "mentions_by_chapter": {"C10": ["Ianticipate nothing."]},
    },
    "entity_216": {  # real Nehemia surface, never merged in
        "type": "PERSON",
        "raw_mentions": ["Nehemia"],
        "mentions_by_chapter": {
            "C05": ["Nehemia laughed.", "Nehemia crossed the hall."],
            "C06": ["Nehemia read the scroll."],
        },
    },
    "entity_219": {  # possessive surface of the same person
        "type": "PERSON",
        "raw_mentions": ["Nehemia'"],
        "mentions_by_chapter": {"C07": ["Nehemia's guards waited."]},
    },
}


def test_get_total_mentions_source_ids_only_undercounts():
    """Baseline: without the surface index a mis-clustered entity reads ~1."""
    entity = {"type": "PERSON", "canonical_name": "Nehemia", "source_ids": ["entity_048"]}
    total, chapters = get_total_mentions(entity, NEHEMIA_PERSONS, {}, {})
    assert total == 1
    assert chapters == 1


def test_get_total_mentions_surface_index_recovers_unmerged_mentions():
    """STU-474: surface aggregation folds every surface form of the canonical
    name (incl. possessive) plus the source_id cluster, without double-counting."""
    entity = {"type": "PERSON", "canonical_name": "Nehemia", "source_ids": ["entity_048"]}
    index = build_surface_index(NEHEMIA_PERSONS)
    total, chapters = get_total_mentions(
        entity, NEHEMIA_PERSONS, {}, {}, surface_index=index
    )
    assert total == 5  # entity_048: 1, entity_216: 3, entity_219: 1
    assert chapters == 4  # C10, C05, C06, C07


def test_get_total_mentions_surface_index_matches_aliases():
    entity = {"type": "PERSON", "canonical_name": "Celaena", "aliases": ["Nehemia"]}
    index = build_surface_index(NEHEMIA_PERSONS)
    total, _ = get_total_mentions(entity, NEHEMIA_PERSONS, {}, {}, surface_index=index)
    assert total == 4  # entity_216 (3) + entity_219 (1) via the alias surface


def test_get_total_mentions_surface_index_no_double_count():
    """A cluster reachable via both source_ids and surface is counted once."""
    entity = {"type": "PERSON", "canonical_name": "Nehemia", "source_ids": ["entity_216"]}
    index = build_surface_index(NEHEMIA_PERSONS)
    total, _ = get_total_mentions(entity, NEHEMIA_PERSONS, {}, {}, surface_index=index)
    assert total == 4  # entity_216 counted once, + entity_219


def test_classify_entities_promotes_undercounted_central_character():
    """STU-474 non-regression: Nehemia must not rank figurant when her surfaces
    are spread across un-merged clusters."""
    entities = [
        {"canonical_name": "Nehemia", "type": "PERSON", "source_ids": ["entity_048"],
         "aliases": [], "relevant": True},
        # Filler so percentile thresholds have >= MIN_ENTITIES_FOR_AUTO entities.
        {"canonical_name": "Extra1", "type": "PERSON", "source_ids": ["e1"], "relevant": True},
        {"canonical_name": "Extra2", "type": "PERSON", "source_ids": ["e2"], "relevant": True},
        {"canonical_name": "Extra3", "type": "PERSON", "source_ids": ["e3"], "relevant": True},
    ]
    persons = dict(NEHEMIA_PERSONS)
    persons.update({
        "e1": {"type": "PERSON", "raw_mentions": ["Extra1"], "mentions_by_chapter": {"C01": ["a"]}},
        "e2": {"type": "PERSON", "raw_mentions": ["Extra2"], "mentions_by_chapter": {"C01": ["b"]}},
        "e3": {"type": "PERSON", "raw_mentions": ["Extra3"], "mentions_by_chapter": {"C01": ["c"]}},
    })
    result = classify_entities(entities, persons, {}, {}, "auto")
    nehemia = next(e for e in result if e["canonical_name"] == "Nehemia")
    assert nehemia["total_mentions"] == 5
    assert nehemia["importance"] != "figurant"


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


def test_compute_auto_thresholds_few_entities_uses_absolute_floor():
    # n=2 PLACEs: percentiles collapse → Calaculla (3 mentions) must NOT be "principal"
    mention_counts = [
        ("White Fang Mountains", "PLACE", 4),
        ("Calaculla", "PLACE", 3),
    ]
    thresholds = compute_auto_thresholds(mention_counts)
    t = thresholds["PLACE"]
    # With only 2 entities, principal threshold must require substantially more than 3 mentions
    assert t["principal"] > 3, (
        f"principal threshold {t['principal']} too low: Calaculla (3 mentions) "
        "would be assigned 'principal'"
    )


def test_compute_auto_thresholds_single_entity_not_principal_with_few_mentions():
    # A single entity with few mentions should not become "principal"
    mention_counts = [("Calaculla", "PLACE", 3)]
    thresholds = compute_auto_thresholds(mention_counts)
    importance = assign_importance("PLACE", 3, 1, thresholds)
    assert importance != "principal", (
        f"3-mention entity should not be 'principal', got {importance!r}"
    )


def test_compute_auto_thresholds_three_entities_conservative():
    # n=3: still below MIN_ENTITIES_FOR_AUTO — principal must not be trivially reachable
    mention_counts = [
        ("A", "PLACE", 5),
        ("B", "PLACE", 4),
        ("C", "PLACE", 3),
    ]
    thresholds = compute_auto_thresholds(mention_counts)
    t = thresholds["PLACE"]
    assert t["principal"] > 5, (
        f"principal threshold {t['principal']} is ≤ 5: an entity with only 5 mentions "
        "should not reach 'principal' when n < MIN_ENTITIES_FOR_AUTO"
    )


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
    assert importance == "secondaire"


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
    importance_order = ["principal", "secondaire", "figurant", "ignored"]
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


def test_normalize_entity_type_keeps_person_when_context_has_generic_geo_words():
    entities = {
        "entity_n": {
            "mentions_by_chapter": {
                "ch01": ["Nehemia spoke about the kingdom and the war."],
                "ch02": ["In the country, Nehemia sought allies."],
            }
        }
    }
    entity = {"canonical_name": "Nehemia", "type": "PERSON", "source_ids": ["entity_n"], "aliases": []}
    new_type = _normalize_entity_type(entity, entities, {}, {}, {})
    assert new_type == "PERSON"


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
        entities, relationships, persons_full, {}, {}, {},
        role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS,
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


def test_classify_entities_accepts_geo_keywords_param():
    """classify_entities should accept optional geo_keywords without error."""
    from scripts.entity_classification import classify_entities
    entities = [{"canonical_name": "Arendelle", "type": "PLACE", "relevant": True, "aliases": [], "source_ids": []}]
    result = classify_entities(entities, {}, {}, {}, "auto", geo_keywords=frozenset({"glacier"}))
    assert isinstance(result, list)


def test_classify_entities_accepts_concept_keywords_param():
    """classify_entities should return OTHER for entities matching concept_keywords."""
    from scripts.entity_classification import classify_entities
    entities = [{"canonical_name": "wyrdmark", "type": "OTHER", "relevant": True, "aliases": [], "source_ids": []}]
    result = classify_entities(entities, {}, {}, {}, "auto", concept_keywords=frozenset({"wyrdmark"}))
    assert result[0]["type"] == "OTHER"


# --- STU-267: compound role nouns and role+surname ---

def test_is_role_entity_name_recognizes_compound_role_noun():
    """'Royal Guard' and 'Head Guard' should be recognized via token membership."""
    assert _is_role_entity_name("Royal Guard", role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS) is True
    assert _is_role_entity_name("Head Guard", role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS) is True
    assert _is_role_entity_name("royal assassin", role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS) is True


def test_is_role_entity_name_does_not_flag_proper_compound_without_role_token():
    """Compound names with no role word token should not be recognized as role entities."""
    assert _is_role_entity_name("Roland Havilliard", role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS) is False
    assert _is_role_entity_name("Nehemia Ytger", role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS) is False


def test_canonicalize_role_entities_merges_role_surname_into_full_name():
    """'Captain Westfall' should merge into 'Chaol Westfall' via surname match + relational support."""
    entities = [
        {"canonical_name": "Chaol Westfall", "type": "PERSON", "aliases": [], "source_ids": ["e1"], "relevant": True},
        {"canonical_name": "Captain Westfall", "type": "PERSON", "aliases": [], "source_ids": ["e2"], "relevant": True},
    ]
    relationships = [
        {"entity_a": "Captain Westfall", "entity_b": "Chaol Westfall", "cooccurrence_count": 10},
    ]
    persons_full = {
        "e2": {
            "mentions_by_chapter": {
                "ch01": ["Captain Westfall arrived. Chaol Westfall was loyal."],
            }
        }
    }

    out_entities, out_relationships, merge_map = _canonicalize_role_entities(
        entities, relationships, persons_full, {}, {}, {},
        role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS,
    )
    assert merge_map == {"Captain Westfall": "Chaol Westfall"}
    assert all(e["canonical_name"] != "Captain Westfall" for e in out_entities)
    chaol = next(e for e in out_entities if e["canonical_name"] == "Chaol Westfall")
    assert "Captain Westfall" in chaol["aliases"]


# --- STU-431: title-only characters must survive role canonicalization ---

def test_canonicalize_role_entities_keeps_title_only_character_with_broad_cooccurrence():
    """A role-named entity that fails the merge but co-occurs with ≥3 distinct
    PERSONs is a real character known only by title (e.g. King of Adarlan) —
    it must stay PERSON/relevant, not be flipped to OTHER/ignored."""
    entities = [
        {"canonical_name": "Celaena", "type": "PERSON", "aliases": [], "source_ids": ["e1"], "relevant": True},
        {"canonical_name": "Nehemia", "type": "PERSON", "aliases": [], "source_ids": ["e2"], "relevant": True},
        {"canonical_name": "Cain", "type": "PERSON", "aliases": [], "source_ids": ["e3"], "relevant": True},
        {"canonical_name": "King of Adarlan", "type": "PERSON", "aliases": [], "source_ids": ["e4"], "relevant": True},
    ]
    # Top candidate (46) does not double the second (29) → merge correctly fails.
    relationships = [
        {"entity_a": "Celaena", "entity_b": "King of Adarlan", "cooccurrence_count": 46},
        {"entity_a": "King of Adarlan", "entity_b": "Nehemia", "cooccurrence_count": 29},
        {"entity_a": "Cain", "entity_b": "King of Adarlan", "cooccurrence_count": 27},
    ]

    out_entities, _, merge_map = _canonicalize_role_entities(
        entities, relationships, {}, {}, {}, {},
        role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS,
    )
    assert "King of Adarlan" not in merge_map
    king = next(e for e in out_entities if e["canonical_name"] == "King of Adarlan")
    assert king["relevant"] is True
    assert king["type"] == "PERSON"


def test_canonicalize_role_entities_ignores_unmerged_role_with_narrow_cooccurrence():
    """A role-named entity that fails the merge and co-occurs with <3 distinct
    PERSONs stays ignored (OTHER/relevant=False) — likely a noise fragment."""
    entities = [
        {"canonical_name": "Celaena", "type": "PERSON", "aliases": [], "source_ids": ["e1"], "relevant": True},
        {"canonical_name": "Nehemia", "type": "PERSON", "aliases": [], "source_ids": ["e2"], "relevant": True},
        {"canonical_name": "Head Guard", "type": "PERSON", "aliases": [], "source_ids": ["e3"], "relevant": True},
    ]
    # Merge fails (4 < 2×3) and only 2 distinct persons → still ignored.
    relationships = [
        {"entity_a": "Head Guard", "entity_b": "Celaena", "cooccurrence_count": 4},
        {"entity_a": "Head Guard", "entity_b": "Nehemia", "cooccurrence_count": 3},
    ]

    out_entities, _, merge_map = _canonicalize_role_entities(
        entities, relationships, {}, {}, {}, {},
        role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS,
    )
    assert "Head Guard" not in merge_map
    guard = next(e for e in out_entities if e["canonical_name"] == "Head Guard")
    assert guard["relevant"] is False
    assert guard["type"] == "OTHER"


def test_canonicalize_role_entities_marks_compound_role_noun_as_other():
    """'Royal Guard' with no matching PERSON should be marked OTHER/irrelevant."""
    entities = [
        {"canonical_name": "Celaena", "type": "PERSON", "aliases": [], "source_ids": ["e1"], "relevant": True},
        {"canonical_name": "Royal Guard", "type": "PERSON", "aliases": [], "source_ids": ["e2"], "relevant": True},
    ]
    relationships = []  # no relational support

    out_entities, _, merge_map = _canonicalize_role_entities(
        entities, relationships, {}, {}, {}, {},
        role_words=_ROLE_WORDS, role_patterns=_ROLE_PATTERNS,
    )
    assert "Royal Guard" not in merge_map
    royal_guard = next(e for e in out_entities if e["canonical_name"] == "Royal Guard")
    assert royal_guard["relevant"] is False
    assert royal_guard["type"] == "OTHER"


def test_normalize_geo_suffix_retags_person_to_place():
    """Name token 'mountains' is a geo-suffix → PERSON retags to PLACE."""
    entity = {
        "canonical_name": "White Fang Mountains",
        "type": "PERSON",
        "source_ids": [],
        "aliases": [],
    }
    new_type = _normalize_entity_type(entity, {}, {}, {}, {}, geo_suffixes=_GEO_SUFFIXES)
    assert new_type == "PLACE"


def test_normalize_geo_suffix_single_word_place():
    """Name containing geo-suffix token 'sea' → PERSON retags to PLACE."""
    entity = {
        "canonical_name": "Frostmere Sea",
        "type": "PERSON",
        "source_ids": [],
        "aliases": [],
    }
    new_type = _normalize_entity_type(entity, {}, {}, {}, {}, geo_suffixes=_GEO_SUFFIXES)
    assert new_type == "PLACE"


def test_normalize_no_false_positive_on_plain_person_name():
    """Name with no geo-suffix tokens stays PERSON."""
    entity = {
        "canonical_name": "Blade",
        "type": "PERSON",
        "source_ids": [],
        "aliases": [],
    }
    new_type = _normalize_entity_type(entity, {}, {}, {}, {})
    assert new_type == "PERSON"


def test_normalize_entity_type_retags_place_to_person_when_source_ids_in_persons_full():
    """PLACE entity whose source_ids include a persons_full entry (≥3 mentions) → PERSON.

    Covers the Arobynn Hamel case: merge creates type=PLACE because a bare first-name
    was extracted as PLACE, but the canonical entity has a persons_full source_id with
    many mentions.
    """
    persons_full = {
        "entity_017": {
            "mentions_by_chapter": {
                "ch01": ["Arobynn Hamel trained her.", "Arobynn watched from the shadows."],
                "ch02": ["She had not seen Arobynn since the river."],
            }
        }
    }
    places_full = {
        "entity_018": {
            "mentions_by_chapter": {
                "ch05": ["found her half-submerged on the banks of a frozen river near Arobynn"],
            }
        }
    }
    entity = {
        "canonical_name": "Arobynn Hamel",
        "type": "PLACE",
        "source_ids": ["entity_017", "entity_018"],
        "aliases": [],
    }
    new_type = _normalize_entity_type(entity, persons_full, places_full, {}, {})
    assert new_type == "PERSON"


def test_normalize_entity_type_no_false_retag_when_persons_full_mentions_are_sparse():
    """PLACE entity with only 1 persons_full mention stays PLACE (noise, not a real person)."""
    persons_full = {
        "entity_noise": {
            "mentions_by_chapter": {
                "ch01": ["A figure called Arobynn passed by."],
            }
        }
    }
    entity = {
        "canonical_name": "Arobynn",
        "type": "PLACE",
        "source_ids": ["entity_noise"],
        "aliases": [],
    }
    new_type = _normalize_entity_type(entity, persons_full, {}, {}, {})
    assert new_type == "PLACE"


def test_normalize_entity_type_accepts_geo_suffixes_kwarg():
    entity = {"canonical_name": "Iron Mountains", "type": "PERSON", "source_ids": []}
    result = _normalize_entity_type(
        entity, {}, {}, {}, {},
        geo_suffixes=frozenset({"mountains"}),
    )
    assert result == "PLACE"


def test_normalize_entity_type_geo_suffixes_empty_does_not_retag():
    entity = {"canonical_name": "Iron Mountains", "type": "PERSON", "source_ids": []}
    result = _normalize_entity_type(
        entity, {}, {}, {}, {},
        geo_suffixes=frozenset(),
    )
    # Without geo_suffixes hint, the PERSON entity should NOT be retagged
    assert result == "PERSON"


def test_is_role_entity_name_empty_role_words_returns_false():
    assert _is_role_entity_name("captain", role_words=frozenset(), role_patterns=()) is False


def test_classify_entities_empty_concept_keywords_does_not_crash():
    entities = [{"canonical_name": "Magic", "type": "OTHER", "source_ids": [], "relevant": True}]
    result = classify_entities(entities, {}, {}, {}, "auto", concept_keywords=frozenset())
    assert result[0]["importance"] in ("principal", "secondaire", "figurant", "ignored")


# ---------------------------------------------------------------------------
# STU-282 — _filter_intra_entity_relationships
# ---------------------------------------------------------------------------



def test_filter_intra_entity_drops_canonical_alias_pair():
    """canonical ↔ alias of the same entity must be dropped."""
    entities = [
        {"canonical_name": "Chaol Westfall", "aliases": ["Captain Westfall", "Chaol"], "type": "PERSON"},
        {"canonical_name": "Celaena Sardothien", "aliases": ["Laena"], "type": "PERSON"},
    ]
    relationships = [
        {"entity_a": "Chaol Westfall", "entity_b": "Captain Westfall", "cooccurrence_count": 12},
    ]
    assert _filter_intra_entity_relationships(entities, relationships) == []


def test_filter_intra_entity_drops_alias_alias_pair():
    """Two aliases of the same entity must be dropped."""
    entities = [
        {"canonical_name": "Dorian Havilliard", "aliases": ["Crown Prince", "Dorian"], "type": "PERSON"},
    ]
    relationships = [
        {"entity_a": "Crown Prince", "entity_b": "Dorian", "cooccurrence_count": 8},
    ]
    assert _filter_intra_entity_relationships(entities, relationships) == []


def test_filter_intra_entity_keeps_cross_entity_pair():
    """Relationship between two different entities must be kept."""
    entities = [
        {"canonical_name": "Chaol Westfall", "aliases": ["Captain Westfall"], "type": "PERSON"},
        {"canonical_name": "Celaena Sardothien", "aliases": ["Laena"], "type": "PERSON"},
    ]
    rel = {"entity_a": "Chaol Westfall", "entity_b": "Celaena Sardothien", "cooccurrence_count": 30}
    result = _filter_intra_entity_relationships(entities, [rel])
    assert result == [rel]


def test_filter_intra_entity_keeps_unknown_name():
    """If one name is not in the entity list, the relationship passes through."""
    entities = [
        {"canonical_name": "Chaol Westfall", "aliases": ["Captain Westfall"], "type": "PERSON"},
    ]
    rel = {"entity_a": "Chaol Westfall", "entity_b": "UnknownEntity", "cooccurrence_count": 5}
    result = _filter_intra_entity_relationships(entities, [rel])
    assert result == [rel]


# STU-285 — _build_alias_merge_map

def test_build_alias_merge_map_maps_canonical_to_itself():
    entities = [{"canonical_name": "Chaol Westfall", "aliases": []}]
    result = _build_alias_merge_map(entities)
    assert result["Chaol Westfall"] == "Chaol Westfall"


def test_build_alias_merge_map_maps_aliases_to_canonical():
    entities = [{"canonical_name": "Chaol Westfall", "aliases": ["Chaol", "Captain Westfall"]}]
    result = _build_alias_merge_map(entities)
    assert result["Chaol"] == "Chaol Westfall"
    assert result["Captain Westfall"] == "Chaol Westfall"


def test_build_alias_merge_map_multiple_entities():
    entities = [
        {"canonical_name": "Celaena Sardothien", "aliases": ["Laena"]},
        {"canonical_name": "Chaol Westfall", "aliases": ["Chaol"]},
    ]
    result = _build_alias_merge_map(entities)
    assert result["Laena"] == "Celaena Sardothien"
    assert result["Chaol"] == "Chaol Westfall"
    assert len(result) == 4  # 2 canonicals + 2 aliases


def test_build_alias_merge_map_skips_empty_canonical():
    entities = [{"canonical_name": "", "aliases": ["Ghost"]}]
    result = _build_alias_merge_map(entities)
    assert result == {}


def test_build_alias_merge_map_skips_empty_aliases():
    entities = [{"canonical_name": "Dorian", "aliases": ["", None]}]
    result = _build_alias_merge_map(entities)
    assert "Dorian" in result
    assert "" not in result
    assert None not in result


# STU-285 — alias canonicalization + dedup integration

def test_alias_canonicalization_deduplicates_relationships():
    """Three alias spellings of the same character-pair collapse to one entry."""
    from scripts.entity_classification import _rewrite_relationships

    entities = [
        {"canonical_name": "Chaol Westfall", "aliases": ["Chaol", "Captain Westfall"]},
        {"canonical_name": "Celaena Sardothien", "aliases": ["Laena", "Celaena"]},
    ]
    relationships = [
        {"entity_a": "Captain Westfall", "entity_b": "Celaena", "cooccurrence_count": 3},
        {"entity_a": "Chaol", "entity_b": "Laena", "cooccurrence_count": 7},
        {"entity_a": "Chaol Westfall", "entity_b": "Celaena Sardothien", "cooccurrence_count": 10},
    ]
    alias_map = _build_alias_merge_map(entities)
    result = _rewrite_relationships(relationships, alias_map)

    assert len(result) == 1
    assert result[0]["entity_a"] == "Celaena Sardothien"
    assert result[0]["entity_b"] == "Chaol Westfall"
    assert result[0]["cooccurrence_count"] == 20  # 3 + 7 + 10


def test_alias_canonicalization_drops_self_relations():
    """A relationship where both sides are aliases of the same entity is dropped."""
    from scripts.entity_classification import _rewrite_relationships

    entities = [
        {"canonical_name": "Dorian Havilliard", "aliases": ["Crown Prince", "Prince Dorian"]},
    ]
    relationships = [
        {"entity_a": "Crown Prince", "entity_b": "Dorian Havilliard", "cooccurrence_count": 5},
    ]
    alias_map = _build_alias_merge_map(entities)
    result = _rewrite_relationships(relationships, alias_map)
    assert result == []


# --- _load_type_corrections ---

def test_load_type_corrections_returns_empty_when_no_file(tmp_path):
    result = _load_type_corrections(tmp_path)
    assert result == {}


def test_load_type_corrections_reads_file(tmp_path):
    data = [
        {"cluster_id": "c1", "name": "Arobynn", "from": "PLACE", "to": "PERSON"},
        {"cluster_id": "c2", "name": "Sam Hamel", "from": "ORG", "to": "PERSON"},
    ]
    (tmp_path / "entity_type_corrections.json").write_text(json.dumps(data))
    result = _load_type_corrections(tmp_path)
    assert result == {"arobynn": "PERSON", "sam hamel": "PERSON"}


# --- _apply_llm_type_corrections ---

def test_apply_llm_corrections_by_canonical_name():
    entities = [{"canonical_name": "Arobynn", "type": "PLACE", "aliases": []}]
    corrections_map = {"arobynn": "PERSON"}
    _apply_llm_type_corrections(entities, corrections_map)
    assert entities[0]["type"] == "PERSON"


def test_apply_llm_corrections_by_alias():
    # canonical_name does NOT match, but alias does
    entities = [{"canonical_name": "Arobynn Hamel", "type": "PLACE", "aliases": ["Arobynn"]}]
    corrections_map = {"arobynn": "PERSON"}
    _apply_llm_type_corrections(entities, corrections_map)
    assert entities[0]["type"] == "PERSON"


def test_apply_llm_corrections_no_match():
    entities = [{"canonical_name": "Dorian", "type": "PERSON", "aliases": []}]
    corrections_map = {"arobynn": "PERSON"}
    _apply_llm_type_corrections(entities, corrections_map)
    assert entities[0]["type"] == "PERSON"  # unchanged


def test_apply_llm_corrections_no_op_when_type_already_matches():
    entities = [{"canonical_name": "Arobynn", "type": "PERSON", "aliases": []}]
    corrections_map = {"arobynn": "PERSON"}  # type already PERSON
    _apply_llm_type_corrections(entities, corrections_map)
    assert entities[0]["type"] == "PERSON"  # unchanged, not re-set


@pytest.fixture
def classification_tmp_env(tmp_path):
    """Set up a minimal processing environment for run_studio_mode integration tests.

    Returns (tmp_path, processing_dir) with empty entity files and
    entity_type_corrections.json containing Arobynn PLACE→PERSON.
    """
    import json as _json
    processing_dir = tmp_path / "processing_output" / "testbook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "entity_type_corrections.json").write_text(
        _json.dumps([{"name": "Arobynn", "from": "PLACE", "to": "PERSON"}])
    )
    for fname, key in [("persons_full.json", "persons_full"),
                       ("places_full.json", "places_full"),
                       ("orgs_full.json", "orgs_full"),
                       ("events_full.json", "events_full")]:
        (processing_dir / fname).write_text(_json.dumps({key: {}}))
    book_file = tmp_path / "books" / "testbook.epub"
    book_file.parent.mkdir(parents=True)
    book_file.touch()
    return tmp_path, processing_dir


def test_corrections_lower_priority_than_entity_overrides(monkeypatch, classification_tmp_env):
    """LLM correction says PERSON; manual override force_type=PLACE wins."""
    import io
    import json
    import yaml
    from scripts.entity_classification import run_studio_mode

    tmp_path, processing_dir = classification_tmp_env
    book_file = tmp_path / "books" / "testbook.epub"

    book_yaml = yaml.dump({
        "file_path": str(book_file),
        "thresholds": "auto",
        "entity_overrides": {"Arobynn": {"force_type": "PLACE"}},
    })
    entities = [
        {"canonical_name": "Arobynn", "type": "PLACE", "aliases": [], "source_ids": [], "relevant": True}
    ]
    payload = {
        "additional_context": book_yaml,
        "previous_outputs": {
            "alias-resolution": {"entities": entities, "narrator": None},
            "relationship-extraction": {
                "entities": entities, "relationships": [], "stats": {}, "narrator": None,
            },
        },
        "all_stage_outputs": {},
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    run_studio_mode()

    result = json.loads(captured.getvalue())
    arobynn = next(e for e in result["entities"] if e["canonical_name"] == "Arobynn")
    assert arobynn["type"] == "PLACE", f"Expected PLACE (manual override wins), got {arobynn['type']}"


def test_run_studio_mode_applies_corrections_file(monkeypatch, classification_tmp_env):
    """Integration: entity_type_corrections.json present → type corrected in output."""
    import io
    import json
    import yaml
    from scripts.entity_classification import run_studio_mode

    tmp_path, processing_dir = classification_tmp_env
    book_file = tmp_path / "books" / "testbook.epub"

    book_yaml = yaml.dump({"file_path": str(book_file), "thresholds": "auto"})
    entities = [
        {"canonical_name": "Arobynn", "type": "PLACE", "aliases": [], "source_ids": [], "relevant": True}
    ]
    payload = {
        "additional_context": book_yaml,
        "previous_outputs": {
            "alias-resolution": {"entities": entities, "narrator": None},
            "relationship-extraction": {
                "entities": entities,
                "relationships": [],
                "stats": {},
                "narrator": None,
            },
        },
        "all_stage_outputs": {},
    }

    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)

    run_studio_mode()

    result = json.loads(captured.getvalue())
    arobynn = next(e for e in result["entities"] if e["canonical_name"] == "Arobynn")
    assert arobynn["type"] == "PERSON", f"Expected PERSON, got {arobynn['type']}"
