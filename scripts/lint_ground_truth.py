#!/usr/bin/env python3
"""Mechanical, LLM-free lint of a ground-truth corpus against the book's own
text (the add-book skill's step 6, committed and testable).

    python scripts/lint_ground_truth.py --book <book.yaml> [--gt-dir DIR]

Resolves the corpus from the book (tome subdirectory when it exists, flat
otherwise) and the text from processing_output/<slug>/epub_data.json — run
scripts/parse_epub.py first if it is missing. Exits non-zero on any FAIL; every
WARN is fixed or justified in the corpus README. Facts are the part no linter
can check — spot-check known_facts_book1 by grepping the text.

Pure logic in wiki_creator/ground_truth.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from wiki_creator.ground_truth import lint_corpus, load_entries, resolve_gt_dir
from wiki_creator.paths import book_paths_from_yaml


def main() -> int:
    parser = argparse.ArgumentParser(description="Ground-truth corpus lint")
    parser.add_argument("--book", required=True, help="Path to a book YAML config")
    parser.add_argument("--gt-dir", help="Corpus directory (default: resolved from the book)")
    args = parser.parse_args()

    paths = book_paths_from_yaml(args.book)
    slug = paths.processing.name
    gt_dir = Path(args.gt_dir) if args.gt_dir else resolve_gt_dir(paths.series_dir, slug)
    if gt_dir is None or not gt_dir.is_dir():
        print(f"No ground-truth corpus under {paths.series_dir}/books/ground-truth", file=sys.stderr)
        return 2

    epub_data = paths.processing / "epub_data.json"
    if not epub_data.exists():
        print(f"{epub_data} missing — run scripts/parse_epub.py first", file=sys.stderr)
        return 2
    chapters = json.loads(epub_data.read_text())["chapters"]
    text = "\n".join(c["content"] for c in chapters)

    entries, _ = load_entries(gt_dir)
    findings = lint_corpus(entries, text)
    for level, msg in findings:
        print(f"{level:5} {msg}")
    fails = sum(1 for level, _ in findings if level == "FAIL")
    print(f"\n{len(entries)} entities, {fails} failures, "
          f"{sum(1 for level, _ in findings if level == 'WARN')} warnings")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
