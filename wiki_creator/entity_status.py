"""Decide whether a character is dead by the end of this tome.

The `status` infobox slot has been declared and inert since STU-504. Filling it
needs the one thing a regex cannot give: who a sentence is *about*. STU-538
measured that lesson at 340 fires and 0 true positives — a pattern matched in one
entity's context was credited to whichever entity happened to be paired with it.
"Eragon watched Brom die" holds a death marker in both characters' contexts and
kills exactly one of them.

So the marker vocabulary only **retrieves**: it picks which snippets the
classifier reads. The classifier decides. A marker missing from the vocabulary
means a death is never surfaced, which means `unknown` — the forgiving direction.

Every helper here fails toward `unknown`. The asymmetry is STU-539's: a false
`deceased` kills a living character on a page nobody will reread, while a false
`unknown` renders the slot's own declared fallback.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_creator.chapters import chapter_number
from wiki_creator.page_templates import chrome_label

STATUS_VALUES = ("alive", "deceased", "missing", "unknown", "undead")
DEFAULT_STATUS = "unknown"

SNIPPETS_PER_ENTITY = 5
SNIPPET_CHARS = 300

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: object) -> str:
    return _WHITESPACE_RE.sub(" ", str(text or "")).strip().casefold()


def _has_marker(text: str, status_markers: list[str]) -> bool:
    return any(
        re.search(r"\b" + re.escape(marker) + r"\b", text, re.IGNORECASE)
        for marker in status_markers
        if marker
    )


def _latest_first(snippets: list[dict]) -> list[dict]:
    """Sorted by chapter, latest first. An unnumbered chapter (``Prologue``)
    sorts earliest. Stable, so same-chapter snippets keep source order."""
    return sorted(
        snippets,
        key=lambda snippet: chapter_number(snippet.get("chapter_id")) or 0,
        reverse=True,
    )


def select_status_snippets(snippets: list[dict], status_markers: list[str]) -> list[dict]:
    """Up to ``SNIPPETS_PER_ENTITY`` snippets, marker-bearing first, then latest.

    Two verdicts need two kinds of evidence. `deceased`/`missing`/`undead` are
    proved by a sentence that says so — the marker-bearing snippets. `alive` is
    proved by the character acting late in the book — the latest snippets. Both
    groups are latest-first: status is the state at the end of the tome, so the
    latest evidence decides.

    Snippets are ``{"text": str, "chapter_id": str}``; the chapter rides along
    because the caller derives the `death` slot from it, never from the model.
    """
    marked: list[dict] = []
    plain: list[dict] = []
    for snippet in snippets or []:
        text = str(snippet.get("text") or "")
        (marked if _has_marker(text, status_markers or []) else plain).append(snippet)

    chosen = _latest_first(marked)[:SNIPPETS_PER_ENTITY]
    chosen += _latest_first(plain)[: SNIPPETS_PER_ENTITY - len(chosen)]
    return [
        {"text": str(snippet.get("text") or "")[:SNIPPET_CHARS], "chapter_id": snippet.get("chapter_id")}
        for snippet in chosen
    ]


def roster_rows(
    entities: list[dict], contexts: dict[str, list[dict]], status_markers: list[str]
) -> list[dict]:
    """One row per PERSON entity — the roster the classifier sees.

    ``contexts`` maps canonical_name -> that entity's snippets.
    """
    return [
        {
            "name": entity["canonical_name"],
            "aliases": sorted(a for a in (entity.get("aliases") or []) if a),
            "snippets": select_status_snippets(
                contexts.get(entity["canonical_name"], []), status_markers
            ),
        }
        for entity in entities
    ]


def render_roster(rows: list[dict]) -> str:
    """The roster block the classifier reads. Text only — the chapter is derived
    by the caller from the snippet the verdict quotes, never reported by the model."""
    blocks = []
    for row in rows:
        header = row["name"]
        if row["aliases"]:
            header += f" (also called: {', '.join(row['aliases'])})"
        lines = [f"## {header}"]
        lines.extend(f"- {snippet['text']}" for snippet in row["snippets"])
        if not row["snippets"]:
            lines.append("- (no snippet found for this character)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _quoted_snippet(quote: str, snippets: list[dict]) -> dict | None:
    """The entity's own snippet holding ``quote`` verbatim, or None.

    Verification and dating are one lookup: the snippet that proves the verdict
    is the snippet that dates it.
    """
    needle = _normalize(quote)
    if not needle:
        return None
    for snippet in snippets:
        if needle in _normalize(snippet.get("text")):
            return snippet
    return None


def parse_status_verdict(payload: object, rows: list[dict]) -> dict[str, dict]:
    """Map the classifier's reply to verified verdicts, keyed by roster name.

    A name absent from the result is `unknown`; unparseable input verdicts
    nothing. A verdict survives only when its name is on the roster, its status
    is in the enum and is not `unknown`, and its quote is verbatim in **that
    entity's own** snippets. The model has read these novels: without the quote
    check, a verdict from its memory of the plot and one from this run's text
    are indistinguishable afterwards.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("status")
    if not isinstance(entries, list):
        return {}

    rows_by_name = {row["name"]: row for row in rows}
    verdicts: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        status = str(entry.get("status", "")).strip().lower()
        quote = str(entry.get("quote", "") or "").strip()
        row = rows_by_name.get(name)
        if row is None or name in verdicts:
            continue
        if status not in STATUS_VALUES or status == DEFAULT_STATUS:
            continue
        snippet = _quoted_snippet(quote, row["snippets"])
        if snippet is None:
            continue
        verdicts[name] = {
            "status": status,
            "quote": quote,
            "chapter": chapter_number(snippet.get("chapter_id")) if status == "deceased" else None,
        }
    return verdicts


def load_cached_status(path: Path | str, rows: list[dict]) -> dict[str, dict] | None:
    """Cached verdicts for exactly this roster, or None.

    Keyed on the rows themselves: the roster changes with WIKI_MAX_CHAPTERS and
    with every upstream extraction fix, and a verdict returned for a different
    roster must not be replayed onto it.
    """
    try:
        cached = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("roster") != rows:
        return None
    verdicts = cached.get("verdicts")
    return verdicts if isinstance(verdicts, dict) else None


def save_status_cache(path: Path | str, rows: list[dict], verdicts: dict[str, dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"roster": rows, "verdicts": verdicts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def status_label(status: str | None, lang: str) -> str:
    """The localized enum label. An absent or unrecognized status renders the
    slot's declared fallback (`unknown`) — a book that never ran the stage and a
    verdict that was rejected must render the same thing."""
    value = str(status or "").strip().lower()
    if value not in STATUS_VALUES:
        value = DEFAULT_STATUS
    return chrome_label(f"status_{value}", lang)


def death_label(chapter: int | None, lang: str) -> str | None:
    """The localized death line, or None when there is no chapter to name."""
    if chapter is None:
        return None
    return chrome_label("death_chapter", lang).format(chapter=chapter)
