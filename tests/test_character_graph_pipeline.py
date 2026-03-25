import json
from dataclasses import asdict
from pathlib import Path
from wiki_creator.character_graph import CharacterGraph

FIXTURES = Path(__file__).parent / "fixtures" / "character_graph"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def test_indirect_relationships_enriched_in_bundle():
    """build_entity_bundle should add indirect_relationships when graph is provided."""
    from scripts.wiki_preparation import build_entity_bundle

    graph = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))

    entity = {
        "canonical_name": "Nehemia",
        "type": "PERSON",
        "importance": "major",
        "aliases": [],
        "total_mentions": 30,
        "chapters_present": 5,
        "mentions_by_chapter": {},
    }
    relationships = []  # direct relationships from flat list (legacy)

    bundle = build_entity_bundle(
        entity=entity,
        relationships=relationships,
        persons={}, places={}, orgs={}, events={},
        entities_by_name={"Nehemia": entity},
        graph=graph,
    )

    assert "indirect_relationships" in bundle
    targets = [r["entity_b"] for r in bundle["indirect_relationships"]]
    assert "Cain" in targets


def test_indirect_relationships_absent_for_minor_character():
    """Minor characters should still get indirect_relationships computed (filtering happens downstream)."""
    from scripts.wiki_preparation import build_entity_bundle

    graph = CharacterGraph.from_json(_load_fixture("minimal_graph.json"))
    entity = {
        "canonical_name": "Cain",
        "type": "PERSON",
        "importance": "supporting",
        "aliases": [],
        "total_mentions": 10,
        "chapters_present": 2,
        "mentions_by_chapter": {},
    }
    bundle = build_entity_bundle(
        entity=entity,
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={"Cain": entity},
        graph=graph,
    )
    # indirect_relationships key should exist (may be empty for supporting)
    assert "indirect_relationships" in bundle


def test_bundle_graceful_when_no_graph():
    """build_entity_bundle should work without a graph (graph=None)."""
    from scripts.wiki_preparation import build_entity_bundle

    entity = {
        "canonical_name": "Nehemia",
        "type": "PERSON",
        "importance": "major",
        "aliases": [],
        "total_mentions": 10,
        "chapters_present": 3,
        "mentions_by_chapter": {},
    }
    bundle = build_entity_bundle(
        entity=entity,
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={"Nehemia": entity},
        graph=None,
    )
    assert bundle["indirect_relationships"] == []


def test_series_graph_merged_across_two_books():
    """merge_book correctly accumulates two books."""
    g1 = CharacterGraph.from_json(_load_fixture("book1_delta.json"))
    g2 = CharacterGraph.from_json(_load_fixture("book2_delta.json"))
    g1.merge_book(g2)
    # Celaena↔Chaol: 20 (book1) + 25 (book2) = 45
    assert g1._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45
    # Aedion added from book2
    assert "Aedion" in g1._g.nodes
    # Both books listed
    assert "01-tog" in g1._g.nodes["Celaena"]["books"]
    assert "02-com" in g1._g.nodes["Celaena"]["books"]


def test_indirect_block_injected_for_major_character():
    """build_prompt should include indirect relationship line for major characters."""
    import scripts.generate_wiki_pages as gwp

    entity_bundle = {
        "canonical_name": "Nehemia",
        "type": "PERSON",
        "importance": "major",
        "aliases": [],
        "total_mentions": 30,
        "chapters_present": 5,
        "relationships": [],
        "indirect_relationships": [
            {"entity_a": "Nehemia", "entity_b": "Cain", "via": ["Celaena"],
             "path_edge_types": ["amie", "antagoniste"], "strength": 0.67, "inferred": True},
            {"entity_a": "Nehemia", "entity_b": "Chaol", "via": ["Celaena"],
             "path_edge_types": ["amie", "allié"], "strength": 0.60, "inferred": True},
        ],
        "related_context": [],
        "context_by_chapter": {},
        "first_seen": None,
        "chapter_summary_context": [],
    }
    prompt = gwp.build_prompt(entity_bundle, book_title="Throne of Glass", sections=["infobox", "biography", "relationships"])
    assert "inferred: true" in prompt
    assert "Cain" in prompt
