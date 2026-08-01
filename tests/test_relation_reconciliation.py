"""STU-754: relation-graph reconciliation — roster orphans + cooccurrence gaps.

The reconciliation pass diffs the PERSON roster against the typed graph
`discover-relationships` produced, and folds any agentic point-query's
recovered relations back through the exact `valid_relations`/`aggregate`
validation discovery itself uses. No LLM here — these are the deterministic
gap-detection and fold halves.
"""
import json

from scripts.relation_reconciliation import (
    _MIN_COOCCURRENCE_FOR_GAP,
    collect_and_save,
    prepare_reconciliation,
)
from wiki_creator.paths import BookPaths
from wiki_creator.registry import EntityRecord, Registry
from wiki_creator.types import Relationship, RelationshipBundle


def _entity(name: str, *, entity_type: str = "PERSON", offstage: bool = False) -> EntityRecord:
    return EntityRecord(
        entity_id=name.lower().replace(" ", "-"),
        canonical_name=name,
        entity_type=entity_type,
        aliases=[name],
        offstage=offstage,
    )


def _book_paths(tmp_path) -> BookPaths:
    processing = tmp_path / "processing_output" / "book"
    processing.mkdir(parents=True)
    return BookPaths(
        epub=tmp_path / "book.epub",
        processing=processing,
        wiki_inputs=tmp_path / "wiki_inputs" / "book",
        output=tmp_path / "output" / "book",
    )


def _write_chapters(paths: BookPaths) -> None:
    (paths.processing / "chapters.json").write_text(
        json.dumps({"chapters": {"ch1": "Some narrative text."}}), encoding="utf-8"
    )


def _write_registry(paths: BookPaths, entities: list[EntityRecord]) -> None:
    Registry(entities=entities).save(paths.processing / "registry.json")


def _write_discovered(paths: BookPaths, relationships: list[Relationship]) -> None:
    from wiki_creator import studio_io

    bundle = RelationshipBundle(
        entities=[],
        relationships=relationships,
        stats={},
    )
    studio_io.save_artifact(
        paths.processing / "relationships_discovered.json", bundle, RelationshipBundle
    )


def _write_cooccurrence(paths: BookPaths, relationships: list[Relationship]) -> None:
    from wiki_creator import studio_io

    bundle = RelationshipBundle(entities=[], relationships=relationships, stats={})
    studio_io.save_artifact(paths.processing / "relationships.json", bundle, RelationshipBundle)


# --- prepare_reconciliation: gap detection ----------------------------------


