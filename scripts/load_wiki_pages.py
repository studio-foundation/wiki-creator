#!/usr/bin/env python3
"""
Stage: wiki-generation (script executor, no LLM)

Loads pre-generated wiki pages from processing_output/wiki_pages.json.
Run scripts/generate_wiki_pages.py first to generate the pages.

Input (Studio stdin): consumed and ignored
Output (stdout): {"pages": [...]}
"""

import json
import os
import sys
from pathlib import Path
import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_epub, BookPaths


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)


def main() -> None:
    payload = json.load(sys.stdin)  # consume stdin (Studio requires it)
    paths = _paths_from_payload(payload)
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
    print(f"[load-wiki-pages] Loaded {len(pages)} pages from {output_file}", file=sys.stderr)
    json.dump({"pages": pages}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
