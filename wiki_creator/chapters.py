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


# Chapter IDs (lowercased) matching these substrings are skipped entirely.
# They contain metadata (author, translator, epub-maker) not story entities.
FRONTMATTER_ID_PATTERNS: frozenset[str] = frozenset({
    "titlepage",
    "cover",
    "colophon",
    "copyright",
    "toc",
    "halftitle",
    "dedication",
    "dedicatoria",
    "index",
    "acknowledg",
    "author",
    "autor",
    "about-author",
    "about_the_author",
    "notes",
    "credits",
    "info",
    "sinopsis",
    "remerciement",
    "remerciements",
    "auteur",
    "bio-auteur",
})

FRONTMATTER_TITLE_PATTERNS: frozenset[str] = frozenset({
    "acknowledg",
    "author",
    "autor",
    "about the author",
    "notes",
    "credits",
    "info",
    "sinopsis",
    "dedicatoria",
    "remerciement",
    "remerciements",
    "auteur",
    "biographie de l'auteur",
    "biographie auteur",
})


def is_frontmatter_chapter(chapter: dict) -> bool:
    """Return True if chapter metadata suggests front/back matter, not narrative."""
    chapter_id = str(chapter.get("id", "") or "").lower()
    title = str(chapter.get("title", "") or "").lower()
    return any(p in chapter_id for p in FRONTMATTER_ID_PATTERNS) or any(
        p in title for p in FRONTMATTER_TITLE_PATTERNS
    )
