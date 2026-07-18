#!/usr/bin/env python3
"""Pre-step: relationship-discovery — schema-guided relation discovery (STU-556).

One `studio run relationship-discovery-item` per paragraph-aligned chunk. Each call
discovers AND types the interpersonal relations that chunk evidences, over the
book's PERSON roster. The per-chunk votes are folded to one book-level typed pair
each (`wiki_creator.relationship_discovery.aggregate`) and written to
`relationships_discovered.json`, which `classify_relationships.py` then reads to
add prose (`evolution`, `key_moments`) and grade confidence.

It replaces co-occurrence as the reader-facing relation graph (STU-540 decision:
118 pairs vs 80, 5x less junk, type+direction 20/20 against a human gold on
Eragon). It is a pre-step, not a wiki-resolution stage — resolution is chained by
`make golden`, which stays LLM-free by construction. Co-occurrence
`relationship-extraction` stays in resolution untouched (it still feeds
`build-character-graph`); this only supersedes it for the typed reader graph.

Fail-safe (STU-539 bias): a book with no roster or no chapters writes nothing and
warns — `classify_relationships` then falls back to the co-occurrence graph. A
single failed chunk yields no votes and is skipped, never losing the run.

Usage:
    python scripts/discover_relationships.py --book library/.../book.yaml
    python scripts/discover_relationships.py --book library/.../book.yaml --workers 6
"""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
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
    fold_chunk_result,
    load_votes_cache,
    save_votes_cache,
)
from wiki_creator.types import Relationship, RelationshipBundle

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_CHUNK_CHARS = 6000
_TIMEOUT_SECONDS = 120
_AGENT_YAML = PROJECT_ROOT / ".studio" / "agents" / "relationship-discovery.agent.yaml"


def _prompt_fingerprint(type_defs: list[dict]) -> str:
    """Fingerprint the discovery prompt + type vocabulary the votes were made under.

    The votes cache busts when either changes, so a prompt edit re-runs the chunks
    instead of replaying stale votes (STU-560). Hashes the agent yaml (the system
    prompt) and the injected type definitions."""
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


def _run_discovery_chunk(chunk: dict, roster_lines: list[str], type_defs: list[dict]) -> object:
    """One `studio run` for a chunk. Returns the raw ``relations`` list or None."""
    item_input = {
        "title": chunk["title"],
        "passage": chunk["text"],
        "roster": roster_lines,
        "relationship_types": type_defs,
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name
    cmd = ["studio", "run", "relationship-discovery-item", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        print(f"  [{chunk['id']}] FAILED: {type(e).__name__}", file=sys.stderr)
        return None
    finally:
        Path(input_path).unlink(missing_ok=True)
    if result.returncode != 0:
        print(f"  [{chunk['id']}] studio exit {result.returncode}", file=sys.stderr)
        return None
    stage_output = studio_io.stage_output_from_stdout(result.stdout or "", "relationship-discovery")
    if stage_output is None:
        print(f"  [{chunk['id']}] no stage output", file=sys.stderr)
        return None
    return stage_output.get("relations")


def main() -> None:
    parser = argparse.ArgumentParser(description="Schema-guided relation discovery (STU-556).")
    parser.add_argument("--book", required=True, help="Path to book YAML")
    parser.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument(
        "--max-chapters", type=int, default=None,
        help="Discover over only the first N narrative chapters — a cheap prompt "
             "smoke (~15 chunks) that seeds the shared cache for a later full run.",
    )
    args = parser.parse_args()

    book_paths = book_paths_from_yaml(args.book)
    epub_data_path = book_paths.processing / "epub_data.json"
    registry_path = book_paths.processing / "registry.json"
    output_path = book_paths.processing / "relationships_discovered.json"
    votes_path = book_paths.processing / "relationships_discovered_votes.json"

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

    prompt_key = _prompt_fingerprint(type_defs)
    cache = load_votes_cache(votes_path, roster_lines, prompt_key)
    todo = [c for c in chunks if c["id"] not in cache]
    print(
        f"[discover-relationships] {len(chunks)} chunks | {len(cache)} cached | "
        f"{len(todo)} to run | roster {len(roster_names)} PERSON",
        file=sys.stderr,
    )

    done, lock = [0], threading.Lock()

    def run(chunk: dict) -> tuple[str, list[dict]]:
        raw = _run_discovery_chunk(chunk, roster_lines, type_defs)
        kept = fold_chunk_result(raw, alias_to_canonical, roster_names, allowed_types)
        with lock:
            done[0] += 1
            if kept is None:
                # Transient failure — leave the chunk out of the cache so a re-run
                # retries it, instead of poisoning it with an empty vote a later run
                # reads as a genuine 0 (STU-562 shape).
                print(f"  [{done[0]}/{len(todo)}] {chunk['id']}: FAILED — not cached, will retry", file=sys.stderr)
                return chunk["id"], []
            cache[chunk["id"]] = kept
            save_votes_cache(votes_path, roster_lines, prompt_key, cache)
            print(f"  [{done[0]}/{len(todo)}] {chunk['id']}: {len(kept)}", file=sys.stderr)
        return chunk["id"], kept

    if todo:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            list(pool.map(run, todo))

    votes = [{"chapter_id": c["chapter_id"], "relations": cache.get(c["id"], [])} for c in chunks]
    pairs = aggregate(votes, roster_names)

    bundle = RelationshipBundle(
        entities=[{"canonical_name": e["canonical_name"], "type": e["entity_type"]} for e in entities],
        relationships=[Relationship(**p) for p in pairs],
        stats={"chunks": len(chunks), "pairs": len(pairs), "roster": len(roster_names)},
    )
    studio_io.save_artifact(output_path, bundle, RelationshipBundle)
    print(
        f"[discover-relationships] {len(chunks)} chunks → {len(pairs)} typed pairs → {output_path.name}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
