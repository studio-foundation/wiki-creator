"""What a roster-classifier stage does regardless of what it asks.

`entity_status` (STU-488) and `entity_affiliation` (STU-551) both send the PERSON
roster to one `studio run`, verify the reply against the snippets they showed, and
cache on the roster rows. The shape is STU-529's and STU-539's before them. What
differs is the question — which snippets to select, and what makes a verdict valid.
That stays in each stage; this is the rest.

`normalize`'s typographic folding is load-bearing (99a6a71): an EPUB's dialogue ships
curly quotes and the model echoes straight ones, so without folding both sides every
verdict whose evidence sat inside dialogue was silently dropped — in a novel, where
such facts are announced in dialogue.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_creator.chapters import chapter_number

_WHITESPACE_RE = re.compile(r"\s+")

# An EPUB's typesetting uses curly quotes/dashes; the model echoes the same
# sentence back in plain ASCII. Folding both to one form is what lets a
# verbatim quote inside dialogue still match its source snippet.
_TYPOGRAPHIC_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "′": "'",
        "″": '"',
        "…": "...",
        "–": "-",
        "—": "-",
        "‑": "-",
    }
)


def normalize(text: object) -> str:
    folded = str(text or "").translate(_TYPOGRAPHIC_TRANSLATION)
    return _WHITESPACE_RE.sub(" ", folded).strip().casefold()


def has_marker(text: str, markers: list[str]) -> bool:
    return any(
        re.search(r"\b" + re.escape(marker) + r"\b", text, re.IGNORECASE)
        for marker in markers
        if marker
    )


def latest_first(snippets: list[dict]) -> list[dict]:
    """Sorted by chapter, latest first. An unnumbered chapter (``Prologue``)
    sorts earliest. Stable, so same-chapter snippets keep source order."""
    return sorted(
        snippets,
        key=lambda snippet: chapter_number(snippet.get("chapter_id")) or 0,
        reverse=True,
    )


def render_roster(rows: list[dict]) -> str:
    """The roster block the classifier reads. Text only — the chapter is never
    shown or reported by the model."""
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


def is_quoted(quote: str, snippets: list[dict]) -> bool:
    """True iff ``quote`` is verbatim in one of the entity's own ``snippets``."""
    needle = normalize(quote)
    if not needle:
        return False
    return any(needle in normalize(snippet.get("text")) for snippet in snippets)


# Tokenizes on word characters, so a value's punctuation never welds itself to
# the sentence: "…joined the Varden." must still name `Varden`.
_WORD_RE = re.compile(r"\w+")


def quote_names_value(quote: str, value: str) -> bool:
    """True iff ``value``'s tokens appear contiguously in ``quote``.

    The companion of `is_quoted`: that verifies the quote is real, this verifies
    the quote actually names the value a name-returning stage claims from it. A
    stage whose verdict is an enum member (`status`) does not need it; one whose
    verdict is a name — the faction the model infers, the species it reads off —
    can quote a real sentence and pin the wrong value to it (STU-551).

    Whole tokens, never a substring (STU-541, same reason): `beaver` inside
    `Beavers`, or `Order` off *"he ordered the villagers"*, is an accident of
    spelling, not a mention.
    """
    group = _WORD_RE.findall(normalize(value))
    if not group:
        return False
    words = _WORD_RE.findall(normalize(quote))
    return any(
        words[i:i + len(group)] == group for i in range(len(words) - len(group) + 1)
    )


def load_cache(path: Path | str, rows: list[dict], version: int) -> dict[str, dict] | None:
    """Cached verdicts for exactly this roster and this verdict schema, or None.

    Keyed on the rows themselves: the roster changes with WIKI_MAX_CHAPTERS and
    with every upstream extraction fix, and a verdict returned for a different
    roster must not be replayed onto it.

    ``version`` is the caller's *verdict schema* — not this module's. STU-552
    widened `status`'s verdict to carry a death circumstance, so a v1 entry has
    no `agent`/`place` and must not be replayed into code that reads them. Each
    stage owns its own number, because each stage's verdict evolves on its own.
    """
    try:
        cached = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("roster") != rows:
        return None
    if cached.get("version") != version:
        return None
    verdicts = cached.get("verdicts")
    return verdicts if isinstance(verdicts, dict) else None


def save_cache(
    path: Path | str, rows: list[dict], verdicts: dict[str, dict], version: int
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": version, "roster": rows, "verdicts": verdicts},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
