#!/usr/bin/env python3
"""Standalone SP4 stage (STU-482): generate the book synopsis wiki page.

Projects events.json (SP0 Event Layer) — all events ordered by chapter —
through the wiki-page-item pipeline (anchored writer LLM + validator) into a
single spoiler-safe plot-summary page, written to
<processing>/book_synopsis.json. scripts/assemble_wiki_pages.py appends the page
to the export flow, where it is rendered at the wiki root as Synopsis.wiki.

Runs after scripts/generate_wiki_pages.py (both are wiki-generation
pre-steps in run_wiki.py). Degrades gracefully when events.json is absent
(SP0 not run yet): warns and writes nothing.

Usage:
    python scripts/generate_book_synopsis.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
    python scripts/generate_book_synopsis.py --book <book.yaml> --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


import yaml

from scripts.generate_wiki_pages import (
    _check_forbidden_names,
    _execute_wiki_page_item,
    _references_block,
    load_book_title,
)
from wiki_creator import studio_io
from wiki_creator.lang import book_language
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.synopsis import (
    DEFAULT_MAX_EVENTS_PER_CHAPTER,
    DEFAULT_MAX_TOKENS,
    SYNOPSIS_ENTITY_TYPE,
    SYNOPSIS_IMPORTANCE,
    SYNOPSIS_TITLE,
    build_synopsis_prompt,
    select_events,
)
from wiki_creator.types import EventBundle

_STUB_CONTENT_FAILED = "## Synopsis\n\n*Échec technique de la génération du synopsis.*"
_STUB_CONTENT_DRY = "## Synopsis\n\n*Synopsis non généré (dry-run).*"

# Mirrors _strip_relations_section in generate_wiki_pages.py: the writer is
# told not to author a Références section (it is appended deterministically),
# but the instruction can be ignored — strip it before appending ours.
_REFERENCES_SECTION_RE = re.compile(r"(?m)^## Références\s*\n(?:(?!^##\s).*\n?)*")


def _synopsis_entity() -> dict:
    """Synthetic entity dict — the identity parse_response/make-stub machinery
    and the wiki-page-validator bind the page to."""
    return {
        "canonical_name": SYNOPSIS_TITLE,
        "importance": SYNOPSIS_IMPORTANCE,
        "type": SYNOPSIS_ENTITY_TYPE,
    }


def _stub_page(*, failed: bool = False) -> dict:
    page = {
        "title": SYNOPSIS_TITLE,
        "importance": SYNOPSIS_IMPORTANCE,
        "entity_type": SYNOPSIS_ENTITY_TYPE,
        "infobox_fields": {},
        "content": _STUB_CONTENT_FAILED if failed else _STUB_CONTENT_DRY,
    }
    if failed:
        page["_failed"] = True
    return page


def read_events(processing_dir: Path) -> list[dict] | None:
    """Events from events.json. None → file absent (SP0 not run); [] → file
    present but empty/unreadable."""
    path = Path(processing_dir) / "events.json"
    if not path.exists():
        return None
    try:
        bundle = studio_io.load_artifact(path, EventBundle)
    except json.JSONDecodeError:
        return []
    # dict-only boundary: synopsis.py's select_events/build_synopsis_prompt
    # (pure, unchanged) consume plain event dicts — validated on load above.
    return studio_io.to_dict(bundle.events)


def _finalize_page(result: dict, book_title: str) -> dict:
    """Reduce a wiki-page-item result to the page contract, drop any authored
    Références section, and append the deterministic one."""
    content = str(result.get("content", "") or "")
    content = _REFERENCES_SECTION_RE.sub("", content).rstrip("\n")
    return {
        "title": SYNOPSIS_TITLE,
        "importance": SYNOPSIS_IMPORTANCE,
        "entity_type": SYNOPSIS_ENTITY_TYPE,
        "infobox_fields": {},
        "content": content + "\n\n" + _references_block(book_title),
    }


def generate_synopsis_page(
    events: list[dict],
    *,
    book_title: str,
    book_cfg: dict,
    language: str,
    timeout: int = 120,
    dry_run: bool = False,
) -> dict:
    """One synopsis page from the events, via the wiki-page-item pipeline."""
    if dry_run:
        return _stub_page()

    synopsis_cfg = (book_cfg.get("generation") or {}).get("synopsis") or {}
    try:
        max_per_chapter = int(
            synopsis_cfg.get("max_events_per_chapter", DEFAULT_MAX_EVENTS_PER_CHAPTER)
        )
    except (TypeError, ValueError):
        max_per_chapter = DEFAULT_MAX_EVENTS_PER_CHAPTER
    try:
        max_tokens = int(synopsis_cfg.get("max_tokens", DEFAULT_MAX_TOKENS))
    except (TypeError, ValueError):
        max_tokens = DEFAULT_MAX_TOKENS

    validation_cfg = book_cfg.get("validation", {}) or {}
    forbidden_names = validation_cfg.get("forbidden_names", []) or []

    selected = select_events(events, max_per_chapter)
    prompt = build_synopsis_prompt(selected, book_title, forbidden_names)
    # language / forbidden_names / file_path feed the wiki-page-validator
    # stage inside the wiki-page-item pipeline (same channel as entity pages).
    item_input = {
        "title": SYNOPSIS_TITLE,
        "importance": SYNOPSIS_IMPORTANCE,
        "entity_type": SYNOPSIS_ENTITY_TYPE,
        "max_tokens": max_tokens,
        "language": language,
        "forbidden_names": forbidden_names,
        "file_path": book_cfg.get("file_path", ""),
        "prompt": prompt,
    }
    entity = _synopsis_entity()

    result = _execute_wiki_page_item(item_input, entity, timeout)
    if result.get("error"):
        print(f"[synopsis] generation failed: {result['error']}", file=sys.stderr)
        return _stub_page(failed=True)

    if forbidden_names and _check_forbidden_names(result, forbidden_names):
        print("[synopsis] spoiler detected, retrying…", file=sys.stderr)
        result = _execute_wiki_page_item(item_input, entity, timeout)
        if result.get("error"):
            print(f"[synopsis] retry failed: {result['error']}", file=sys.stderr)
            return _stub_page(failed=True)
        hits = _check_forbidden_names(result, forbidden_names)
        if hits:
            print(f"[synopsis] spoiler persists ({', '.join(hits)}), rejecting", file=sys.stderr)
            page = _stub_page(failed=True)
            page["_spoiler_rejected"] = True
            return page

    return _finalize_page(result, book_title)


def run_for_processing(
    processing_dir: Path | str,
    *,
    book_cfg: dict,
    language: str,
    timeout: int = 120,
    dry_run: bool = False,
) -> dict | None:
    """Build book_synopsis.json from artifacts in ``processing_dir``. Returns
    the page, or None when there is nothing to summarize."""
    processing_dir = Path(processing_dir)
    events = read_events(processing_dir)
    if events is None:
        print(
            "[synopsis] events.json not found — run the Event Layer first "
            "(make run-events, SP0); skipping synopsis",
            file=sys.stderr,
        )
        return None
    if not events:
        print("[synopsis] events.json has no events — skipping synopsis", file=sys.stderr)
        return None

    book_title = load_book_title(str(processing_dir / "epub_data.json"))
    page = generate_synopsis_page(
        events,
        book_title=book_title,
        book_cfg=book_cfg,
        language=language,
        timeout=timeout,
        dry_run=dry_run,
    )
    out_path = processing_dir / "book_synopsis.json"
    out_path.write_text(
        json.dumps({"page": page}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    status = "failed stub" if page.get("_failed") else "page"
    print(f"[synopsis] wrote {status} to {out_path}", file=sys.stderr)
    return page


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the book synopsis page (SP4)")
    parser.add_argument("--book", help="Path to book YAML config (standalone mode)")
    parser.add_argument("--timeout", type=int, default=120, help="LLM timeout (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM call, output a stub")
    args, _ = parser.parse_known_args()

    if args.book:
        with open(args.book, encoding="utf-8") as f:
            book_cfg = yaml.safe_load(f) or {}
        book_paths = book_paths_from_yaml(args.book)
    else:
        # Studio stdin mode (STU-457): a pages-export stage, book yaml in
        # additional_context, artifacts from disk.
        payload = studio_io.read_payload()
        book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
        book_paths = studio_io.paths_from_payload(payload)

    page = run_for_processing(
        book_paths.processing,
        book_cfg=book_cfg,
        language=book_language(book_cfg),
        timeout=args.timeout,
        dry_run=args.dry_run,
    )
    if not args.book:
        studio_io.write_output(
            {"skipped": True} if page is None else {"failed": bool(page.get("_failed"))}
        )


if __name__ == "__main__":
    main()
