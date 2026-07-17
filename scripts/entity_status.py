#!/usr/bin/env python3
"""Pre-step: entity-status — is each character alive at the end of this book?

Usage:
    python scripts/entity_status.py --book library/.../book.yaml

Input:  processing_output/<slug>/registry.json
Output: processing_output/<slug>/entity_status.json

Runs before wiki-preparation, which stamps the verdict onto the batch entity so
`generate_wiki_pages.py` can render the `status` infobox slot.

It is a pre-step and not a wiki-resolution stage on purpose. `alias-adjudication`
sits inside resolution because it changes identity — entity-classification reads
its output. This changes no identity; it only decorates the batch entity. And
resolution is chained by `make golden`, which stays LLM-free by construction.

Never fails a run: a book whose verdict cannot be obtained renders `unknown` for
every character, loudly.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from wiki_creator import studio_io
from wiki_creator.entity_status import (
    load_cached_status,
    parse_status_verdict,
    render_roster,
    roster_rows,
    save_status_cache,
)
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_SECONDS = 600


def contexts_by_entity(registry: Registry) -> dict[str, list[dict]]:
    """Per-PERSON context sentences with the chapter each came from.

    The chapter rides along because `select_status_snippets` sorts by it.
    """
    contexts: dict[str, list[dict]] = {}
    for record in registry.entities:
        if record.entity_type != "PERSON":
            continue
        snippets = [
            {"text": mention.context.strip(), "chapter_id": mention.chapter_id}
            for mention in record.mentions
            if mention.context and mention.context.strip()
        ]
        if snippets:
            contexts[record.canonical_name] = snippets
    return contexts


def resolve_status(rows: list[dict], book_title: str, cache_path: Path) -> dict[str, dict]:
    """Verified status per character, from cache or one `studio run`.

    Never raises. Every failure path returns {} — every character then renders
    the slot's declared fallback, `unknown`.
    """
    cached = load_cached_status(cache_path, rows)
    if cached is not None:
        return cached
    # A verdict for another roster must not survive a failure below: every
    # `_give_up` path returns without writing, so a stale artifact from a
    # prior roster (WIKI_MAX_CHAPTERS, an extraction fix) would otherwise be
    # replayed by `wiki_preparation.load_status_verdicts`, which is roster-blind.
    Path(cache_path).unlink(missing_ok=True)

    item_input = {"book_title": book_title, "roster": render_roster(rows)}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "entity-status-item", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        return _give_up("studio_cli_missing", rows)
    except subprocess.TimeoutExpired:
        return _give_up("studio_run_timeout", rows)
    finally:
        Path(input_path).unlink(missing_ok=True)

    if result.returncode != 0:
        return _give_up("studio_run_failed", rows)
    stage_output = studio_io.stage_output_from_stdout(result.stdout or "", "entity-status-item")
    if stage_output is None:
        return _give_up("studio_run_output_missing", rows)

    verdicts = parse_status_verdict(stage_output, rows)
    save_status_cache(cache_path, rows, verdicts)
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-status] WARNING: {error} — all {len(rows)} characters stay `unknown`",
        file=sys.stderr,
    )
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Decide each character's status for this book")
    parser.add_argument("--book", required=True, help="Path to the book YAML")
    args = parser.parse_args()

    book_cfg = yaml.safe_load(Path(args.book).read_text(encoding="utf-8")) or {}
    paths = book_paths_from_yaml(args.book)

    cache_path = paths.processing / "entity_status.json"

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-status] registry.json not found in {paths.processing} — "
            "every character stays `unknown`",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    lang_cfg = load_lang_config(book_language(book_cfg))
    status_markers = list(lang_cfg.get("status_markers", []))
    if not status_markers:
        print(
            "[entity-status] no `status_markers` in this language's cue_words — "
            "selecting the latest snippets only",
            file=sys.stderr,
        )

    contexts = contexts_by_entity(registry)
    persons = [
        {"canonical_name": record.canonical_name, "aliases": record.aliases}
        for record in registry.entities
        if record.entity_type == "PERSON" and record.canonical_name in contexts
    ]
    if not persons:
        print("[entity-status] no PERSON entity with context — nothing to decide", file=sys.stderr)
        Path(cache_path).unlink(missing_ok=True)
        return

    rows = roster_rows(persons, contexts, status_markers)
    verdicts = resolve_status(
        rows,
        book_title=str(book_cfg.get("title") or paths.processing.name),
        cache_path=cache_path,
    )

    decided = {name: v["status"] for name, v in verdicts.items()}
    print(
        f"[entity-status] {len(decided)}/{len(rows)} characters decided "
        f"({sum(1 for s in decided.values() if s == 'deceased')} deceased); "
        f"the rest render `unknown`",
        file=sys.stderr,
    )
    for name, verdict in sorted(verdicts.items()):
        print(f"[entity-status]   {name}: {verdict['status']}", file=sys.stderr)


if __name__ == "__main__":
    main()
