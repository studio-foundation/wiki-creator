#!/usr/bin/env python3
"""Run alias-adjudication over the whole library and collect every verdict.

STU-539 shipped the stage on one book — Throne of Glass, the book it was designed
against, on a 5-chapter cache. This runs the two real pipelines (wiki-extraction,
wiki-resolution) per book, full text, in reading order so each tome seeds from the
series registry the way production does, and copies the resulting
`processing_output/<slug>/alias_adjudication.json` here for scoring.

    PYTHONPATH=../.. python run_books.py [--only <slug> ...]

The pipelines are invoked exactly as `make run-extraction` / `make run-resolution`
do; nothing here reimplements a stage. Two stages call the network (section-filter,
alias-adjudication), one call each per book. A book whose verdict is already in
`verdicts/` is skipped — delete the file to re-run it.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from wiki_creator.series import discover_series_books  # noqa: E402

VERDICTS = Path(__file__).parent / "verdicts"


def library_books() -> list[Path]:
    """Every book YAML in the library, tomes of a series in reading order."""
    series_dirs = sorted({p.parent.parent for p in REPO_ROOT.glob("library/*/*/books/*.yaml")})
    return [book for series in series_dirs for book in discover_series_books(series)]


def verdict_name(book: Path) -> str:
    return f"{book.parent.parent.name}__{book.stem}.json"


def run_pipeline(pipeline: str, book: Path) -> bool:
    result = subprocess.run(
        ["studio", "run", pipeline, "--input-file", str(book.relative_to(REPO_ROOT)), "--live"],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
    )
    return result.returncode == 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", default=None, help="book stems to run")
    args = parser.parse_args()

    VERDICTS.mkdir(exist_ok=True)
    books = library_books()
    if args.only:
        books = [b for b in books if b.stem in args.only]

    for book in books:
        target = VERDICTS / verdict_name(book)
        if target.exists():
            print(f"[skip] {book.stem} — verdict already collected", file=sys.stderr)
            continue
        print(f"\n=== {book.stem}", file=sys.stderr)
        started = time.monotonic()
        if not (run_pipeline("wiki-extraction", book) and run_pipeline("wiki-resolution", book)):
            print(f"[FAIL] {book.stem} — pipeline failed", file=sys.stderr)
            continue
        slug = book.stem
        produced = book.parent.parent / "processing_output" / slug / "alias_adjudication.json"
        if not produced.exists():
            print(f"[FAIL] {book.stem} — no verdict written (stage merged nothing)", file=sys.stderr)
            continue
        shutil.copy(produced, target)
        print(f"[ok] {book.stem} in {time.monotonic() - started:.0f}s", file=sys.stderr)


if __name__ == "__main__":
    main()
