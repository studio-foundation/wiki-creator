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


def test_untyped_cooccurrence_edge_stays_untyped():
    """The STU-435 co-occurrence input carries no type — folding keeps it None."""
    rels = [
        {"entity_a": "Chaol Westfall", "entity_b": "Celaena", "cooccurrence_count": 5},
    ]
    edge = fold_relationships(rels, _registry(CHAOL, CELAENA))[0]
    assert edge["relationship_type"] is None
    assert edge["direction"] is None
    assert edge["evolution"] is None


def test_pre_typed_edge_type_direction_preserved():
    """STU-583: a pre-typed input edge keeps its type/direction through the fold."""
    rels = [
        {"entity_a": "Celaena", "entity_b": "Chaol", "cooccurrence_count": 5,
         "relationship_type": "enemy", "direction": "A→B", "evidence": "quote"},
    ]
    edge = fold_relationships(rels, _registry(CHAOL, CELAENA))[0]
    assert edge["relationship_type"] == "enemy"
    assert edge["direction"] == "A→B"
    assert edge["evidence"] == "quote"


def test_pre_typed_direction_flips_when_pair_reordered():
    """Carrying direction through a canonical reorder restates it (STU-583)."""
    # Input order Chaol→Celaena; canonical key sorts to (Celaena, Chaol), so the
    # A→B direction must flip to B→A against the reordered pair.
    rels = [
        {"entity_a": "Chaol", "entity_b": "Celaena", "cooccurrence_count": 5,
         "relationship_type": "enemy", "direction": "A→B"},
    ]
    edge = fold_relationships(rels, _registry(CHAOL, CELAENA))[0]
    assert (edge["entity_a"], edge["entity_b"]) == ("Celaena", "Chaol")
    assert edge["direction"] == "B→A"


def test_conflicting_merged_types_collapse_to_none():
    """When folded surface edges disagree on type, neither wins."""
    rels = [
        {"entity_a": "Chaol Westfall", "entity_b": "Celaena", "cooccurrence_count": 5,
         "relationship_type": "enemy", "direction": "symétrique"},
        {"entity_a": "Captain Westfall", "entity_b": "Celaena", "cooccurrence_count": 3,
         "relationship_type": "ally", "direction": "symétrique"},
    ]
    folded = fold_relationships(rels, _registry(CHAOL, CELAENA))
    assert len(folded) == 1
    assert folded[0]["relationship_type"] is None
    assert folded[0]["direction"] == "symétrique"  # agree → kept


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


def test_folding_pre_typed_discovered_graph_keeps_all_typed():
    """STU-583: the discovered graph is already canonical (one edge per pair), so
    folding it must leave every pair typed — the Narnia audit was 32/32 → 0/32."""
    names = [f"E{i}" for i in range(9)]
    records = [
        EntityRecord(entity_id=n.lower(), canonical_name=n, entity_type="PERSON",
                     aliases=[n])
        for n in names
    ]
    pairs = [(a, b) for i, a in enumerate(names) for b in names[i + 1:]][:32]
    rels = [
        {"entity_a": a, "entity_b": b, "cooccurrence_count": 5,
         "relationship_type": "enemy", "direction": "symétrique"}
        for a, b in pairs
    ]
    assert len(rels) == 32
    folded = fold_relationships(rels, _registry(*records))
    assert len(folded) == 32
    typed = sum(1 for e in folded if e["relationship_type"] == "enemy")
    assert typed == 32


def test_output_sorted_by_cooccurrence_desc():
    third = EntityRecord(entity_id="dorian", canonical_name="Dorian",
                         entity_type="PERSON", aliases=["Dorian"])
    rels = [
        {"entity_a": "Chaol", "entity_b": "Dorian", "cooccurrence_count": 4},
        {"entity_a": "Chaol", "entity_b": "Celaena", "cooccurrence_count": 30},
    ]
    folded = fold_relationships(rels, _registry(CHAOL, CELAENA, third))
    assert [e["cooccurrence_count"] for e in folded] == [30, 4]
