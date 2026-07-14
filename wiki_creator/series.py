"""Series discovery — enumerate a series' book YAMLs in reading order (STU-487).

Pure logic over the existing library layout
(``library/<author>/<series>/books/NN_*.yaml``, already numbered); no ad-hoc
series manifest. Consumed by run_wiki.py's ``--series`` mode to run the tomes in
order, propagating the accumulated series registry from one tome to the next.
"""
from __future__ import annotations

from pathlib import Path

from wiki_creator.tome_labels import tome_number


def _sort_key(book: Path) -> tuple[float, str]:
    """Order by leading numeric tome prefix ('04.5_...' -> 4.5); books with no
    numeric prefix sort last, then alphabetically by name for stability."""
    number = tome_number(book.stem)
    try:
        return (float(number), book.name)
    except ValueError:
        return (float("inf"), book.name)


def discover_series_books(series_dir: Path | str) -> list[Path]:
    """Book YAMLs under ``<series_dir>/books/`` in reading order.

    Raises FileNotFoundError when the ``books/`` directory is absent or holds no
    YAML."""
    books_dir = Path(series_dir) / "books"
    books = sorted(books_dir.glob("*.yaml"), key=_sort_key)
    if not books:
        raise FileNotFoundError(f"No book YAML found under {books_dir}")
    return books
