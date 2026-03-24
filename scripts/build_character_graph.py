"""build_character_graph.py — Studio script.

Reads from stdin: JSON payload with all_stage_outputs containing entity-classification output.
Writes to stdout: JSON with {"graph": <node_link_data>, "delta": <node_link_data>}

Also writes:
  - series_character_graph (atomic: write-to-temp + rename)
  - book_graph_delta
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from wiki_creator.character_graph import CharacterGraph
from wiki_creator.paths import book_paths_from_yaml


def _build_book_graph(entities: list[dict], relationships: list[dict], book_slug: str) -> CharacterGraph:
    """Build a CharacterGraph from entity-classification output for one book."""
    g = CharacterGraph()

    known_names: set[str] = set()
    for ent in entities:
        if ent.get("type") != "PERSON":
            continue
        name = ent.get("canonical_name", "")
        if not name:
            continue
        g.add_character(name, {
            "importance": ent.get("importance", "minor"),
            "aliases": ent.get("aliases", []),
            "books": [book_slug],
        })
        known_names.add(name)

    for rel in relationships:
        a = rel.get("entity_a", "")
        b = rel.get("entity_b", "")
        count = rel.get("cooccurrence_count", 0)

        if a not in known_names or b not in known_names:
            print(
                f"build-character-graph: skipping edge {a!r}↔{b!r} — entity not in graph",
                file=sys.stderr,
            )
            continue
        if not count or count <= 0:
            print(
                f"build-character-graph: skipping edge {a!r}↔{b!r} — cooccurrence_count={count}",
                file=sys.stderr,
            )
            continue

        g.add_interaction(a, b, {
            "relationship_type": rel.get("relationship_type"),
            "direction": rel.get("direction"),
            "cooccurrence_count": count,
            "chapter_weights": rel.get("chapter_weights", {}),
            "sample_contexts": [c[:500] for c in rel.get("sample_contexts", [])[:3]],
            "evolution": rel.get("evolution", ""),
            "books": [book_slug],
        })

    return g


def main(series_graph_data: dict | None = None) -> None:
    payload = json.load(sys.stdin)
    all_outputs = payload.get("all_stage_outputs", {})
    classification = all_outputs.get("entity-classification", {})

    entities = classification.get("entities", [])
    relationships = classification.get("relationships", [])

    # Derive book slug from additional_context YAML
    ctx = yaml.safe_load(payload.get("additional_context", "")) or {}
    book_slug = ctx.get("book_slug", "unknown")

    # Build delta for this book
    delta = _build_book_graph(entities, relationships, book_slug)

    # Load existing series graph (if provided or from disk)
    if series_graph_data is not None:
        series_graph = CharacterGraph.from_json(series_graph_data)
    else:
        # Try loading from disk via paths
        try:
            yaml_path = ctx.get("yaml_path", "")
            if yaml_path:
                paths = book_paths_from_yaml(yaml_path)
                sgp = paths.series_character_graph
                if sgp.exists():
                    series_graph = CharacterGraph.from_json(json.loads(sgp.read_text()))
                    # Atomic write after merge
                    series_graph.merge_book(delta)
                    tmp = sgp.with_suffix(".json.tmp")
                    try:
                        tmp.write_text(json.dumps(series_graph.to_json(), ensure_ascii=False))
                        tmp.rename(sgp)
                    except Exception:
                        if tmp.exists():
                            tmp.unlink()
                        raise
                    # Write delta
                    paths.book_graph_delta.parent.mkdir(parents=True, exist_ok=True)
                    paths.book_graph_delta.write_text(
                        json.dumps(delta.to_json(), ensure_ascii=False)
                    )
                    json.dump({"graph": series_graph.to_json(), "delta": delta.to_json()}, sys.stdout, ensure_ascii=False)
                    return
                else:
                    series_graph = CharacterGraph()
            else:
                series_graph = CharacterGraph()
        except Exception as e:
            print(f"build-character-graph: could not load series graph — {e}", file=sys.stderr)
            series_graph = CharacterGraph()

    series_graph.merge_book(delta)
    json.dump(
        {"graph": series_graph.to_json(), "delta": delta.to_json()},
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