def test_missing_discovered_graph_skips(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice")])
    _write_chapters(paths)
    prep, skip = prepare_reconciliation({}, paths)
    assert prep is None
    assert skip == "missing_discovered_graph"


def test_person_with_zero_relations_is_an_orphan(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice"), _entity("Bob"), _entity("Carol")])
    _write_chapters(paths)
    _write_discovered(
        paths,
        [Relationship(entity_a="Alice", entity_b="Bob", cooccurrence_count=3, relationship_type="friend")],
    )
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None
    assert [r["name"] for r in prep["rows"]] == ["Carol"]
    assert prep["orphans"] == 1
    assert prep["cooccurrence_gaps"] == 0


def test_fully_typed_roster_has_no_gaps(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice"), _entity("Bob")])
    _write_chapters(paths)
    _write_discovered(
        paths,
        [Relationship(entity_a="Alice", entity_b="Bob", cooccurrence_count=3, relationship_type="friend")],
    )
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None
    assert prep["rows"] == []


def test_offstage_person_is_never_a_gap(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice"), _entity("Bob"), _entity("Ghost", offstage=True)])
    _write_chapters(paths)
    _write_discovered(
        paths,
        [Relationship(entity_a="Alice", entity_b="Bob", cooccurrence_count=3, relationship_type="friend")],
    )
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None
    assert prep["rows"] == []


def test_strong_cooccurrence_pair_absent_from_typed_graph_is_a_gap(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Dan"), _entity("Eve")])
    _write_chapters(paths)
    _write_discovered(paths, [])
    _write_cooccurrence(
        paths,
        [Relationship(entity_a="Dan", entity_b="Eve", cooccurrence_count=_MIN_COOCCURRENCE_FOR_GAP)],
    )
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None
    # both are orphans already (0 typed relations at all), so both are queried
    assert {r["name"] for r in prep["rows"]} == {"Dan", "Eve"}
    assert prep["cooccurrence_gaps"] == 1


def test_weak_cooccurrence_below_threshold_is_not_a_gap(tmp_path):
    paths = _book_paths(tmp_path)
    # Dan/Eve each already have a typed relation elsewhere, so they are not
    # orphans — only the untyped Dan-Eve pair itself could make them a gap.
    paths2 = paths
    _write_registry(paths2, [_entity("Dan"), _entity("Eve"), _entity("Frank")])
    _write_chapters(paths2)
    _write_discovered(
        paths2,
        [
            Relationship(entity_a="Dan", entity_b="Frank", cooccurrence_count=3, relationship_type="friend"),
            Relationship(entity_a="Eve", entity_b="Frank", cooccurrence_count=3, relationship_type="friend"),
        ],
    )
    _write_cooccurrence(
        paths2,
        [Relationship(entity_a="Dan", entity_b="Eve", cooccurrence_count=_MIN_COOCCURRENCE_FOR_GAP - 1)],
    )
    prep, skip = prepare_reconciliation({}, paths2)
    assert skip is None
    assert prep["rows"] == []


# --- collect_and_save: folding recovered relations --------------------------


def _map_output(*outputs: dict | None) -> dict:
    results = []
    for i, output in enumerate(outputs):
        if output is None:
            results.append({"index": i, "status": "failed"})
        else:
            results.append({"index": i, "status": "success", "output": output})
    return {"results": results}


def test_recovered_relation_is_folded_into_the_graph(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice"), _entity("Bob"), _entity("Carol")])
    _write_chapters(paths)
    _write_discovered(
        paths,
        [Relationship(entity_a="Alice", entity_b="Bob", cooccurrence_count=3, relationship_type="friend")],
    )
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None
    assert [r["name"] for r in prep["rows"]] == ["Carol"]

    map_output = _map_output(
        {
            "relations": [
                {
                    "entity_a": "Carol",
                    "entity_b": "Alice",
                    "relationship_type": "friend",
                    "direction": "symmetric",
                    "evidence": "Carol and Alice laughed together.",
                }
            ]
        }
    )
    summary = collect_and_save(prep, map_output)
    assert summary == {"gaps_found": 1, "gaps_recovered": 1}

    saved = json.loads((paths.processing / "relationships_discovered.json").read_text())
    pairs = {(r["entity_a"], r["entity_b"]) for r in saved["relationships"]}
    assert ("Alice", "Bob") in pairs
    assert ("Alice", "Carol") in pairs


def test_recovered_relation_never_overwrites_an_already_typed_pair(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice"), _entity("Bob"), _entity("Carol")])
    _write_chapters(paths)
    _write_discovered(
        paths,
        [
            Relationship(entity_a="Alice", entity_b="Bob", cooccurrence_count=3, relationship_type="friend"),
        ],
    )
    _write_cooccurrence(
        paths,
        [Relationship(entity_a="Bob", entity_b="Carol", cooccurrence_count=_MIN_COOCCURRENCE_FOR_GAP)],
    )
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None
    # Carol is a gap (orphan); the model tries to re-type Alice-Bob too, which
    # must never overwrite the pair discovery already typed.
    gap_names = {r["name"] for r in prep["rows"]}
    assert "Carol" in gap_names

    outputs = []
    for row in prep["rows"]:
        if row["name"] == "Carol":
            outputs.append(
                {
                    "relations": [
                        {
                            "entity_a": "Carol",
                            "entity_b": "Bob",
                            "relationship_type": "ally",
                            "direction": "symmetric",
                            "evidence": "Carol stood beside Bob.",
                        },
                        {
                            "entity_a": "Carol",
                            "entity_b": "Alice",
                            "relationship_type": "enemy",
                            "direction": "symmetric",
                            "evidence": "Carol glared at Alice.",
                        },
                    ]
                }
            )
        else:
            outputs.append({"relations": []})

    summary = collect_and_save(prep, _map_output(*outputs))
    assert summary["gaps_recovered"] == 2

    saved = json.loads((paths.processing / "relationships_discovered.json").read_text())
    by_pair = {(r["entity_a"], r["entity_b"]): r for r in saved["relationships"]}
    assert by_pair[("Alice", "Bob")]["relationship_type"] == "friend"
    assert ("Bob", "Carol") in by_pair
    assert ("Alice", "Carol") in by_pair


def test_off_roster_relation_is_dropped_not_folded(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice"), _entity("Bob")])
    _write_chapters(paths)
    _write_discovered(paths, [])
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None

    map_output = _map_output(
        *(
            {
                "relations": [
                    {
                        "entity_a": row["name"],
                        "entity_b": "Nobody On The Roster",
                        "relationship_type": "friend",
                        "direction": "symmetric",
                        "evidence": "quote",
                    }
                ]
            }
            for row in prep["rows"]
        )
    )
    summary = collect_and_save(prep, map_output)
    assert summary["gaps_recovered"] == 0


def test_no_gaps_short_circuits_without_a_map_output(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice"), _entity("Bob")])
    _write_chapters(paths)
    _write_discovered(
        paths,
        [Relationship(entity_a="Alice", entity_b="Bob", cooccurrence_count=3, relationship_type="friend")],
    )
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None
    assert collect_and_save(prep, None) == {"gaps_found": 0, "gaps_recovered": 0}


def test_missing_map_output_leaves_graph_untouched(tmp_path):
    paths = _book_paths(tmp_path)
    _write_registry(paths, [_entity("Alice"), _entity("Bob"), _entity("Carol")])
    _write_chapters(paths)
    _write_discovered(
        paths,
        [Relationship(entity_a="Alice", entity_b="Bob", cooccurrence_count=3, relationship_type="friend")],
    )
    prep, skip = prepare_reconciliation({}, paths)
    assert skip is None
    summary = collect_and_save(prep, None)
    assert summary == {"gaps_found": 1, "gaps_recovered": 0}
