#!/usr/bin/env python3
"""Standalone SP3 stage (STU-481): generate one wiki page per major event.

Projects events.json (SP0 Event Layer) — each event of salience >= threshold —
through the wiki-page-item pipeline (anchored writer LLM + validator) into a
dedicated spoiler-safe "Event" page (prose + deterministic infobox), written
to <processing>/event_pages.json. scripts/assemble_wiki_pages.py appends the pages
to the export flow, where each is rendered under output/wiki/events/.

Runs after scripts/generate_wiki_pages.py (both are wiki-generation pre-steps
in run_wiki.py). Degrades gracefully when events.json is absent (SP0 not run
yet): warns and writes nothing.

Usage:
    python scripts/generate_event_pages.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
    python scripts/generate_event_pages.py --book <book.yaml> --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from scripts.generate_book_synopsis import read_events
from wiki_creator import studio_io
from scripts.generate_wiki_pages import (
    _check_forbidden_names,
    _execute_wiki_page_item,
    _references_block,
    load_book_title,
    page_from_map_result,
    wiki_pages_map_item,
)
from wiki_creator.event_pages import (
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_TOKENS,
    DEFAULT_SALIENCE_THRESHOLD,
    EVENT_ENTITY_TYPE,
    EVENT_IMPORTANCE,
    build_event_prompt,
    event_infobox_fields,
    event_title,
    select_events,
)
from wiki_creator.page_templates import (
    chrome_label,
    load_base_template,
    output_language,
    slot_label,
)
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.register import DEFAULT_REGISTER, register_clause


def _event_stub(lang: str, kind: str) -> str:
    """Reader-facing stub body under the localized ``course`` heading (STU-514)."""
    heading = slot_label("course", lang)
    entry = (load_base_template().get("stubs") or {}).get(kind) or {}
    message = entry.get(lang) or entry.get("fr") or ""
    return f"## {heading}\n\n*{message}*"


# Mirrors generate_book_synopsis: the writer is told not to author a references
# section (it is appended deterministically), but the instruction can be
# ignored — strip it before appending ours. Heading follows the output language.
def _references_section_re(lang: str) -> "re.Pattern[str]":
    return re.compile(rf"(?m)^## {re.escape(slot_label('references', lang))}\s*\n(?:(?!^##\s).*\n?)*")


def _event_entity(title: str) -> dict:
    """Synthetic entity dict the parse_response identity machinery and the
    wiki-page-validator bind the page to."""
    return {
        "canonical_name": title,
        "importance": EVENT_IMPORTANCE,
        "type": EVENT_ENTITY_TYPE,
    }


def _base_page(title: str, event: dict, content: str) -> dict:
    return {
        "title": title,
        "importance": EVENT_IMPORTANCE,
        "entity_type": EVENT_ENTITY_TYPE,
        "infobox_fields": {"name": title, **event_infobox_fields(event)},
        "content": content,
    }


def _stub_page(title: str, event: dict, lang: str, *, failed: bool = False) -> dict:
    page = _base_page(
        title,
        event,
        _event_stub(lang, "event_failed" if failed else "event_dry_run"),
    )
    if failed:
        page["_failed"] = True
    return page


def _finalize_page(result: dict, title: str, event: dict, book_title: str, lang: str) -> dict:
    """Reduce a wiki-page-item result to the event-page contract, drop any
    authored references section, append the deterministic one, and attach the
    deterministic infobox."""
    content = str(result.get("content", "") or "")
    content = _references_section_re(lang).sub("", content).rstrip("\n")
    return _base_page(title, event, content + "\n\n" + _references_block(book_title, lang))


def build_event_item(
    event: dict,
    title: str,
    *,
    book_title: str,
    forbidden_names: list[str],
    max_tokens: int,
    language: str,
    file_path: str,
    all_events: list[dict] | None = None,
    register: str = DEFAULT_REGISTER,
) -> tuple[dict, dict]:
    """The pre-LLM half of an event page: the wiki-page-item input + entity.
    Shared by the `--book` subprocess path and the pre stage (STU-621)."""
    prompt = build_event_prompt(
        event, title, book_title, forbidden_names, all_events, lang=language, register=register
    )
    item_input = {
        "title": title,
        "importance": EVENT_IMPORTANCE,
        "entity_type": EVENT_ENTITY_TYPE,
        "max_tokens": max_tokens,
        "language": language,
        "forbidden_names": forbidden_names,
        "file_path": file_path,
        "prompt": prompt,
    }
    return item_input, _event_entity(title)


def finalize_event(
    result: dict, title: str, event: dict, *, book_title: str, language: str, forbidden_names: list[str]
) -> dict:
    """The post-LLM half: one wiki-page-item result into the event page. A
    forbidden name that survived the child's generation-validation loop rejects
    the page (`_spoiler_rejected`)."""
    if result.get("error"):
        print(f"[event-pages] '{title}' generation failed: {result['error']}", file=sys.stderr)
        return _stub_page(title, event, language, failed=True)
    if forbidden_names and _check_forbidden_names(result, forbidden_names):
        hits = _check_forbidden_names(result, forbidden_names)
        print(f"[event-pages] '{title}' spoiler persists ({', '.join(hits)}), rejecting", file=sys.stderr)
        page = _stub_page(title, event, language, failed=True)
        page["_spoiler_rejected"] = True
        return page
    return _finalize_page(result, title, event, book_title, language)


def generate_event_page(
    event: dict,
    title: str,
    *,
    book_title: str,
    forbidden_names: list[str],
    max_tokens: int,
    language: str,
    file_path: str,
    all_events: list[dict] | None = None,
    timeout: int = 120,
    dry_run: bool = False,
    register: str = DEFAULT_REGISTER,
) -> dict:
    """One event page via the wiki-page-item pipeline (`--book` path: one nested
    `studio run` subprocess with a host-level forbidden-name re-roll). ``language``
    is the wiki's output language, driving prose, headings and stubs (STU-514)."""
    if dry_run:
        return _stub_page(title, event, language)

    item_input, entity = build_event_item(
        event, title, book_title=book_title, forbidden_names=forbidden_names,
        max_tokens=max_tokens, language=language, file_path=file_path, all_events=all_events,
        register=register,
    )
    result = _execute_wiki_page_item(item_input, entity, timeout)
    if not result.get("error") and forbidden_names and _check_forbidden_names(result, forbidden_names):
        print(f"[event-pages] '{title}' spoiler detected, retrying…", file=sys.stderr)
        result = _execute_wiki_page_item(item_input, entity, timeout)
    return finalize_event(
        result, title, event, book_title=book_title, language=language, forbidden_names=forbidden_names
    )


