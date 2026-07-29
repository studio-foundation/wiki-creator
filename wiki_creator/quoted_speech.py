"""Offstage names: named only inside another character's speech (STU-716).

A name that never occurs outside quotation marks is a name the characters talk
about, not a presence on the page — a schoolmaster's nickname in a joke, a
housemaid nobody meets. Read from the chapter text rather than from extracted
mentions, so a name the extractor missed in narration still counts as onstage.
"""

import re
from collections.abc import Iterable, Mapping

_PAIRED_QUOTES = {
    "“": "”",
    "«": "»",
    "„": "“",
}
_SYMMETRIC_QUOTE = '"'


def quoted_spans(text: str) -> list[tuple[int, int]]:
    """Return the (start, end) character ranges covered by quoted speech.

    An opener runs to its own closer, or to the end of the paragraph when the
    closer is missing — speech continuing across paragraphs re-opens without
    closing, which is typography, not an error. Straight double quotes toggle.
    Dash-introduced dialogue is not detected.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    straight_open: int | None = None
    while i < len(text):
        char = text[i]
        closer = _PAIRED_QUOTES.get(char)
        if closer is not None:
            end = text.find(closer, i + 1)
            para = text.find("\n\n", i + 1)
            if end == -1 or (para != -1 and para < end):
                stop = para if para != -1 else len(text)
            else:
                stop = end + 1
            spans.append((i, stop))
            i = stop
            continue
        if char == _SYMMETRIC_QUOTE:
            if straight_open is None:
                straight_open = i
            else:
                spans.append((straight_open, i + 1))
                straight_open = None
        i += 1
    return spans


def quoted_spans_by_chapter(chapter_texts: Mapping[str, str]) -> dict[str, list[tuple[int, int]]]:
    return {chapter_id: quoted_spans(text) for chapter_id, text in chapter_texts.items()}


def is_inside(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    """True when [start, end) falls within one of the quoted spans."""
    return any(s <= start and end <= e for s, e in spans)


def is_offstage(
    surfaces: Iterable[str],
    chapter_texts: Mapping[str, str],
    spans_by_chapter: Mapping[str, list[tuple[int, int]]],
) -> bool:
    """True when no surface form of a name occurs outside quoted speech.

    Matching is case-sensitive and whole-word: a name is capitalised, and the
    lowercase homograph of a mis-extracted entity ("Will", "Say") is not it.
    """
    pattern = _surface_pattern(surfaces)
    if pattern is None:
        return False
    seen = False
    for chapter_id, text in chapter_texts.items():
        quoted = spans_by_chapter.get(chapter_id, [])
        for match in pattern.finditer(text):
            if not is_inside(quoted, match.start(), match.end()):
                return False
            seen = True
    return seen


def _surface_pattern(surfaces: Iterable[str]) -> "re.Pattern | None":
    alternatives = sorted({s.strip() for s in surfaces if s and s.strip()}, key=len, reverse=True)
    if not alternatives:
        return None
    return re.compile(r"\b(?:%s)\b" % "|".join(re.escape(s) for s in alternatives))
