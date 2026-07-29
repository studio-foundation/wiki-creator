#!/usr/bin/env python3
"""coverage-report — the coverage/faithfulness harness as a dev tool (STU-723).

Reads a run's already-persisted artifacts from a book's processing dir and emits
``coverage_report.json`` plus a readable stderr summary: three ledgers (chapter
coverage, floating aliases, relationship support) and a drop log. Pure logic, no
LLM, no network — mirrors ``make smoke``/``make golden``.

Never fails the run (project norm: a stage must not fail over a coverage miss);
the *assertions* live in ``tests/test_coverage.py``. Exit code is always 0.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from wiki_creator import coverage, studio_io
from wiki_creator.entity_taxonomy import full_registry_files
from wiki_creator.paths import book_paths_from_yaml


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _load_registries(processing: Path) -> dict[str, dict]:
    """``{source_id: entry}`` merged across every ``*_full.json`` type registry."""
    by_type: dict[str, dict] = {}
    for _etype, filename, json_key in full_registry_files():
        raw = _load_json(processing / filename)
        if raw is not None:
            by_type[json_key] = raw.get(json_key, raw)
    return coverage.merge_registries(by_type)


def _page_chapters_from_batches(wiki_inputs: Path) -> dict[str, list[str]]:
    """Map canonical name -> chapters represented in its page context, read from the
    ``wiki_inputs/batch_*.json`` the writer consumes. Absent → empty (Ledger 1 then
    falls back to the classifier's ``chapters_present`` count)."""
    page_chapters: dict[str, list[str]] = {}
    for batch_file in sorted(wiki_inputs.glob("batch_*.json")):
        raw = _load_json(batch_file)
        if not raw:
            continue
        for entity in raw.get("entities", []):
            name = entity.get("canonical_name", "")
            ctx = entity.get("context_by_chapter") or {}
            if name:
                page_chapters[name] = sorted(ctx.keys())
    return page_chapters


def _paged_titles(processing: Path) -> set[str] | None:
    raw = _load_json(processing / "wiki_pages.json")
    if not raw:
        return None
    titles = {
        p.get("title", "")
        for p in raw.get("pages", [])
        if not p.get("_failed")
    }
    titles.discard("")
    return titles or None


def build_report(processing: Path, wiki_inputs: Path, book_config: dict) -> dict:
    registries = _load_registries(processing)
    classified = _load_json(processing / "entities_classified.json") or {}
    entities = classified.get("entities", [])
    discovered = _load_json(processing / "relationships_discovered.json") or {}
    relationships = discovered.get("relationships", [])
    page_chapters = _page_chapters_from_batches(wiki_inputs) or None
    return coverage.build_coverage_report(
        entities,
        registries,
        relationships,
        page_chapters=page_chapters,
        paged_titles=_paged_titles(processing),
        book_config=book_config,
    )


def _print_summary(report: dict, stream=sys.stderr) -> None:
    s = report["summary"]
    print(
        f"[coverage] paged={s['entities_paged']} "
        f"chapter-flags={s['chapter_coverage_flags']} "
        f"floating-aliases={s['floating_mentions']} "
        f"relation-slots={s['relationship_slots']} "
        f"relation-flags={s['relationship_flags']} "
        f"total-drops={s['total_drops']}",
        file=stream,
    )
    for drop in report["drops"]:
        print(
            f"  DROP {drop['stage']}: {drop['entity']} "
            f"(x{drop['count']}, {drop['reason']})",
            file=stream,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Coverage/faithfulness report")
    parser.add_argument("--book", required=True, help="Path to book YAML config")
    parser.add_argument("--out", help="Report path (default: <processing>/coverage_report.json)")
    args = parser.parse_args()

    with open(args.book, encoding="utf-8") as f:
        book_config = yaml.safe_load(f) or {}
    paths = book_paths_from_yaml(args.book)
    report = build_report(paths.processing, paths.wiki_inputs, book_config)

    out = Path(args.out) if args.out else paths.processing / "coverage_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    _print_summary(report)
    print(f"[coverage] wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
