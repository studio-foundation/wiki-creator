import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from wiki_creator.character_graph import CharacterGraph

# Minimal Studio payload
SAMPLE_ENTITIES = [
    {"canonical_name": "Celaena", "type": "PERSON", "importance": "major",
     "aliases": ["Laena"], "relevant": True},
    {"canonical_name": "Chaol", "type": "PERSON", "importance": "major",
     "aliases": [], "relevant": True},
    {"canonical_name": "Cain", "type": "PERSON", "importance": "supporting",
     "aliases": [], "relevant": True},
]

SAMPLE_RELATIONSHIPS = [
    {
        "entity_a": "Celaena", "entity_b": "Chaol",
        "cooccurrence_count": 45, "chapters": ["C01.xhtml", "C05.xhtml"],
        "chapter_weights": {"01-tog/C01.xhtml": 10, "01-tog/C05.xhtml": 35},
        "sample_contexts": ["Ils marchèrent."],
        "relationship_type": "allié", "direction": "symétrique",
        "evolution": "", "books": ["01-tog"],
    },
    {
        "entity_a": "Celaena", "entity_b": "Cain",
        "cooccurrence_count": 20, "chapters": ["C10.xhtml"],
        "chapter_weights": {"01-tog/C10.xhtml": 20},
        "sample_contexts": ["Cain défia Celaena."],
        "relationship_type": "antagoniste", "direction": "asymétrique",
        "evolution": "", "books": ["01-tog"],
    },
    {
        # Entity not in entity list — should be skipped with warning
        "entity_a": "Ghost", "entity_b": "Chaol",
        "cooccurrence_count": 5, "chapters": ["C01.xhtml"],
        "chapter_weights": {}, "sample_contexts": [],
        "relationship_type": None, "direction": None,
        "evolution": "", "books": ["01-tog"],
    },
]


def _run_script(entities, relationships, book_slug="01-tog", series_graph=None):
    """Run build_character_graph main() with given inputs, return (graph, delta)."""
    import scripts.build_character_graph as bsg

    payload = {
        "all_stage_outputs": {
            "entity-classification": {"entities": entities, "relationships": relationships}
        },
        "additional_context": f"book_slug: {book_slug}\n",
    }
    output = StringIO()
    with patch("sys.stdin", StringIO(json.dumps(payload))), \
         patch("sys.stdout", output):
        bsg.main(series_graph_data=series_graph)

    result = json.loads(output.getvalue())
    return result


def test_builds_character_nodes_from_entities():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph = CharacterGraph.from_json(result["graph"])
    assert "Celaena" in graph._g.nodes
    assert "Chaol" in graph._g.nodes


def test_builds_interaction_edges():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph = CharacterGraph.from_json(result["graph"])
    assert graph._g.has_edge("Celaena", "Chaol")
    assert graph._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45


def test_skips_edge_with_unknown_entity():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph = CharacterGraph.from_json(result["graph"])
    # "Ghost" is not in entities → edge Ghost↔Chaol should not appear
    assert not graph._g.has_edge("Ghost", "Chaol")


def test_chapter_weights_preserved():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph = CharacterGraph.from_json(result["graph"])
    cw = graph._g.edges["Celaena", "Chaol"]["chapter_weights"]
    assert "01-tog/C01.xhtml" in cw


def test_delta_output_contains_only_current_book():
    result = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    assert "delta" in result
    delta = CharacterGraph.from_json(result["delta"])
    assert "Celaena" in delta._g.nodes


def test_merges_into_existing_series_graph():
    # First build
    r1 = _run_script(SAMPLE_ENTITIES[:2], SAMPLE_RELATIONSHIPS[:1], book_slug="01-tog")
    # Second build merges into existing
    r2 = _run_script(SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS, book_slug="02-com",
                     series_graph=r1["graph"])
    graph = CharacterGraph.from_json(r2["graph"])
    # Celaena↔Chaol should have accumulated counts
    count = graph._g.edges["Celaena", "Chaol"]["cooccurrence_count"]
    assert count == 45 + 45  # both runs have 45
