#!/usr/bin/env python3
"""Series arc stage (STU-708): generate the series hub's overarching-arc paragraph.

One LLM call per series. Projects every tome's persisted artifacts — its synopsis
(SP4/STU-482), its highest-salience events (SP0), and the assembled series
characters (STU-668) — through the wiki-page-item pipeline into the one generative
piece of the hub (STU-707), written to <series>/series_arc.json.

The result is cached on the inputs that produced it (the rendered prompt plus the
agent-prompt fingerprint), so a re-run replays instead of re-calling.

Usage:
    python scripts/generate_series_arc.py --series library/sarah_j_maas/throne-of-glass
    python scripts/generate_series_arc.py --series <series_dir> --dry-run   # print the prompt, no call
    python scripts/generate_series_arc.py --series <series_dir> --force     # ignore the cache
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from scripts.generate_wiki_pages import _execute_wiki_page_item, load_book_title
from wiki_creator import studio_io
from wiki_creator.page_templates import output_language
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.register import register_clause
from wiki_creator.registry import Registry
from wiki_creator.series import (
    TomeArtifacts,
    build_series_characters,
    discover_series_books,
    load_tome_artifacts,
    series_title,
)
from wiki_creator.series_arc import (
    ARC_ENTITY_TYPE,
    ARC_IMPORTANCE,
    ARC_TITLE,
    CACHE_FILENAME,
    DEFAULT_MAX_TOKENS,
    TomeGrounding,
    arc_cache_key,
    build_arc_prompt,
    clean_arc,
    load_cached_arc,
    save_arc_cache,
    select_tome_events,
)
from wiki_creator.series_hub import main_characters
from wiki_creator.tome_labels import tome_number

_AGENTS_DIR = Path(__file__).resolve().parents[1] / ".studio" / "agents"


def arc_prompt_fingerprint() -> str:
    """Busts the cache on a wiki-page-item prompt edit (STU-560). The rendered arc
    prompt is already part of the cache key, so this only guards the agent yaml."""
    return studio_io.prompt_fingerprint([_AGENTS_DIR / "wiki-page-item.agent.yaml"], {})


def _read_synopsis(processing_dir: Path) -> str:
    """The tome's generated synopsis prose, or "" when it has none (SP4 not run,
    or the generation failed and left a stub)."""
    path = Path(processing_dir) / "book_synopsis.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    page = data.get("page") if isinstance(data, dict) else None
    if not isinstance(page, dict) or page.get("_failed"):
        return ""
    return str(page.get("content") or "")


def load_tome_grounding(book_yaml: Path) -> tuple[TomeGrounding, TomeArtifacts]:
    """One tome's contribution: the grounding block material, and the artifacts
    the series-character assembly needs (read once, used twice)."""
    paths = book_paths_from_yaml(book_yaml)
    book_id = book_yaml.stem
    artifacts = load_tome_artifacts(paths.processing, book_id)
    grounding = TomeGrounding(
        tome_number=tome_number(book_id),
        title=load_book_title(str(paths.processing / "epub_data.json")),
        synopsis=_read_synopsis(paths.processing),
        events=select_tome_events(artifacts.events),
    )
    return grounding, artifacts


@dataclass
class ArcInputs:
    prompt: str
    lang: str
    cache_path: Path


def build_arc_inputs(series_dir: Path | str) -> ArcInputs | None:
    """Everything the call needs, or None when no tome carries material to ground
    an arc on.

    Language and register come from the first tome's config: they are properties
    of the series' published wiki, and every tome of one series declares the same.
    A missing series registry costs the main-character list, never the arc.
    """
    series_dir = Path(series_dir)
    books = discover_series_books(series_dir)
    grounding, artifacts = zip(*(load_tome_grounding(book) for book in books))
    if not any(tome.synopsis or tome.events for tome in grounding):
        return None

    registry = Registry.load_from_processing(series_dir)
    characters = main_characters(build_series_characters(registry, list(artifacts))) if registry else []

    first_cfg = yaml.safe_load(books[0].read_text(encoding="utf-8")) or {}
    lang = output_language(first_cfg)
    prompt = build_arc_prompt(
        list(grounding),
        characters,
        series_title(series_dir),
        lang=lang,
        register=register_clause(first_cfg),
    )
    return ArcInputs(prompt=prompt, lang=lang, cache_path=series_dir / CACHE_FILENAME)


def generate_arc(prompt: str, *, lang: str, timeout: int = 120) -> str | None:
    """One arc paragraph from the prompt, via the wiki-page-item pipeline. None on
    a generation failure — the hub then renders its deterministic frame without an
    arc (STU-707), which is the safe reader-facing default."""
    entity = {
        "canonical_name": ARC_TITLE,
        "importance": ARC_IMPORTANCE,
        "type": ARC_ENTITY_TYPE,
    }
    item_input = {
        "title": ARC_TITLE,
        "importance": ARC_IMPORTANCE,
        "entity_type": ARC_ENTITY_TYPE,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "language": lang,
        "prompt": prompt,
    }
    result = _execute_wiki_page_item(item_input, entity, timeout)
    if result.get("error"):
        print(f"[series-arc] generation failed: {result['error']}", file=sys.stderr)
        return None
    arc = clean_arc(result.get("content", ""))
    if not arc:
        print("[series-arc] generation returned no prose", file=sys.stderr)
        return None
    return arc


def run_for_series(
    series_dir: Path | str,
    *,
    timeout: int = 120,
    dry_run: bool = False,
    force: bool = False,
) -> str | None:
    inputs = build_arc_inputs(series_dir)
    if inputs is None:
        print(
            "[series-arc] no tome carries a synopsis or events — run the tomes first; "
            "skipping arc",
            file=sys.stderr,
        )
        return None

    if dry_run:
        print(inputs.prompt)
        return None

    key = arc_cache_key(inputs.prompt, arc_prompt_fingerprint())
    if not force:
        cached = load_cached_arc(inputs.cache_path, key)
        if cached:
            print(f"[series-arc] cache hit — {inputs.cache_path}", file=sys.stderr)
            return cached

    arc = generate_arc(inputs.prompt, lang=inputs.lang, timeout=timeout)
    if arc is None:
        return None
    save_arc_cache(inputs.cache_path, key, arc)
    print(f"[series-arc] wrote arc to {inputs.cache_path}", file=sys.stderr)
    return arc


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the series hub arc paragraph (STU-708)")
    parser.add_argument("--series", required=True, help="Series directory (library/<author>/<series>)")
    parser.add_argument("--timeout", type=int, default=120, help="LLM timeout (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Print the prompt, skip the LLM call")
    parser.add_argument("--force", action="store_true", help="Ignore the cached arc")
    args = parser.parse_args()

    run_for_series(args.series, timeout=args.timeout, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
