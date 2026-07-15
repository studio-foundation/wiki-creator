#!/usr/bin/env python3
"""Post-generation editorial-stance consolidation pass (STU-508).

Reads the pages generated for a book, scans them for register that contradicts
the declared ``editorial_stance.mode`` (STU-507), and writes an advisory drift
report to ``<processing>/editorial_stance_report.json`` plus a human-readable
summary on stderr.

Advisory only: it never fails the run (INV-08 — inter-page tone is not
contractable per page, so drift is a warning, not a binary contract). A single
deterministic pass over all generated pages, zero LLM calls (Fable frugality).

Runs after the page generators (generate_wiki_pages / _book_synopsis /
_event_pages) as the last wiki-generation pre-step.

Usage:
    python scripts/consolidate_editorial_stance.py --book <book.yaml>
    python scripts/consolidate_editorial_stance.py --book <book.yaml> --sample 40
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from wiki_creator.consolidation import build_report, format_summary, scan_pages
from wiki_creator.editorial_stance import editorial_stance
from wiki_creator.page_templates import output_language
from wiki_creator.paths import book_paths_from_yaml

_REPORT_FILENAME = "editorial_stance_report.json"


def _pages_from(path: Path, key: str) -> list[dict]:
    """Non-failed page dicts under ``data[key]`` (a list, or a single dict for
    the synopsis). Empty when the artifact is absent or unreadable."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"[editorial-consolidation] could not read {path} — skipping", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        return []
    value = data.get(key)
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    return [p for p in value if isinstance(p, dict) and not p.get("_failed")]


def collect_pages(processing_dir: Path) -> list[dict]:
    """Every generated page for the book, across all generator artifacts."""
    pages: list[dict] = []
    pages += _pages_from(processing_dir / "wiki_pages.json", "pages")
    pages += _pages_from(processing_dir / "book_synopsis.json", "page")
    pages += _pages_from(processing_dir / "event_pages.json", "pages")
    pages += _pages_from(processing_dir / "collation_pages.json", "pages")
    return pages


def run_for_processing(
    processing_dir: Path | str, *, book_cfg: dict, sample: int = 0
) -> dict:
    processing_dir = Path(processing_dir)
    stance = editorial_stance(book_cfg)
    lang = output_language(book_cfg)

    pages = collect_pages(processing_dir)
    if sample and sample > 0:
        pages = pages[:sample]

    findings = scan_pages(pages, stance, lang)
    report = build_report(findings, stance, pages_scanned=len(pages))

    out_path = processing_dir / _REPORT_FILENAME
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(format_summary(report), file=sys.stderr)
    print(f"[editorial-consolidation] wrote report to {out_path}", file=sys.stderr)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Editorial-stance consolidation pass (STU-508)")
    parser.add_argument("--book", required=True, help="Path to book YAML config")
    parser.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Cap the number of pages scanned (0 = all; the scan is free, so all by default)",
    )
    args = parser.parse_args()

    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}

    book_paths = book_paths_from_yaml(args.book)
    run_for_processing(book_paths.processing, book_cfg=book_cfg, sample=args.sample)


if __name__ == "__main__":
    main()
