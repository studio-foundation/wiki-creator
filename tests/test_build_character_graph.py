import json
import sys
from unittest.mock import patch

import pytest

from wiki_creator.character_graph import CharacterGraph

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
        "relationship_type": "ally", "direction": "symétrique",
        "evolution": "", "books": ["01-tog"],
    },
    {
        "entity_a": "Celaena", "entity_b": "Cain",
        "cooccurrence_count": 20, "chapters": ["C10.xhtml"],
        "chapter_weights": {"01-tog/C10.xhtml": 20},
        "sample_contexts": ["Cain défia Celaena."],
        "relationship_type": "enemy", "direction": "A→B",
        "evolution": "", "books": ["01-tog"],
    },
    {
        # Entity not in the entity list — skipped with a warning.
        "entity_a": "Ghost", "entity_b": "Chaol",
        "cooccurrence_count": 5, "chapters": ["C01.xhtml"],
        "chapter_weights": {}, "sample_contexts": [],
        "relationship_type": None, "direction": None,
        "evolution": "", "books": ["01-tog"],
    },
]


@pytest.fixture
def book(tmp_path):
    """A book YAML in the library layout book_paths_from_yaml expects."""
    series = tmp_path / "library" / "maas" / "throne-of-glass"
    (series / "books").mkdir(parents=True)
    yaml_path = series / "books" / "01-tog.yaml"
    yaml_path.write_text("title: Throne of Glass\n")
    processing = series / "processing_output" / "01-tog"
    processing.mkdir(parents=True)
    return yaml_path


def _processing(book_yaml):
    return book_yaml.parent.parent / "processing_output" / book_yaml.stem


def _write_artifacts(
    book_yaml, entities, relationships,
    source="relationships_classified.json", roster=None,
):
    processing = _processing(book_yaml)
    (processing / "entities_classified.json").write_text(json.dumps({"entities": entities}))
    bundle = {"relationships": relationships}
    if roster is not None:
        bundle["entities"] = roster
    (processing / source).write_text(json.dumps(bundle))


def _roster_of(entities):
    """The `RelationshipBundle.entities` shape discovery records — `type`, not `entity_type`."""
    return [{"canonical_name": e["canonical_name"], "type": e["type"]} for e in entities]


def _run(book_yaml):
    """Run the pre-step against a book; return (series_graph, delta) or None if it wrote nothing."""
    import scripts.build_character_graph as bcg

    with patch.object(sys, "argv", ["build_character_graph.py", "--book", str(book_yaml)]):
        bcg.main()

    series_path = book_yaml.parent.parent / "character_graph.json"
    if not series_path.exists():
        return None
    delta_path = _processing(book_yaml) / "character_graph_delta.json"
    return (
        CharacterGraph.from_json(json.loads(series_path.read_text())),
        CharacterGraph.from_json(json.loads(delta_path.read_text())),
    )


def test_builds_character_nodes_from_entities(book):
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph, _ = _run(book)
    assert "Celaena" in graph._g.nodes
    assert "Chaol" in graph._g.nodes


def test_builds_interaction_edges(book):
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph, _ = _run(book)
    assert graph._g.has_edge("Celaena", "Chaol")
    assert graph._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45


def test_edges_carry_the_discovered_relationship_type(book):
    """STU-575: the whole point of moving the build after discovery. An untyped
    graph starves indirect_relationships, which drops any path with an untyped hop."""
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph, _ = _run(book)
    assert graph._g.edges["Celaena", "Chaol"]["relationship_type"] == "ally"
    assert graph._g.edges["Celaena", "Cain"]["relationship_type"] == "enemy"
    assert graph._g.edges["Celaena", "Cain"]["direction"] == "A→B"


def test_skips_edge_with_unknown_entity(book):
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph, _ = _run(book)
    assert not graph._g.has_edge("Ghost", "Chaol")


def test_chapter_weights_preserved(book):
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph, _ = _run(book)
    assert "01-tog/C01.xhtml" in graph._g.edges["Celaena", "Chaol"]["chapter_weights"]


def test_delta_contains_only_current_book(book):
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    _, delta = _run(book)
    assert "Celaena" in delta._g.nodes


def test_merges_into_existing_series_graph(book):
    _write_artifacts(book, SAMPLE_ENTITIES[:2], SAMPLE_RELATIONSHIPS[:1])
    _run(book)
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph, _ = _run(book)
    assert graph._g.edges["Celaena", "Chaol"]["cooccurrence_count"] == 45 + 45


