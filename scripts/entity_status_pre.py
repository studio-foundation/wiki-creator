#!/usr/bin/env python3
"""Pre-step of the entity-status split (STU-457): build the roster input.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits the rendered PERSON roster and whether a verdict is still needed — the
`call: entity-status-verdict` stage that follows runs the LLM only when
`needs_verdict` is true (cache miss). The verdict cache stays keyed on the
roster rows themselves (STU-488), so this stage deciding "no call needed" is
exactly the old in-script cache hit. On a cache miss the stale cache is
unlinked here (the defensive pre-call unlink, STU-551): a failed call must not
leave a verdict made for a different roster on disk.

Input:  { "additional_context": "<book yaml>" }
Output: { "book_title", "roster", "needs_verdict" }
"""

import json
import sys
from pathlib import Path

import yaml

from scripts.entity_status import contexts_by_entity
from wiki_creator import studio_io
from wiki_creator.entity_status import load_cached_status, render_roster, roster_rows
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.registry import Registry


def _emit(book_title: str = "", roster: str = "", needs_verdict: bool = False) -> None:
    json.dump(
        {"book_title": book_title, "roster": roster, "needs_verdict": needs_verdict},
        sys.stdout,
        ensure_ascii=False,
    )


def main() -> None:
    payload = studio_io.read_payload()
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    paths = studio_io.paths_from_payload(payload)
    cache_path = paths.processing / "entity_status.json"

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-status] registry.json not found in {paths.processing} — "
            "every character stays `unknown`",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        _emit()
        return

    lang_cfg = load_lang_config(book_language(ctx))
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
        _emit()
        return

    rows = roster_rows(persons, contexts, status_markers)
    needs_verdict = load_cached_status(cache_path, rows) is None
    if needs_verdict:
        Path(cache_path).unlink(missing_ok=True)

    _emit(
        book_title=str(ctx.get("title") or paths.processing.name),
        roster=render_roster(rows),
        needs_verdict=needs_verdict,
    )


if __name__ == "__main__":
    main()
