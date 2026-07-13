"""Shared chapter-level helpers used across pipeline stages."""

from __future__ import annotations

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
