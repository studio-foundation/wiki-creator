"""Tests for wiki_creator/relationship_fold.py — STU-435 canonical edge folding."""
from wiki_creator.registry import EntityRecord, Registry
from wiki_creator.relationship_fold import fold_relationships


def _registry(*records: EntityRecord) -> Registry:
    # Bypass validate(): tests build minimal records with only the fields the
    # fold reads (canonical_name, aliases, entity_id).
    return Registry(entities=list(records))


CHAOL = EntityRecord(
    entity_id="chaol",
    canonical_name="Chaol",
    entity_type="PERSON",
    aliases=["Chaol", "Chaol Westfall", "Captain Westfall"],
)
CELAENA = EntityRecord(
    entity_id="celaena",
    canonical_name="Celaena",
    entity_type="PERSON",
    aliases=["Celaena", "Celaena Sardothien"],
)


def test_fragmented_edges_fold_into_one_canonical_pair():
    """The STU-435 repro: Chaol's edges split across two surface forms merge."""
    rels = [
        {"entity_a": "Chaol Westfall", "entity_b": "Celaena",
         "cooccurrence_count": 17, "chapters": ["ch01", "ch02"],
         "sample_contexts": ["ctx-a"]},
        {"entity_a": "Captain Westfall", "entity_b": "Celaena",
         "cooccurrence_count": 10, "chapters": ["ch02", "ch05"],
         "sample_contexts": ["ctx-b"]},
    ]
    folded = fold_relationships(rels, _registry(CHAOL, CELAENA))

    assert len(folded) == 1
    edge = folded[0]
    assert {edge["entity_a"], edge["entity_b"]} == {"Chaol", "Celaena"}
    assert edge["cooccurrence_count"] == 27
    assert edge["chapters"] == ["ch01", "ch02", "ch05"]  # sorted union, deduped
    assert edge["sample_contexts"] == ["ctx-a", "ctx-b"]  # unioned


def test_type_direction_evolution_reset_for_single_classification():
    rels = [
        {"entity_a": "Chaol Westfall", "entity_b": "Celaena",
         "cooccurrence_count": 5, "relationship_type": "ami", "direction": "a_to_b",
         "evolution": "stable"},
    ]
    edge = fold_relationships(rels, _registry(CHAOL, CELAENA))[0]
    assert edge["relationship_type"] is None
    assert edge["direction"] is None
    assert edge["evolution"] is None


def test_self_pair_after_folding_is_dropped():
    rels = [
        {"entity_a": "Chaol Westfall", "entity_b": "Captain Westfall",
         "cooccurrence_count": 9},
    ]
    assert fold_relationships(rels, _registry(CHAOL, CELAENA)) == []


def test_unknown_surface_passes_through_unfolded():
    """A name absent from the registry is kept (edge not lost), just unfolded."""
    rels = [
        {"entity_a": "Chaol Westfall", "entity_b": "Mystery Man",
         "cooccurrence_count": 3},
    ]
    edge = fold_relationships(rels, _registry(CHAOL, CELAENA))[0]
    assert {edge["entity_a"], edge["entity_b"]} == {"Chaol", "Mystery Man"}


def test_sample_contexts_capped():
    rels = [
        {"entity_a": "Chaol Westfall", "entity_b": "Celaena",
         "cooccurrence_count": 1, "sample_contexts": [f"ctx-{i}" for i in range(20)]},
    ]
    edge = fold_relationships(rels, _registry(CHAOL, CELAENA))[0]
    assert len(edge["sample_contexts"]) == 12


def test_output_sorted_by_cooccurrence_desc():
    third = EntityRecord(entity_id="dorian", canonical_name="Dorian",
                         entity_type="PERSON", aliases=["Dorian"])
    rels = [
        {"entity_a": "Chaol", "entity_b": "Dorian", "cooccurrence_count": 4},
        {"entity_a": "Chaol", "entity_b": "Celaena", "cooccurrence_count": 30},
    ]
    folded = fold_relationships(rels, _registry(CHAOL, CELAENA, third))
    assert [e["cooccurrence_count"] for e in folded] == [30, 4]
