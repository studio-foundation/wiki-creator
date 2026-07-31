"""Full-text search over a book's parsed chapters (STU-753).

The retrieval primitive an agentic point-query verdict searches with, instead
of receiving a pre-selected snippet pack. ``chapters.json`` (written by
``entity_extraction.save_chapters_json``) maps chapter id -> full chapter text;
this is the same artifact `relationship_extraction.py` already reads for
co-occurrence, so no new artifact is introduced.

A query is a literal, case-insensitive phrase — never a regex. The caller is
an LLM tool call: a regex engine let loose on model-shaped input is a
catastrophic-backtracking surface a substring search never opens.
"""

from __future__ import annotations

import json
from pathlib import Path

from wiki_creator.chapters import chapter_number
from wiki_creator.roster import fold_typography

MAX_RESULTS = 8
CONTEXT_CHARS = 300


def load_chapters(processing_dir: Path | str) -> dict[str, str]:
    """This book's ``chapters.json`` as ``{chapter_id: text}``, or ``{}``."""
    try:
        data = json.loads((Path(processing_dir) / "chapters.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    chapters = data.get("chapters") if isinstance(data, dict) else None
    return chapters if isinstance(chapters, dict) else {}


def full_text(chapters: dict[str, str]) -> str:
    """Every chapter's text joined — the grounding surface a free-search verdict's
    quote must appear in (there is no pre-selected snippet pack to check against)."""
    return "\n".join(str(t) for t in (chapters or {}).values())


def search_chapters(
    chapters: dict[str, str],
    query: str,
    *,
    max_results: int = MAX_RESULTS,
    context_chars: int = CONTEXT_CHARS,
) -> list[dict]:
    """Up to ``max_results`` passages containing ``query``, latest chapter first.

    One match per chapter — the first occurrence. A name mentioned 40 times in
    one chapter is one passage to read, not 40; a character's fate is decided
    from where it is stated, and the agent can search again, narrower, if the
    first passage does not settle it. Latest-first mirrors `roster.latest_first`:
    for the temporal questions (status, affiliation) the passage that matters is
    the one nearest the end of the book.
    """
    needle = fold_typography(query).strip()
    if not needle:
        return []
    hits = []
    for chapter_id, text in (chapters or {}).items():
        text = str(text or "")
        pos = fold_typography(text).find(needle)
        if pos == -1:
            continue
        start = max(0, pos - context_chars // 2)
        end = min(len(text), pos + len(needle) + context_chars // 2)
        hits.append({"chapter_id": chapter_id, "text": text[start:end].strip()})
    hits.sort(key=lambda h: chapter_number(h["chapter_id"]) or 0, reverse=True)
    return hits[:max_results]
