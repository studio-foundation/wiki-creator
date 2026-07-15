"""Shared chapter-level helpers used across pipeline stages."""

from __future__ import annotations

import re

_DIGITS_RE = re.compile(r"\d+")


def chapter_number(key: object) -> int | None:
    """Normalize any chapter reference to its integer index.

    Handles every key form the pipeline emits: ints, epub keys (``C25.xhtml``),
    mention keys (``chapter_0``), relationship keys (``ch01``), and labels
    (``Chapter 25``, ``Ch12: …``). Returns the first digit run, or ``None`` when
    the reference carries no number (``Prologue``, ``""``).
    """
    if isinstance(key, int):
        return key
    m = _DIGITS_RE.search(str(key or ""))
    return int(m.group()) if m else None


def is_frontmatter_chapter(chapter: dict) -> bool:
    """Return True if the section filter tagged this section as front/back matter.

    The verdict is made once per book in `parse_epub` (see
    `wiki_creator.section_filter`); an untagged chapter is narrative.
    """
    return bool(chapter.get("frontmatter"))