def _event_pages_config(book_cfg: dict) -> tuple[float, int, int]:
    """(salience_threshold, max_pages, max_tokens) from book YAML, with defaults."""
    cfg = (book_cfg.get("generation") or {}).get("event_pages") or {}

    def _num(key, default, cast):
        try:
            return cast(cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    return (
        _num("salience_threshold", DEFAULT_SALIENCE_THRESHOLD, float),
        _num("max_pages", DEFAULT_MAX_PAGES, int),
        _num("max_tokens", DEFAULT_MAX_TOKENS, int),
    )


def plan_event_pages(
    processing_dir: Path, *, book_cfg: dict, language: str
) -> tuple[list[tuple[dict, str]], dict] | None:
    """The deterministic selection + unique titling, shared by pre and post so
    both derive the same ordered `(event, title)` list (STU-621). Returns
    `(planned, meta)`, or None when there is nothing to generate."""
    events = read_events(processing_dir)
    if events is None:
        print(
            "[event-pages] events.json not found — run the Event Layer first "
            "(make run-events, SP0); skipping event pages",
            file=sys.stderr,
        )
        return None

    threshold, max_pages, max_tokens = _event_pages_config(book_cfg)
    selected = select_events(events, threshold, max_pages)
    if not selected:
        print(
            f"[event-pages] no event at salience >= {threshold} — skipping event pages",
            file=sys.stderr,
        )
        return None

    planned: list[tuple[dict, str]] = []
    seen_titles: set[str] = set()
    for event in selected:
        base = event_title(event)
        if not base:
            continue
        title = base  # keep filenames/wikilinks unique
        if title in seen_titles:
            chapter_tag = chrome_label("chapter_tag", language).format(chapter=event.get("chapter", "?"))
            title = f"{base} ({chapter_tag})"
            suffix = 2
            while title in seen_titles:
                title = f"{base} ({chapter_tag}, #{suffix})"
                suffix += 1
        seen_titles.add(title)
        planned.append((event, title))

    validation_cfg = book_cfg.get("validation", {}) or {}
    meta = {
        "book_title": load_book_title(str(processing_dir / "epub_data.json")),
        "forbidden_names": validation_cfg.get("forbidden_names", []) or [],
        "max_tokens": max_tokens,
        "file_path": book_cfg.get("file_path", ""),
        "all_events": events,
        "register": register_clause(book_cfg),
    }
    return planned, meta


def _write_event_pages(pages: list[dict], processing_dir: Path) -> None:
    out_path = processing_dir / "event_pages.json"
    out_path.write_text(
        json.dumps({"pages": pages}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    failed = sum(1 for p in pages if p.get("_failed"))
    print(
        f"[event-pages] wrote {len(pages)} page(s) ({failed} failed) to {out_path}",
        file=sys.stderr,
    )


def run_for_processing(
    processing_dir: Path | str,
    *,
    book_cfg: dict,
    language: str,
    timeout: int = 120,
    dry_run: bool = False,
) -> list[dict] | None:
    """Build event_pages.json from events.json (`--book` path). Returns the
    pages, or None when there is nothing to generate."""
    processing_dir = Path(processing_dir)
    plan = plan_event_pages(processing_dir, book_cfg=book_cfg, language=language)
    if plan is None:
        return None
    planned, meta = plan

    pages: list[dict] = []
    for event, title in planned:
        print(f"[event-pages] generating '{title}' (salience {event.get('salience')})", file=sys.stderr)
        pages.append(
            generate_event_page(
                event, title,
                book_title=meta["book_title"],
                forbidden_names=meta["forbidden_names"],
                max_tokens=meta["max_tokens"],
                language=language,
                file_path=meta["file_path"],
                all_events=meta["all_events"],
                timeout=timeout,
                dry_run=dry_run,
                register=meta["register"],
            )
        )
    _write_event_pages(pages, processing_dir)
    return pages


VERDICT_STAGE = "event-pages-verdict"

_AGENTS_DIR = Path(__file__).resolve().parents[1] / ".studio" / "agents"


def event_pages_prompt_fingerprint() -> str:
    """Busts the map resume cache on a wiki-page-item prompt edit (STU-560); the
    rendered per-event prompt already travels in each item input."""
    return studio_io.prompt_fingerprint(
        [_AGENTS_DIR / "wiki-page-item.agent.yaml", _AGENTS_DIR / "wiki-page-validator.agent.yaml"],
        {},
    )


def _map_output_from_payload(payload: dict) -> dict | None:
    verdict = payload.get("all_stage_outputs", {}).get(VERDICT_STAGE)
    if verdict is None:
        verdict = payload.get("previous_outputs", {}).get(VERDICT_STAGE)
    return verdict if isinstance(verdict, dict) else None


def _results_by_index(map_output: dict | None) -> dict[int, dict]:
    out: dict[int, dict] = {}
    if not isinstance(map_output, dict):
        return out
    for result in map_output.get("results") or []:
        if isinstance(result, dict) and isinstance(result.get("index"), int):
            out[result["index"]] = result
    return out


def run_post(payload: dict, *, book_cfg: dict, language: str) -> dict:
    """Studio post stage (STU-621): finalize the event pages from the
    `wiki-pages` call's map output. Emits `{skipped}` / `{pages, failed}`."""
    paths = studio_io.paths_from_payload(payload)
    plan = plan_event_pages(paths.processing, book_cfg=book_cfg, language=language)
    if plan is None:
        return {"skipped": True}
    planned, meta = plan

    results = _results_by_index(_map_output_from_payload(payload))
    pages: list[dict] = []
    for i, (event, title) in enumerate(planned):
        result = page_from_map_result(results.get(i), _event_entity(title), language)
        pages.append(
            finalize_event(
                result, title, event,
                book_title=meta["book_title"], language=language,
                forbidden_names=meta["forbidden_names"],
            )
        )
    _write_event_pages(pages, paths.processing)
    return {"pages": len(pages), "failed": sum(1 for p in pages if p.get("_failed"))}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate per-event wiki pages (SP3)")
    parser.add_argument("--book", help="Path to book YAML config (standalone mode)")
    parser.add_argument("--timeout", type=int, default=120, help="LLM timeout (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Skip LLM calls, output stubs")
    args, _ = parser.parse_known_args()

    if args.book:
        with open(args.book, encoding="utf-8") as f:
            book_cfg = yaml.safe_load(f) or {}
        run_for_processing(
            book_paths_from_yaml(args.book).processing,
            book_cfg=book_cfg,
            language=output_language(book_cfg),
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
        return

    # Studio post stage: the `call: event-pages-verdict` stage already ran the
    # wiki-pages map; finalize its output.
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    studio_io.write_output(run_post(payload, book_cfg=book_cfg, language=output_language(book_cfg)))


if __name__ == "__main__":
    main()
