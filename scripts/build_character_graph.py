"""build_character_graph.py — pre-step: build the series character graph (STU-575).

Reads the typed relation graph from disk — `relationships_classified.json`, falling
back to `relationships_discovered.json` — and the entity set from
`entities_classified.json`.

It used to be a `wiki-resolution` stage reading `entity-classification`'s
relationships, which are the co-occurrence graph: typing happens in the
`discover-relationships`/`classify-relationships` pre-steps of `wiki-preparation`,
one pipeline later, so every edge it ever built carried `relationship_type: null`
(78/78 on Narnia). `wiki_preparation` then read that graph back and
`indirect_relationships` dropped every path for an untyped hop (STU-528), returning
`[]` on every book. Moving the build after typing is what makes the typed edges
STU-556 discovers reach the reader.

Writes:
  - series_character_graph (atomic: write-to-temp + rename)
  - book_graph_delta
"""
from __future__ import annotations

import argparse
import json
import sys

from wiki_creator import studio_io
from wiki_creator.character_graph import CharacterGraph
from wiki_creator.contract_validators import character_graph_errors
from wiki_creator.paths import book_paths_from_yaml

# Classified first — it is the discovered set plus prose (`evolution`) and graded
# confidence; discovered alone is the same typed pairs without them.
_RELATION_SOURCES = ("relationships_classified.json", "relationships_discovered.json")


def build_book_graph(entities: list[dict], relationships: list[dict], book_slug: str) -> CharacterGraph:
    """Build a CharacterGraph for one book."""
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


def _persons(entities: list[dict], key: str) -> set[str]:
    return {e["canonical_name"] for e in entities if e.get(key) == "PERSON" and e.get("canonical_name")}


def _load_typed_relationships(processing) -> tuple[dict, str] | None:
    """The typed bundle and the artifact it came from, or None if neither exists."""
    for name in _RELATION_SOURCES:
        path = processing / name
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8")), name
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the series character graph (STU-575).")
    parser.add_argument("--book", help="Path to book YAML (standalone mode)")
    args, _ = parser.parse_known_args()

    if args.book:
        run(book_paths_from_yaml(args.book))
        return

    # Studio stdin mode (STU-457): a wiki-preparation stage, artifacts from disk.
    payload = studio_io.read_payload()
    summary = run(studio_io.paths_from_payload(payload))
    studio_io.write_output(summary)


def run(paths) -> dict:
    classified_path = paths.processing / "entities_classified.json"

    # Fail safe, loudly: no typed source means writing an untyped graph, which is
    # the state this stage exists to end. Leave the artifacts on disk untouched.
    source = _load_typed_relationships(paths.processing)
    if source is None or not classified_path.exists():
        print(
            f"[build-character-graph] no typed relations "
            f"({' or '.join(_RELATION_SOURCES)}) or no {classified_path.name} — "
            f"writing nothing. Run discover-relationships first.",
            file=sys.stderr,
        )
        return {"skipped": "no_typed_source"}
    bundle, source_name = source

    entities = json.loads(classified_path.read_text(encoding="utf-8")).get("entities", [])

    # STU-602: the bundle records the PERSON roster discovery ran against. A
    # re-resolution that renames or retypes an entity leaves every edge naming the
    # old canonical off-roster, and the per-edge skip below drops them one at a
    # time — on Narnia that read as a 44% gate loss and was diagnosed as two
    # artifacts disagreeing on who is a character. They never disagree; the
    # artifact is simply older than the roster. Refuse it whole.
    discovered_roster = _persons(bundle.get("entities", []), "type")
    drift = discovered_roster - _persons(entities, "type")
    if drift:
        print(
            f"[build-character-graph] {source_name} was discovered against a stale "
            f"PERSON roster — {len(drift)} name(s) no longer in {classified_path.name}: "
            f"{', '.join(sorted(drift))}. Writing nothing; re-run discover-relationships.",
            file=sys.stderr,
        )
        return {"skipped": "stale_roster"}

    delta = build_book_graph(entities, bundle.get("relationships", []), paths.processing.name)

    sgp = paths.series_character_graph
    series_graph = CharacterGraph.from_json(json.loads(sgp.read_text())) if sgp.exists() else CharacterGraph()
    series_graph.merge_book(delta)

    graph_json = series_graph.to_json()
    delta_json = delta.to_json()
    # The stage no longer runs under its Studio contract, so it checks itself.
    errors = character_graph_errors({"graph": graph_json, "delta": delta_json})
    if errors:
        print("[build-character-graph] invalid graph:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    sgp.parent.mkdir(parents=True, exist_ok=True)
    tmp = sgp.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(graph_json, ensure_ascii=False))
        tmp.rename(sgp)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise

    paths.book_graph_delta.parent.mkdir(parents=True, exist_ok=True)
    paths.book_graph_delta.write_text(json.dumps(delta_json, ensure_ascii=False))

    links = delta_json["links"]
    typed = sum(1 for link in links if link.get("relationship_type"))
    print(
        f"[build-character-graph] {source_name} → {len(delta_json['nodes'])} nodes, "
        f"{len(links)} edges ({typed} typed) → {sgp.name}",
        file=sys.stderr,
    )
    return {"nodes": len(delta_json["nodes"]), "edges": len(links), "typed": typed}


if __name__ == "__main__":
    main()
