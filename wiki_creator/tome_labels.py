"""Tome display helpers — book_id slug -> human tome number/label (STU-486).

Pure logic, no I/O. Consumed by generation (infobox appearance line, via
scripts/generate_wiki_pages.py) and export (per-tome fandom categories, via
wiki_creator/export_helpers.py).
"""
from __future__ import annotations

import re

_LEADING_TOME_NUMBER = re.compile(r"^(\d+(?:\.\d+)?)")
_LEADING_ZEROS = re.compile(r"^0+(?=\d)")


def tome_number(book_id: str | None) -> str:
    """Human tome number from a book_id slug (cf. book_paths_from_epub):
    '01-throne-of-glass' -> '1', '04.5_tales-of-alagaesia' -> '4.5'. Falls back
    to the raw slug when it carries no leading numeric token (non-numbered
    series conventions)."""
    if not book_id:
        return ""
    match = _LEADING_TOME_NUMBER.match(str(book_id))
    if not match:
        return str(book_id)
    return _LEADING_ZEROS.sub("", match.group(1))


def appearance_label(books: list[str], *, lang: str = "fr") -> str:
    """Infobox appearance line from an entity's ``books`` provenance
    (EntityRecord.books, in first-appearance order). Empty when ``books`` is
    empty — no known provenance (registry absent or pre-multi-tome artifact),
    degrades to omitting the infobox slot (batch-bound, OPT)."""
    numbers = [tome_number(b) for b in books if b]
    if not numbers:
        return ""
    if lang == "en":
        if len(numbers) == 1:
            return f"Appears in book {numbers[0]}"
        return f"First appears in book {numbers[0]}, last appears in book {numbers[-1]}"
    if len(numbers) == 1:
        return f"Apparaît au tome {numbers[0]}"
    return f"Apparaît au tome {numbers[0]}, dernière apparition tome {numbers[-1]}"
