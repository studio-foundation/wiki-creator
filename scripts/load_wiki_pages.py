#!/usr/bin/env python3
"""
Stage: wiki-generation (script executor, no LLM)

Loads pre-generated wiki pages from <series_dir>/processing_output/wiki_pages.json.
Run scripts/generate_wiki_pages.py first to generate the pages.

Input (Studio stdin): consumed and ignored
Output (stdout): {"pages": [...]}
"""

import json
import sys
from pathlib import Path

from wiki_creator import studio_io
from wiki_creator.types import WikiPage


def _load_synopsis_page(processing_dir) -> dict | None:
    """Book synopsis page from book_synopsis.json (SP4, STU-482), or None when
    the artifact is absent, unreadable, or the generation failed."""
    path = Path(processing_dir) / "book_synopsis.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"[load-wiki-pages] Could not read {path} — skipping synopsis", file=sys.stderr)
        return None
    page = data.get("page") if isinstance(data, dict) else None
    if not isinstance(page, dict):
        return None
    if page.get("_failed"):
        print("[load-wiki-pages] Skipping _failed synopsis page", file=sys.stderr)
        return None
    return page


def _read_pages(path: Path) -> list[WikiPage]:
    """Load wiki_pages.json's `pages` array, validated against WikiPage."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return studio_io.from_dict(list[WikiPage], raw.get("pages", []))


def _load_event_pages(processing_dir) -> list[dict]:
    """Per-event wiki pages from event_pages.json (SP3, STU-481), minus any that
    failed generation. Empty list when the artifact is absent or unreadable."""
    path = Path(processing_dir) / "event_pages.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"[load-wiki-pages] Could not read {path} — skipping event pages", file=sys.stderr)
        return []
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list):
        return []
    return [p for p in pages if isinstance(p, dict) and not p.get("_failed")]


def _filter_failed_pages(pages: list[WikiPage]) -> list[WikiPage]:
    """Exclude pages that failed generation before they enter the export pipeline."""
    exportable = [p for p in pages if not p._failed]
    skipped = len(pages) - len(exportable)
    if skipped:
        failed_titles = [p.title for p in pages if p._failed]
        print(
            f"[load-wiki-pages] Skipping {skipped} _failed page(s): {', '.join(failed_titles)}",
            file=sys.stderr,
        )
    return exportable


def main() -> None:
    payload = studio_io.read_payload()  # consume stdin (Studio requires it)
    paths = studio_io.paths_from_payload(payload)
    output_file = paths.processing / "wiki_pages.json"

    if not output_file.exists():
        print(
            f"[ERROR] {output_file} not found.\n"
            "Run first: python scripts/generate_wiki_pages.py",
            file=sys.stderr,
        )
        sys.exit(1)

    pages = _filter_failed_pages(_read_pages(output_file))
    # dict-only boundary: the synopsis page comes from a separate artifact
    # (book_synopsis.json, not wired to studio_io in this task) as a plain
    # dict, and the stdout payload mixes it in with the validated pages.
    output_pages = [studio_io.to_dict(p) for p in pages]
    synopsis = _load_synopsis_page(paths.processing)
    if synopsis is not None:
        output_pages.append(synopsis)
        print(
            f"[load-wiki-pages] Added synopsis page '{synopsis.get('title', '')}'",
            file=sys.stderr,
        )
    event_pages = _load_event_pages(paths.processing)
    if event_pages:
        output_pages.extend(event_pages)
        print(f"[load-wiki-pages] Added {len(event_pages)} event page(s)", file=sys.stderr)
    print(f"[load-wiki-pages] Loaded {len(output_pages)} pages from {output_file}", file=sys.stderr)
    json.dump({"pages": output_pages}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
