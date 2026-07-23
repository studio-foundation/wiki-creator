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
    page_from_map_result,
    wiki_pages_map_item,
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
from wiki_creator.register import register_clause
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


def build_synopsis_item(
    events: list[dict], *, book_title: str, book_cfg: dict, language: str
) -> tuple[dict, dict, list[str]]:
    """The pre-LLM half of the synopsis page: the wiki-page-item input, the
    synthetic entity, and the forbidden-name list. Shared by the `--book`
    subprocess path and the pre stage that builds the map item (STU-621)."""
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
    prompt = build_synopsis_prompt(
        selected, book_title, forbidden_names, register=register_clause(book_cfg)
    )
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
    return item_input, _synopsis_entity(), forbidden_names


def finalize_synopsis(result: dict, *, book_title: str, forbidden_names: list[str]) -> dict:
    """The post-LLM half: turn one wiki-page-item result into the synopsis page.

    A generation error stubs the page; a forbidden name that survived the
    child's generation-validation loop rejects it (`_spoiler_rejected`).
    """
    if result.get("error"):
        print(f"[synopsis] generation failed: {result['error']}", file=sys.stderr)
        return _stub_page(failed=True)
    if forbidden_names and _check_forbidden_names(result, forbidden_names):
        hits = _check_forbidden_names(result, forbidden_names)
        print(f"[synopsis] spoiler persists ({', '.join(hits)}), rejecting", file=sys.stderr)
        page = _stub_page(failed=True)
        page["_spoiler_rejected"] = True
        return page
    return _finalize_page(result, book_title)


def generate_synopsis_page(
    events: list[dict],
    *,
    book_title: str,
    book_cfg: dict,
    language: str,
    timeout: int = 120,
    dry_run: bool = False,
) -> dict:
    """One synopsis page from the events, via the wiki-page-item pipeline
    (`--book` path: one nested `studio run` subprocess with a host-level
    forbidden-name re-roll)."""
    if dry_run:
        return _stub_page()

    item_input, entity, forbidden_names = build_synopsis_item(
        events, book_title=book_title, book_cfg=book_cfg, language=language
    )
    result = _execute_wiki_page_item(item_input, entity, timeout)
    if not result.get("error") and forbidden_names and _check_forbidden_names(result, forbidden_names):
        print("[synopsis] spoiler detected, retrying…", file=sys.stderr)
        result = _execute_wiki_page_item(item_input, entity, timeout)
    return finalize_synopsis(result, book_title=book_title, forbidden_names=forbidden_names)


def _write_synopsis_page(page: dict, processing_dir: Path) -> None:
    out_path = processing_dir / "book_synopsis.json"
    out_path.write_text(
        json.dumps({"page": page}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    status = "failed stub" if page.get("_failed") else "page"
    print(f"[synopsis] wrote {status} to {out_path}", file=sys.stderr)


def run_for_processing(
    processing_dir: Path | str,
    *,
    book_cfg: dict,
    language: str,
    timeout: int = 120,
    dry_run: bool = False,
) -> dict | None:
    """Build book_synopsis.json from artifacts in ``processing_dir`` (`--book`
    path). Returns the page, or None when there is nothing to summarize."""
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
    _write_synopsis_page(page, processing_dir)
    return page


VERDICT_STAGE = "book-synopsis-verdict"

_AGENTS_DIR = Path(__file__).resolve().parents[1] / ".studio" / "agents"


def synopsis_prompt_fingerprint() -> str:
    """Busts the map resume cache on a wiki-page-item prompt edit (STU-560). The
    rendered synopsis prompt already travels in the item input, so this only
    guards the agent yaml."""
    return studio_io.prompt_fingerprint(
        [_AGENTS_DIR / "wiki-page-item.agent.yaml", _AGENTS_DIR / "wiki-page-validator.agent.yaml"],
        {},
    )


def _map_output_from_payload(payload: dict) -> dict | None:
    verdict = payload.get("all_stage_outputs", {}).get(VERDICT_STAGE)
    if verdict is None:
        verdict = payload.get("previous_outputs", {}).get(VERDICT_STAGE)
    return verdict if isinstance(verdict, dict) else None


def _result_at_index(map_output: dict | None, index: int) -> dict | None:
    if not isinstance(map_output, dict):
        return None
    for result in map_output.get("results") or []:
        if isinstance(result, dict) and result.get("index") == index:
            return result
    return None


def run_post(payload: dict, *, book_cfg: dict, language: str) -> dict:
    """Studio post stage (STU-621): finalize the synopsis from the `wiki-pages`
    call's map output. Emits `{skipped}` / `{failed}`."""
    paths = studio_io.paths_from_payload(payload)
    events = read_events(paths.processing)
    if not events:
        reason = "events.json not found" if events is None else "events.json has no events"
        print(f"[synopsis] {reason} — skipping synopsis", file=sys.stderr)
        return {"skipped": True}

    book_title = load_book_title(str(paths.processing / "epub_data.json"))
    _item_input, entity, forbidden_names = build_synopsis_item(
        events, book_title=book_title, book_cfg=book_cfg, language=language
    )
    result = page_from_map_result(
        _result_at_index(_map_output_from_payload(payload), 0), entity, language
    )
    page = finalize_synopsis(result, book_title=book_title, forbidden_names=forbidden_names)
    _write_synopsis_page(page, paths.processing)
    return {"failed": bool(page.get("_failed"))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the book synopsis page (SP4)")
    parser.add_argument("--book", help="Path to book YAML config (standalone mode)")
    parser.add_argument("--timeout", type=int, default=120, help="LLM timeout (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM call, output a stub")
    args, _ = parser.parse_known_args()

    if args.book:
        with open(args.book, encoding="utf-8") as f:
            book_cfg = yaml.safe_load(f) or {}
        run_for_processing(
            book_paths_from_yaml(args.book).processing,
            book_cfg=book_cfg,
            language=book_language(book_cfg),
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
        return

    # Studio post stage: the `call: book-synopsis-verdict` stage already ran the
    # wiki-pages map; finalize its output.
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    studio_io.write_output(run_post(payload, book_cfg=book_cfg, language=book_language(book_cfg)))


if __name__ == "__main__":
    main()
