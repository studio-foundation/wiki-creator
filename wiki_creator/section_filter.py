"""Decide which EPUB sections are front/back matter rather than narrative.

The classifier sees the whole section list at once, because most of the signal is
structural: position in the spine, size, and the naming pattern of the neighbours.
Titles alone are not enough — a Calibre-generated `index_split_002.html` is a table
of contents while `index_split_042.html` is a chapter, and `Argument` names both an
in-world prose opening and a marketing synopsis. So each row also carries the
section's opening characters, which is where the deciding signal actually sits.

Every helper here fails toward keeping a section. A false keep costs one visible
junk entity; a false drop silently deletes a real chapter from a book nobody here
will ever read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

OPENING_CHARS = 200

_WHITESPACE_RE = re.compile(r"\s+")


def _opening(content: str) -> str:
    """First characters of a section, safe to render as a pipe-delimited column."""
    return _WHITESPACE_RE.sub(" ", content.replace("|", "/")).strip()[:OPENING_CHARS]


def section_rows(chapters: list[dict]) -> list[dict]:
    """One row per section, in spine order — the list the classifier sees."""
    return [
        {
            "id": str(chapter.get("id", "")),
            "title": str(chapter.get("title", "")).strip() or str(chapter.get("id", "")),
            "chars": len(str(chapter.get("content", ""))),
            "opening": _opening(str(chapter.get("content", ""))),
        }
        for chapter in chapters
    ]


def render_section_list(rows: list[dict]) -> str:
    return "\n".join(
        f"{row['id']} | {row['title']} | {row['chars']} | {row['opening']}" for row in rows
    )


def parse_drop_verdict(payload: object, known_ids: set[str]) -> dict[str, str]:
    """Map section id -> drop reason. Unparseable input drops nothing."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("drop")
    if not isinstance(entries, list):
        return {}

    drops: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        section_id = str(entry.get("id", "")).strip()
        if section_id in known_ids:
            drops[section_id] = str(entry.get("reason", "") or "").strip()
    return drops


def apply_frontmatter(chapters: list[dict], drops: dict[str, str]) -> list[dict]:
    """Tag dropped sections in place. Returns what was tagged, for logging."""
    tagged: list[dict] = []
    for chapter in chapters:
        section_id = str(chapter.get("id", ""))
        if section_id not in drops:
            continue
        chapter["frontmatter"] = True
        tagged.append({
            "id": section_id,
            "title": str(chapter.get("title", "")).strip() or section_id,
            "reason": drops[section_id],
        })
    return tagged


def load_cached_drops(path: Path | str, rows: list[dict]) -> dict[str, str] | None:
    """Cached verdict for exactly this section list, or None.

    Keyed on the rows themselves: WIKI_MAX_CHAPTERS truncates the book, and a
    verdict returned for a different section list must not be replayed onto it.
    """
    try:
        cached = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("sections") != rows:
        return None
    drops = cached.get("drop")
    return drops if isinstance(drops, dict) else None


def save_drop_cache(path: Path | str, rows: list[dict], drops: dict[str, str]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"sections": rows, "drop": drops}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
