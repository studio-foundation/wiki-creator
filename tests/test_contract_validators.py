"""Unit tests for the structural contract validators (pure logic)."""

from wiki_creator.contract_validators import (
    batches_errors,
    character_graph_errors,
    classified_entity_errors,
    sections_complete_errors,
    split_clusters_errors,
)
from wiki_creator.entity_taxonomy import resolution_types

ALLOWED = set(resolution_types())


def _entity(**overrides):
    base = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "aliases": [],
        "source_ids": ["e1"],
        "relevant": True,
        "total_mentions": 10,
        "chapters_present": 3,
        "importance": "principal",
    }
    base.update(overrides)
    return base


# ---- classified_entity_errors ------------------------------------------------


def test_valid_entity_passes():
    assert classified_entity_errors([_entity()], ALLOWED) == []


def test_faction_type_is_accepted_from_runtime_vocabulary():
    # The drift STU-432 targets: FACTION shipped in STU-505 but the restated
    # enum comment never listed it. Reading base.yaml at runtime accepts it.
    assert "FACTION" in ALLOWED
    assert classified_entity_errors([_entity(type="FACTION")], ALLOWED) == []


def test_unknown_type_fails():
    errors = classified_entity_errors([_entity(type="WEAPON")], ALLOWED)
    assert len(errors) == 1
    assert "WEAPON" in errors[0]


def test_bad_importance_fails():
    errors = classified_entity_errors([_entity(importance="lead")], ALLOWED)
    assert any("importance" in e for e in errors)


def test_missing_counts_fail():
    errors = classified_entity_errors([_entity(total_mentions="10")], ALLOWED)
    assert any("total_mentions" in e for e in errors)


def test_wrong_field_types_fail():
    errors = classified_entity_errors(
        [_entity(canonical_name="", aliases="x", relevant="yes")], ALLOWED
    )
    assert any("canonical_name" in e for e in errors)
    assert any("aliases" in e for e in errors)
    assert any("relevant" in e for e in errors)


def test_entities_must_be_list():
    assert classified_entity_errors({}, ALLOWED)
    assert classified_entity_errors("nope", ALLOWED)


# ---- character_graph_errors --------------------------------------------------


def _graph(nodes=None, links=None):
    return {
        "nodes": nodes if nodes is not None else [
            {"id": "Celaena", "type": "CHARACTER", "importance": "principal",
             "aliases": [], "books": ["01"]}
        ],
        "links": links if links is not None else [
            {"source": "Celaena", "target": "Chaol", "edge_type": "INTERACTION",
             "cooccurrence_count": 5, "chapter_weights": {}, "sample_contexts": [],
             "books": ["01"]}
        ],
    }


def test_valid_graph_passes():
    assert character_graph_errors({"graph": _graph(), "delta": _graph()}) == []


def test_empty_graphs_pass_structurally():
    # STU-587's empty-nodes bug is an application defect; an empty (but
    # well-formed) graph is structurally valid.
    assert character_graph_errors(
        {"graph": {"nodes": [], "links": []}, "delta": {"nodes": [], "links": []}}
    ) == []


def test_node_wrong_enum_fails():
    bad = _graph(nodes=[{"id": "X", "type": "PERSON", "importance": "p",
                         "aliases": [], "books": []}])
    errors = character_graph_errors({"graph": bad, "delta": _graph()})
    assert any("CHARACTER" in e for e in errors)


def test_link_wrong_enum_and_missing_fields_fail():
    bad = _graph(links=[{"source": "A", "target": "B", "edge_type": "co"}])
    errors = character_graph_errors({"graph": bad, "delta": _graph()})
    assert any("INTERACTION" in e for e in errors)
    assert any("cooccurrence_count" in e for e in errors)


def test_graph_must_be_object():
    errors = character_graph_errors({"graph": [], "delta": _graph()})
    assert any("graph must be a node_link_data object" in e for e in errors)


# ---- batches_errors ----------------------------------------------------------


def test_valid_batches_pass():
    out = {"batches": [{"batch_id": "batch_000", "file": "wiki_inputs/b.json",
                        "entity_count": 4}]}
    assert batches_errors(out) == []


def test_empty_batches_list_is_valid():
    assert batches_errors({"batches": []}) == []


def test_batch_bad_shape_fails():
    out = {"batches": [{"batch_id": "", "file": 3, "entity_count": "4"}]}
    errors = batches_errors(out)
    assert any("batch_id" in e for e in errors)
    assert any("file" in e for e in errors)
    assert any("entity_count" in e for e in errors)


def test_batches_must_be_list():
    assert batches_errors({"batches": {}})


# ---- split_clusters_errors ---------------------------------------------------


def test_valid_split_clusters_pass():
    out = {"singles_resolved": [], "by_type": {"PERSON": [], "PLACE": []}}
    assert split_clusters_errors(out) == []


def test_by_type_value_must_be_list():
    out = {"singles_resolved": [], "by_type": {"PERSON": {}}}
    errors = split_clusters_errors(out)
    assert any("PERSON" in e for e in errors)


def test_singles_and_by_type_required_shapes():
    errors = split_clusters_errors({"singles_resolved": "x", "by_type": []})
    assert any("singles_resolved" in e for e in errors)
    assert any("by_type" in e for e in errors)


# ---- sections_complete_errors ------------------------------------------------


def test_valid_sections_pass():
    out = {"chapters": [{"id": "ch01", "title": "One", "content": "text"}]}
    assert sections_complete_errors(out) == []


def test_empty_chapters_fail():
    assert sections_complete_errors({"chapters": []})


def test_emptied_content_fails():
    out = {"chapters": [{"id": "ch01", "title": "One", "content": ""}]}
    errors = sections_complete_errors(out)
    assert any("content" in e for e in errors)


def test_missing_id_fails():
    out = {"chapters": [{"title": "One", "content": "text"}]}
    errors = sections_complete_errors(out)
    assert any("id" in e for e in errors)
