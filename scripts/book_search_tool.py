#!/usr/bin/env python3
"""Studio tool executor for book-search-search_book (STU-753).

Shelled out to by `.studio/tools/book-search.tool.yaml`, one process per agent
tool call: argv in, one JSON object on stdout. Always exits 0 — a search tool
has no failure the caller should retry blind on; "book_dir doesn't resolve" is
itself a result the agent reads in the reply and can correct on its next call.

Input:  --book-dir <str> --query <str>
Output: {"results": [{"chapter_id", "text"}], "count"} or {"error": str}
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from wiki_creator.book_search import search_chapters
from wiki_creator.studio_io import PROJECT_ROOT

# Mirrors the two corpus roots' shape (STU-623):
# <root>/<author>/<series>/processing_output/<slug>
_BOOK_DIR_RE = re.compile(
    r"(?:^|/)(?:library|public_domain)/[^/]+/[^/]+/processing_output/[^/]+/?$"
)


def resolve_book_dir(book_dir: str, *, root: Path = PROJECT_ROOT) -> Path | None:
    """The processing dir ``book_dir`` names under ``root``, or None when it is
    not one of this repo's own book directories.

    Confines the tool to a book's own artifacts. `book_dir` is an
    agent-supplied argument (the pre-stage hands it the real value, but nothing
    stops the agent from sending something else) — without this gate a wrong or
    crafted value would read any file under the repo the shell process can see.
    """
    if not _BOOK_DIR_RE.search(str(book_dir or "")):
        return None
    resolved = (root / book_dir).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def build_response(book_dir_arg: str, query: str, *, root: Path = PROJECT_ROOT) -> dict:
    """The tool's JSON reply for one ``book-search-search_book`` call."""
    book_dir = resolve_book_dir(book_dir_arg, root=root)
    if book_dir is None:
        return {"error": f"not a book processing directory: {book_dir_arg!r}"}

    try:
        chapters = json.loads((book_dir / "chapters.json").read_text(encoding="utf-8")).get(
            "chapters", {}
        )
    except (OSError, ValueError):
        return {"error": f"chapters.json not found or unreadable in {book_dir_arg}"}

    results = search_chapters(chapters if isinstance(chapters, dict) else {}, query)
    return {"results": results, "count": len(results)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book-dir", required=True)
    parser.add_argument("--query", required=True)
    args = parser.parse_args()
    print(json.dumps(build_response(args.book_dir, args.query), ensure_ascii=False))


if __name__ == "__main__":
    main()
