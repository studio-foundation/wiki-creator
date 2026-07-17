"""Decide which species/race a character is.

The `species` infobox slot is declared, `genre_gated: true`, and inert since
STU-504 — STU-571 assumed the value was already collected into the FACTION bucket
(`Elves`, `Dwarves`) and a typing fix would feed it. It would not: `Elves` the
collective noun is an *entity* with its own page; Eragon's `human` is an
*attribute* of the Eragon PERSON. This is per-character attribution, a
classification task independent of NER typing (STU-574).

Same shape as `entity_affiliation` (STU-551), because the verdict is the same
kind of thing — a name the model reads off the text, not an enum member. Snippet
selection is single-source (marker-bearing only), and a verdict survives only
when the species it returns is literally in the quote it cites. Species is
atemporal — a character's race does not change across the tome — so `latest_first`
here only bounds the selected set deterministically; it carries no "end of tome"
meaning as it does for `status`/`affiliation`.

The marker vocabulary only **retrieves**; the classifier decides. STU-538 measured
that lesson at 340 fires and 0 true positives when a pattern *was* the verdict.

Every helper here fails toward an omitted slot. `species` is OPT with no declared
fallback: a false species labels a character the wrong race on a page nobody will
reread, and reads as fact; an absent one says nothing.
"""

from __future__ import annotations

import json

from wiki_creator.roster import (
    has_marker,
    is_quoted,
    latest_first,
    quote_names_value,
)

# This stage's verdict schema. Its own number, per the roster.load_cache contract.
CACHE_VERSION = 1

SNIPPETS_PER_ENTITY = 5
SNIPPET_CHARS = 300


def select_species_snippets(snippets: list[dict], markers: list[str]) -> list[dict]:
    """Up to ``SNIPPETS_PER_ENTITY`` marker-bearing snippets.

    Single-source, like `select_affiliation_snippets`: nothing proves the absence
    of a species, so a snippet with no marker can only confirm the character
    exists. ``latest_first`` only makes the cap deterministic here — species does
    not change across the tome, so which marker-bearing snippets are kept does not
    change the answer, only bounds the budget.

    Snippets are ``{"text": str, "chapter_id": str}``.
    """
    marked = [
        snippet
        for snippet in snippets or []
        if has_marker(str(snippet.get("text") or ""), markers or [])
    ]
    return [
        {"text": str(s.get("text") or "")[:SNIPPET_CHARS], "chapter_id": s.get("chapter_id")}
        for s in latest_first(marked)[:SNIPPETS_PER_ENTITY]
    ]


def roster_rows(
    entities: list[dict], contexts: dict[str, list[dict]], markers: list[str]
) -> list[dict]:
    """One row per PERSON entity — the roster the classifier sees.

    ``contexts`` maps canonical_name -> that entity's snippets.
    """
    return [
        {
            "name": entity["canonical_name"],
            "aliases": sorted(a for a in (entity.get("aliases") or []) if a),
            "snippets": select_species_snippets(
                contexts.get(entity["canonical_name"], []), markers
            ),
        }
        for entity in entities
    ]


def parse_species_verdict(payload: object, rows: list[dict]) -> dict[str, dict]:
    """Map the classifier's reply to verified verdicts, keyed by roster name.

    A name absent from the result renders no slot; unparseable input verdicts
    nothing. A verdict survives three rules (see `quote_names_value` for rule 3):

    1. its name is on the roster (the model hallucinates characters);
    2. its quote is verbatim in **that entity's own** snippets (STU-539: these
       novels are in the model's training data);
    3. **the species is literally in the quote.** The value is a name, so the
       model can quote a real sentence — "Eragon killed the Urgal" — and pin the
       wrong race to the character it names.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("species")
    if not isinstance(entries, list):
        return {}

    rows_by_name = {row["name"]: row for row in rows}
    verdicts: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        species = str(entry.get("species", "") or "").strip()
        quote = str(entry.get("quote", "") or "").strip()
        row = rows_by_name.get(name)
        if row is None or name in verdicts or not species:
            continue
        if not is_quoted(quote, row["snippets"]):
            continue
        if not quote_names_value(quote, species):
            continue
        verdicts[name] = {"species": species, "quote": quote}
    return verdicts
