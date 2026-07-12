import json
import pytest
from pathlib import Path
from wiki_creator.character_graph import CharacterGraph, IndirectRelationship
from wiki_creator.paths import book_paths_from_yaml

FIXTURES = Path(__file__).parent / "fixtures" / "character_graph"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_from_json_raises_on_incompatible_format():
    with pytest.raises(ValueError, match="incompatible"):
        CharacterGraph.from_json({"nodes": [], "links": []})


def test_from_json_roundtrip_empty():
    g = CharacterGraph()
    data = g.to_json()
    g2 = CharacterGraph.from_json(data)
    assert g2.to_json() == data


def test_add_and_retrieve_character():
    g = CharacterGraph()
    g.add_character("Celaena", {"importance": "major", "aliases": [], "books": ["01-tog"]})
    assert "Celaena" in g._g.nodes
    assert g._g.nodes["Celaena"]["importance"] == "major"


def test_add_interaction_stored_as_edge():
    g = CharacterGraph()
    g.add_character("Celaena", {"importance": "major", "aliases": [], "books": ["01-tog"]})
    g.add_character("Chaol", {"importance": "major", "aliases": [], "books": ["01-tog"]})
    g.add_interaction("Celaena", "Chaol", {
        "relationship_type": "allié", "direction": "symétrique",
        "cooccurrence_count": 45,
        "chapter_weights": {"01-tog/C01.xhtml": 10},
        "sample_contexts": ["ils marchèrent ensemble."],
        "evolution": "", "books": ["01-tog"],
    })
    assert g._g.has_edge("Celaena", "Chaol")
    assert g._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45


def test_direct_relationships_returns_both_directions():
    g = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    rels = g.direct_relationships("Celaena")
    names = {r["entity_b"] for r in rels} | {r["entity_a"] for r in rels}
    assert "Chaol" in names
    assert "Nehemia" in names
    assert "Cain" in names


def test_indirect_relationship_confidence_is_interpretation():
    """STU-428: multi-hop paths are interpretation, never attested fact."""
    r = IndirectRelationship("A", "B", ["X"], ["co-occurrence"], 0.5)
    assert r.confidence == "interpretation"


def test_indirect_relationships_two_hop():
    g = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    # Nehemia and Cain are not directly connected; both connect via Celaena
    indirect = g.indirect_relationships("Nehemia")
    targets = [r.entity_b for r in indirect]
    assert "Cain" in targets
    r = next(r for r in indirect if r.entity_b == "Cain")
    assert r.via == ["Celaena"]
    assert r.inferred is True


def test_indirect_relationships_excludes_direct_neighbors():
    g = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    indirect = g.indirect_relationships("Celaena")
    # All nodes are direct neighbors of Celaena — no indirect results
    assert indirect == []


def test_indirect_relationships_strength_below_threshold_filtered():
    g = CharacterGraph()
    g.add_character("A", {"importance": "major", "aliases": [], "books": ["b"]})
    g.add_character("B", {"importance": "major", "aliases": [], "books": ["b"]})
    g.add_character("C", {"importance": "major", "aliases": [], "books": ["b"]})
    # Very low counts → strength will be near 0
    g.add_interaction("A", "B", {"relationship_type": "allié", "cooccurrence_count": 1,
                                  "chapter_weights": {}, "sample_contexts": [],
                                  "evolution": "", "books": ["b"]})
    g.add_interaction("B", "C", {"relationship_type": "allié", "cooccurrence_count": 1,
                                  "chapter_weights": {}, "sample_contexts": [],
                                  "evolution": "", "books": ["b"]})
    # max_count=1, strength = 1/1 * 1/1 = 1.0 — should NOT be filtered
    # (only filtered if < 0.1)
    indirect = g.indirect_relationships("A")
    assert len(indirect) == 1  # A→C via B, strength=1.0


def test_indirect_relationships_max_hops_respected():
    g = CharacterGraph()
    for name in ["A", "B", "C", "D"]:
        g.add_character(name, {"importance": "major", "aliases": [], "books": ["b"]})
    for a, b in [("A", "B"), ("B", "C"), ("C", "D")]:
        g.add_interaction(a, b, {"relationship_type": "allié", "cooccurrence_count": 50,
                                  "chapter_weights": {}, "sample_contexts": [],
                                  "evolution": "", "books": ["b"]})
    # A→D requires 3 hops; with max_hops=2 it should not appear
    indirect = g.indirect_relationships("A", max_hops=2)
    assert not any(r.entity_b == "D" for r in indirect)
    # With max_hops=3 it should appear
    indirect3 = g.indirect_relationships("A", max_hops=3)
    assert any(r.entity_b == "D" for r in indirect3)


def test_merge_book_accumulates_cooccurrence_counts():
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    assert g1._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45  # 20 + 25


def test_merge_book_merges_chapter_weights():
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    cw = g1._g.edges["Celaena", "Chaol"]["chapter_weights"]
    assert "01-tog/C01.xhtml" in cw
    assert "02-com/C02.xhtml" in cw


def test_merge_book_adds_new_nodes():
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    assert "Aedion" in g1._g.nodes


def test_merge_book_extends_books_list():
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    books = g1._g.nodes["Celaena"]["books"]
    assert "01-tog" in books
    assert "02-com" in books


def test_serialization_roundtrip():
    g = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    data = g.to_json()
    g2 = CharacterGraph.from_json(data)
    assert set(g2._g.nodes) == set(g._g.nodes)
    assert set(g2._g.edges) == set(g._g.edges)


def test_series_character_graph_path():
    # Use the real book yaml from the library
    yaml = "library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml"
    paths = book_paths_from_yaml(yaml)
    sgp = paths.series_character_graph
    # Should be: library/sarah_j_maas/throne-of-glass/character_graph.json
    assert sgp.name == "character_graph.json"
    assert "throne-of-glass" in str(sgp)
    assert "processing_output" not in str(sgp)


def test_book_graph_delta_path():
    yaml = "library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml"
    paths = book_paths_from_yaml(yaml)
    delta = paths.book_graph_delta
    assert delta.name == "character_graph_delta.json"
    assert "processing_output" in str(delta)
    assert "01-throne-of-glass" in str(delta)