def test_falls_back_to_the_discovered_artifact(book):
    """classify-relationships adds prose over the same typed pairs; if it never
    ran, the discovered set is still typed and still worth a graph."""
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS,
                     source="relationships_discovered.json")
    graph, _ = _run(book)
    assert graph._g.edges["Celaena", "Chaol"]["relationship_type"] == "ally"


def test_prefers_classified_over_discovered(book):
    processing = _processing(book)
    (processing / "entities_classified.json").write_text(json.dumps({"entities": SAMPLE_ENTITIES}))
    (processing / "relationships_discovered.json").write_text(
        json.dumps({"relationships": SAMPLE_RELATIONSHIPS})
    )
    with_prose = json.loads(json.dumps(SAMPLE_RELATIONSHIPS))
    with_prose[0]["evolution"] = "Ils passent de la méfiance à la confiance."
    (processing / "relationships_classified.json").write_text(
        json.dumps({"relationships": with_prose})
    )
    graph, _ = _run(book)
    assert graph._g.edges["Celaena", "Chaol"]["evolution"].startswith("Ils passent")


def test_writes_nothing_without_a_typed_source(book, capsys):
    """No typed relations means the only graph available is the untyped
    co-occurrence one — the state STU-575 exists to end. Warn, write nothing,
    leave whatever is on disk intact rather than overwrite it with junk."""
    _processing(book).joinpath("entities_classified.json").write_text(
        json.dumps({"entities": SAMPLE_ENTITIES})
    )
    assert _run(book) is None
    assert "no typed relations" in capsys.readouterr().err


def test_writes_nothing_without_classified_entities(book, capsys):
    _processing(book).joinpath("relationships_classified.json").write_text(
        json.dumps({"relationships": SAMPLE_RELATIONSHIPS})
    )
    assert _run(book) is None
    assert "writing nothing" in capsys.readouterr().err


def test_merge_types_an_edge_a_pre_stu575_graph_left_untyped(book):
    """A graph built before STU-575 carries relationship_type: null on every edge.
    Merging must fill it, or the artifact never converges on a re-run."""
    untyped = json.loads(json.dumps(SAMPLE_RELATIONSHIPS[:1]))
    untyped[0]["relationship_type"] = None
    untyped[0]["direction"] = None
    _write_artifacts(book, SAMPLE_ENTITIES, untyped)
    graph, _ = _run(book)
    assert graph._g.edges["Celaena", "Chaol"]["relationship_type"] is None

    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    graph, _ = _run(book)
    assert graph._g.edges["Celaena", "Chaol"]["relationship_type"] == "ally"


def test_writes_nothing_when_the_relations_predate_the_current_roster(book, capsys):
    """STU-602: the typed artifact records the PERSON roster it was discovered
    against. A later re-resolution renames or retypes an entity, and every edge
    naming the old canonical is silently dropped one entity at a time — on Narnia
    that read as a 44% gate loss and was diagnosed as two artifacts disagreeing.
    The artifact is stale; refuse it whole rather than build from its survivors."""
    stale = _roster_of(SAMPLE_ENTITIES)
    stale[0]["canonical_name"] = "CELAENA"
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS, roster=stale)
    assert _run(book) is None
    err = capsys.readouterr().err
    assert "roster" in err
    assert "CELAENA" in err


def test_builds_when_the_recorded_roster_matches(book):
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS,
                     roster=_roster_of(SAMPLE_ENTITIES))
    graph, _ = _run(book)
    assert graph._g.edges["Celaena", "Chaol"]["relationship_type"] == "ally"


def test_a_non_person_roster_entry_is_not_part_of_the_comparison(book):
    """Only PERSON enters either side: discovery rosters PERSON, the graph gates on
    PERSON. A FACTION in the bundle is not a divergence."""
    roster = _roster_of(SAMPLE_ENTITIES) + [{"canonical_name": "Beavers", "type": "FACTION"}]
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS, roster=roster)
    assert _run(book) is not None


def test_merge_keeps_an_existing_type(book):
    """A type already on the edge is an earlier tome's verdict and stands."""
    _write_artifacts(book, SAMPLE_ENTITIES, SAMPLE_RELATIONSHIPS)
    _run(book)
    retyped = json.loads(json.dumps(SAMPLE_RELATIONSHIPS))
    retyped[0]["relationship_type"] = "enemy"
    _write_artifacts(book, SAMPLE_ENTITIES, retyped)
    graph, _ = _run(book)
    assert graph._g.edges["Celaena", "Chaol"]["relationship_type"] == "ally"
