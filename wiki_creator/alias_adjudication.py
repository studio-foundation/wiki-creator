"""Decide which PERSON entities are one character under two names.

The lexical detectors in alias-resolution all ask the same question — does some
sentence hold both names in a fixed shape? STU-538 measured that shape's yield
over the library: 340 hits, 0 true positives. What it cannot ask is the question
a reader answers without noticing: given everything these two names are used for,
is this one person?

So the classifier sees the whole PERSON roster at once, and per entity the
snippets that name another character. Those are the sentences that carry identity
evidence at all — a sentence naming nobody else can only confirm that the entity
exists. On Throne of Glass this keeps `Lillian Gordaina was Celaena Sardothien`
for both entities of the pair, inside a 14k-token payload for a 38-entity roster.

Every helper here fails toward NOT merging. The asymmetry is STU-538's: a false
merge invents a character that never existed, deletes a real one, and
`Registry.accumulate` propagates it to every later tome; a false negative leaves
two pages that are each individually correct.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

SNIPPETS_PER_ENTITY = 5
SNIPPET_CHARS = 300

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip().casefold()


def _mentions_other(snippet: str, other_names: set[str]) -> int:
    """How many other roster names this snippet names."""
    return sum(
        1 for name in other_names
        if re.search(r"\b" + re.escape(name) + r"\b", snippet, re.IGNORECASE)
    )


def select_snippets(snippets: list[str], own_names: set[str], roster_names: set[str]) -> list[str]:
    """The snippets that name another character, most-naming first."""
    others = {n for n in roster_names if n not in own_names}
    scored = [(_mentions_other(s, others), s) for s in snippets]
    ranked = sorted(
        ((count, s) for count, s in scored if count),
        key=lambda pair: -pair[0],
    )
    return [s[:SNIPPET_CHARS] for _, s in ranked[:SNIPPETS_PER_ENTITY]]


def roster_rows(entities: list[dict], contexts: dict[str, list[str]]) -> list[dict]:
    """One row per PERSON entity — the roster the classifier sees.

    `contexts` maps canonical_name -> that entity's mention snippets.
    """
    names_by_entity = {
        entity["canonical_name"]: set(entity.get("aliases", [])) | {entity["canonical_name"]}
        for entity in entities
    }
    roster_names = {n for names in names_by_entity.values() for n in names}
    return [
        {
            "name": entity["canonical_name"],
            "aliases": sorted(names_by_entity[entity["canonical_name"]] - {entity["canonical_name"]}),
            "snippets": select_snippets(
                contexts.get(entity["canonical_name"], []),
                names_by_entity[entity["canonical_name"]],
                roster_names,
            ),
        }
        for entity in entities
    ]


def render_roster(rows: list[dict]) -> str:
    blocks = []
    for row in rows:
        header = row["name"]
        if row["aliases"]:
            header += f" (also called: {', '.join(row['aliases'])})"
        lines = [f"## {header}"]
        lines.extend(f"- {snippet}" for snippet in row["snippets"])
        if not row["snippets"]:
            lines.append("- (no snippet names another character)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def parse_merge_verdict(payload: object, rows: list[dict]) -> list[dict]:
    """Map the classifier's reply to verified merge pairs. Unparseable input merges nothing.

    A pair survives only when both names are on the roster and the quote it cites
    is verbatim in the snippets we showed for one of the two. The model has read
    these novels; without this check a merge can come from its memory of the plot
    rather than from the text this run extracted, and there would be no way to
    tell the two apart afterwards.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    if not isinstance(payload, dict):
        return []
    entries = payload.get("merge")
    if not isinstance(entries, list):
        return []

    snippets_by_name = {row["name"]: [_normalize(s) for s in row["snippets"]] for row in rows}
    verified: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name_a = str(entry.get("a", "")).strip()
        name_b = str(entry.get("b", "")).strip()
        quote = _normalize(str(entry.get("quote", "")))
        if name_a not in snippets_by_name or name_b not in snippets_by_name or name_a == name_b:
            continue
        if not quote:
            continue
        if not any(
            quote in snippet
            for snippet in snippets_by_name[name_a] + snippets_by_name[name_b]
        ):
            continue
        key = (min(name_a, name_b), max(name_a, name_b))
        if key in seen:
            continue
        seen.add(key)
        verified.append({
            "a": name_a,
            "b": name_b,
            "quote": str(entry.get("quote", "")).strip(),
            "reason": str(entry.get("reason", "") or "").strip(),
        })
    return verified


def load_cached_merges(path: Path | str, rows: list[dict]) -> list[dict] | None:
    """Cached verdict for exactly this roster, or None.

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
    merges = cached.get("merge")
    return merges if isinstance(merges, list) else None


def save_merge_cache(path: Path | str, rows: list[dict], merges: list[dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"roster": rows, "merge": merges}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
