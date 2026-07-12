#!/usr/bin/env python3
"""
Stage: wiki-generation (script executor, no LLM)

Loads pre-generated wiki pages from <series_dir>/processing_output/wiki_pages.json.
Run scripts/generate_wiki_pages.py first to generate the pages.

Input (Studio stdin): consumed and ignored
Output (stdout): {"pages": [...]}
"""

import json
import os
import sys
from pathlib import Path

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wiki_creator import studio_io


def _filter_failed_pages(pages: list[dict]) -> list[dict]:
    """Exclude pages that failed generation before they enter the export pipeline."""
    exportable = [p for p in pages if not p.get("_failed")]
    skipped = len(pages) - len(exportable)
    if skipped:
        failed_titles = [p.get("title", "?") for p in pages if p.get("_failed")]
        print(
            f"[load-wiki-pages] Skipping {skipped} _failed page(s): {', '.join(failed_titles)}",
            file=sys.stderr,
        )
    return exportable


def main() -> None:
    payload = studio_io.read_payload()  # consume stdin (Studio requires it)
    paths = studio_io.paths_from_payload(payload)
    output_file = str(paths.processing / "wiki_pages.json")

    if not os.path.exists(output_file):
        print(
            f"[ERROR] {output_file} not found.\n"
            "Run first: python scripts/generate_wiki_pages.py",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(output_file, encoding="utf-8") as f:
        data = json.load(f)

    pages = data.get("pages", [])
    pages = _filter_failed_pages(pages)
    print(f"[load-wiki-pages] Loaded {len(pages)} pages from {output_file}", file=sys.stderr)
    json.dump({"pages": pages}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
