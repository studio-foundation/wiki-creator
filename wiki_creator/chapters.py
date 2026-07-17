"""Shared chapter-level helpers used across pipeline stages."""

from __future__ import annotations

import re
import sys

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


def number_chapters(chapters: list[dict]) -> None:
    """Stamp each narrative chapter with its 1-based position, in place.

    A chapter's number is its position, never digits read out of its own id or
    title: `bookcontent2_0` numbers spine items, `x101.xhtml` numbers nothing,
    and Narnia prints `CHAPTER ONE` (STU-546). A prologue takes number 1.
    """
    position = 0
    for chapter in chapters:
        if is_frontmatter_chapter(chapter):
            chapter.pop("chapter_number", None)
            continue
        position += 1
        chapter["chapter_number"] = position


def chapter_number_index(chapters: list[dict]) -> dict[str, int]:
    """Chapter reference -> its number, for every form the pipeline keys by.

    Ids (`context_by_chapter`, relationship `chapters`) and titles
    (`chapter_summaries` on the books whose summaries are title-keyed) both
    resolve; front matter carries no number and is absent.
    """
    index: dict[str, int] = {}
    for chapter in chapters:
        number = chapter.get("chapter_number")
        if not isinstance(number, int):
            continue
        for key in (chapter.get("id"), chapter.get("title")):
            key = str(key or "").strip()
            if key:
                index.setdefault(key, number)
    return index


def resolve_chapter_number(ref: object, index: dict[str, int]) -> int | None:
    """The chapter `ref` names, or None with a warning when it names none.

    An unresolvable reference is never numbered by whatever digits it happens
    to contain — that is the defect this replaces (STU-550).
    """
    if isinstance(ref, int):
        return ref
    key = str(ref or "").strip()
    number = index.get(key)
    if number is None:
        print(f"chapters: no chapter numbered for reference {key!r}", file=sys.stderr)
    return number
