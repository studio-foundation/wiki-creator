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
from pathlib import Path

from wiki_creator.page_templates import chrome_label
from wiki_creator.tokens import contains_token_run
from wiki_creator.roster import (
    has_marker,
    is_quoted,
    latest_first,
    load_cache,
    normalize,
    render_roster,
    save_cache,
)

STATUS_VALUES = ("alive", "deceased", "missing", "unknown", "undead")
DEFAULT_STATUS = "unknown"

CACHE_VERSION = 2

SNIPPETS_PER_ENTITY = 5
SNIPPET_CHARS = 300

# The two types a death circumstance can name (STU-552).
_CIRCUMSTANCE_TYPES = ("PERSON", "PLACE")


def select_status_snippets(snippets: list[dict], status_markers: list[str]) -> list[dict]:
    """Up to ``SNIPPETS_PER_ENTITY`` snippets, marker-bearing first, then latest.

    Two verdicts need two kinds of evidence. `deceased`/`missing`/`undead` are
    proved by a sentence that says so — the marker-bearing snippets. `alive` is
    proved by the character acting late in the book — the latest snippets. Both
    groups are latest-first: status is the state at the end of the tome, so the
    latest evidence decides.

    Snippets are ``{"text": str, "chapter_id": str}``; the chapter rides along
    because `latest_first` sorts by it.
    """
    marked: list[dict] = []
    plain: list[dict] = []
    for snippet in snippets or []:
        text = str(snippet.get("text") or "")
        (marked if has_marker(text, status_markers or []) else plain).append(snippet)

    chosen = latest_first(marked)[:SNIPPETS_PER_ENTITY]
    chosen += latest_first(plain)[: SNIPPETS_PER_ENTITY - len(chosen)]
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


def build_name_index(entities: list[dict]) -> dict[str, dict[str, str]]:
    """{entity_type: {normalized surface: canonical_name}} for the two types a
    death circumstance can name. Aliases map to their canonical name, so a
    circumstance renders `Chaol Westfall` where the text said `Captain Westfall`.
    """
    index: dict[str, dict[str, str]] = {etype: {} for etype in _CIRCUMSTANCE_TYPES}
    for entity in entities:
        names = index.get(str(entity.get("entity_type") or ""))
        if names is None:
            continue
        canonical = str(entity.get("canonical_name") or "").strip()
        if not canonical:
            continue
        for surface in (canonical, *(entity.get("aliases") or [])):
            key = normalize(surface)
            if key:
                names.setdefault(key, canonical)
    return index


def _grounded_name(value: object, quote: str, names: dict[str, str]) -> str | None:
    r"""The canonical name this value denotes, or None.

    Two gates: it is on the type's roster, and it is verbatim in the quote the
    verdict already had to prove. A name sourced from a neighbouring snippet
    would render where the character *was*, not where they died.

    The quote check is a whole-token match (shared with STU-541, same bug): a
    roster name like "Son" — a spaCy-mistyped common noun kept on the PERSON
    roster — sits inside "per**son**" with no relation to it. `boundary="word"`
    still crosses a possessive apostrophe ("Durza**'s**"), so a name owning the
    sentence keeps grounding.
    """
    surface = normalize(value)
    if not surface:
        return None
    canonical = names.get(surface)
    if canonical is None or not contains_token_run(normalize(quote), surface, boundary="word"):
        return None
    return canonical


def parse_status_verdict(
    payload: object, rows: list[dict], name_index: dict[str, dict[str, str]]
) -> dict[str, dict]:
    """Map the classifier's reply to verified verdicts, keyed by roster name.

    A name absent from the result is `unknown`; unparseable input verdicts
    nothing. A verdict survives only when its name is on the roster, its status
    is in the enum and is not `unknown`, and its quote is verbatim in **that
    entity's own** snippets. The model has read these novels: without the quote
    check, a verdict from its memory of the plot and one from this run's text
    are indistinguishable afterwards.

    A `deceased` verdict may also carry `agent` / `place` — each kept only when
    `name_index` knows it under the right type and the quote names it. A field
    failing either gate is dropped; the verdict survives (STU-552).
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
        if not is_quoted(quote, row["snippets"]):
            continue
        verdict = {"status": status, "quote": quote}
        if status == "deceased":
            agent = _grounded_name(entry.get("agent"), quote, name_index["PERSON"])
            if agent is not None and normalize(agent) == normalize(name):
                agent = None
            place = _grounded_name(entry.get("place"), quote, name_index["PLACE"])
            if agent:
                verdict["agent"] = agent
            if place:
                verdict["place"] = place
        verdicts[name] = verdict
    return verdicts


def load_cached_status(path: Path | str, rows: list[dict]) -> dict[str, dict] | None:
    """Cached verdicts for exactly this roster and this question, or None.

    Keyed on the rows themselves: the roster changes with WIKI_MAX_CHAPTERS and
    with every upstream extraction fix, and a verdict returned for a different
    roster must not be replayed onto it. The version covers what the rows
    cannot — STU-552 changed what we ask, not who we ask it about.
    """
    return load_cache(path, rows, CACHE_VERSION)


def save_status_cache(path: Path | str, rows: list[dict], verdicts: dict[str, dict]) -> None:
    save_cache(path, rows, verdicts, CACHE_VERSION)


def status_label(status: str | None, lang: str) -> str:
    """The localized enum label. An absent or unrecognized status renders the
    slot's declared fallback (`unknown`) — a book that never ran the stage and a
    verdict that was rejected must render the same thing."""
    value = str(status or "").strip().lower()
    if value not in STATUS_VALUES:
        value = DEFAULT_STATUS
    return chrome_label(f"status_{value}", lang)


def death_label(agent: str | None, place: str | None, lang: str) -> str | None:
    """The localized death circumstance, or None when neither field is grounded.

    OPT, unlike `status_label`: a character the text never says died renders no
    row at all rather than a fallback.
    """
    who = str(agent or "").strip()
    where = str(place or "").strip()
    if who and where:
        return chrome_label("death_by_at", lang).format(agent=who, place=where)
    if who:
        return chrome_label("death_by", lang).format(agent=who)
    if where:
        return chrome_label("death_at", lang).format(place=where)
    return None
