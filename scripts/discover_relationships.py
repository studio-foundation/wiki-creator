#!/usr/bin/env python3
"""Pre-step: relationship-discovery — schema-guided relation discovery (STU-556).

One `studio run discover-relationships` per book: the engine fans out one child
run per paragraph-aligned chunk (`map` stage, STU-589), discovers AND types the
interpersonal relations each chunk evidences over the book's PERSON roster. The
per-chunk votes are folded to one book-level typed pair each
(`wiki_creator.relationship_discovery.aggregate`) and written to
`relationships_discovered.json`, which `classify_relationships.py` then reads to
add prose (`evolution`, `key_moments`) and grade confidence.

Per-unit persistence lives in the engine now: the map stage runs with
`resume: true` (STU-605), keyed on each item's input — which carries the prompt
fingerprint, so a prompt or type-vocabulary edit re-runs the chunks instead of
replaying stale votes (STU-560). A failed chunk is never cached and retries on
the next run; completed chunks stay done.

It replaces co-occurrence as the reader-facing relation graph (STU-540 decision:
118 pairs vs 80, 5x less junk, type+direction 20/20 against a human gold on
Eragon). It is a pre-step, not a wiki-resolution stage — resolution is chained by
`make golden`, which stays LLM-free by construction. Co-occurrence
`relationship-extraction` stays in resolution untouched (it still feeds
`build-character-graph`); this only supersedes it for the typed reader graph.

Fail-safe (STU-539 bias): a book with no roster or no chapters writes nothing and
warns — `classify_relationships` then falls back to the co-occurrence graph. A
failed fan-out run also writes nothing, leaving any prior artifact intact
(STU-575's rule: no typed source writes nothing and warns).

Usage:
    python scripts/discover_relationships.py --book library/.../book.yaml
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from wiki_creator import studio_io
from wiki_creator.chapters import is_frontmatter_chapter
from wiki_creator.page_templates import relationship_definitions, relationship_tokens
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry
from wiki_creator.relationship_discovery import (
    aggregate,
    build_roster,
    chunk_chapters,
    votes_from_map_output,
)
from wiki_creator.types import Relationship, RelationshipBundle

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CHUNK_CHARS = 6000
_TIMEOUT_SECONDS = 7200
_AGENT_YAML = PROJECT_ROOT / ".studio" / "agents" / "relationship-discovery.agent.yaml"


def _prompt_fingerprint(type_defs: list[dict]) -> str:
    """Fingerprint the discovery prompt + type vocabulary the votes are made under.

    Travels in every map item's input, so the engine's per-item resume cache
    (keyed on the item input, STU-605) busts when either changes — a prompt edit
    re-runs the chunks instead of replaying stale votes (STU-560). Hashes the
    agent yaml (the system prompt) and the injected type definitions."""
    agent = _AGENT_YAML.read_bytes() if _AGENT_YAML.exists() else b""
    types = json.dumps(type_defs, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(agent + b"\x00" + types).hexdigest()


def _narrative_chapters(epub_data: dict) -> list[dict]:
    """Ordered narrative chapters as {id, title, text}, front matter dropped."""
    out = []
    for chapter in epub_data.get("chapters") or []:
        if is_frontmatter_chapter(chapter):
            continue
        out.append({
            "id": chapter.get("id"),
            "title": chapter.get("title") or chapter.get("id") or "",
            "text": chapter.get("content") or "",
        })
    return out


def _run_discovery_fanout(
    chunks: list[dict], roster_lines: list[str], type_defs: list[dict], prompt_key: str
) -> tuple[dict | None, str | None]:
    """One `studio run` fanning out over all chunks. Returns (map_output, error)."""
    payload = {
        "chunks": [{"title": c["title"], "text": c["text"]} for c in chunks],
        "roster": roster_lines,
        "relationship_types": type_defs,
        "prompt_fingerprint": prompt_key,
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(payload, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name
    cmd = ["studio", "run", "discover-relationships", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        return None, "studio_cli_missing"
    except subprocess.TimeoutExpired:
        return None, "studio_run_timeout"
    finally:
        Path(input_path).unlink(missing_ok=True)
    if result.returncode != 0:
        return None, "studio_run_failed"
    map_output = studio_io.stage_output_from_stdout(result.stdout or "", "discover")
    if map_output is None:
        return None, "studio_run_output_missing"
    return map_output, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Schema-guided relation discovery (STU-556).")
    parser.add_argument("--book", required=True, help="Path to book YAML")
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument(
        "--max-chapters", type=int, default=None,
        help="Discover over only the first N narrative chapters — a cheap prompt "
             "smoke (~15 chunks) that seeds the shared engine cache for a later full run.",
    )
    args = parser.parse_args()

    book_paths = book_paths_from_yaml(args.book)
    epub_data_path = book_paths.processing / "epub_data.json"
    registry_path = book_paths.processing / "registry.json"
    output_path = book_paths.processing / "relationships_discovered.json"

    if not epub_data_path.exists() or not registry_path.exists():
        print(
            f"[discover-relationships] missing {epub_data_path.name} or "
            f"{registry_path.name} — writing nothing, classifier falls back to co-occurrence",
            file=sys.stderr,
        )
        return

    epub_data = json.loads(epub_data_path.read_text(encoding="utf-8"))
    registry = Registry.load(registry_path)
    entities = [
        {"canonical_name": r.canonical_name, "entity_type": r.entity_type, "aliases": r.aliases}
        for r in registry.entities
    ]
    roster_names, alias_to_canonical, roster_lines = build_roster(entities)
    if not roster_names:
        print("[discover-relationships] empty PERSON roster — nothing to discover", file=sys.stderr)
        return

    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}
    type_defs = relationship_definitions(book_config=book_cfg)
    allowed_types = set(relationship_tokens(book_config=book_cfg))

    chapters = _narrative_chapters(epub_data)
    if args.max_chapters is not None:
        chapters = chapters[: args.max_chapters]
    chunks = chunk_chapters(chapters, args.chunk_chars)
    if not chunks:
        print("[discover-relationships] no narrative chapters — nothing to discover", file=sys.stderr)
        return

    print(
        f"[discover-relationships] {len(chunks)} chunks | roster {len(roster_names)} PERSON",
        file=sys.stderr,
    )
    map_output, error = _run_discovery_fanout(
        chunks, roster_lines, type_defs, _prompt_fingerprint(type_defs)
    )
    if error:
        print(
            f"[discover-relationships] WARNING: {error} — writing nothing; "
            "prior artifact (if any) kept, classifier falls back to co-occurrence",
            file=sys.stderr,
        )
        return

    votes, failed = votes_from_map_output(
        chunks, map_output, alias_to_canonical, roster_names, allowed_types
    )
    resumed = map_output.get("resumed", 0) if isinstance(map_output, dict) else 0
    print(
        f"[discover-relationships] {len(chunks)} chunks | {resumed} resumed | "
        f"{len(failed)} failed (will retry next run)",
        file=sys.stderr,
    )
    for chunk_id in failed:
        print(f"  [{chunk_id}] FAILED — not cached, will retry", file=sys.stderr)

    pairs = aggregate(votes, roster_names)
    bundle = RelationshipBundle(
        entities=[{"canonical_name": e["canonical_name"], "type": e["entity_type"]} for e in entities],
        relationships=[Relationship(**p) for p in pairs],
        # STU-610: the artifact records which chunks failed and stayed uncached,
        # so a partial discovery output is distinguishable from full coverage.
        stats={
            "chunks": len(chunks),
            "chunks_covered": len(chunks) - len(failed),
            "chunks_uncached": failed,
            "pairs": len(pairs),
            "roster": len(roster_names),
        },
    )
    studio_io.save_artifact(output_path, bundle, RelationshipBundle)
    print(
        f"[discover-relationships] {len(chunks)} chunks → {len(pairs)} typed pairs → {output_path.name}",
        file=sys.stderr,
    )
    if failed:
        print(
            f"[discover-relationships] WARNING: {len(failed)} of {len(chunks)} chunks "
            f"failed and stayed uncached — the discovery output is partial and the graph "
            f"built from it is missing these chunks (re-run to retry): {', '.join(failed)}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
