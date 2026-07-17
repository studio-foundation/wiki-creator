"""Decide which faction a character belongs to at the end of this tome.

The `affiliation` infobox slot has been declared and inert since STU-504. STU-551
asked for a dated edge; it is a scalar. The wiki is per-tome and earlier tomes are
never regenerated, so "tome 3's faction on tome 3's page" is true by construction —
and STU-488 measured that dating a fact from the snippet that quotes it does not
work (3 of 4 derived chapters wrong: the place where the text states a fact is not
the place where the fact happens).

Snippet selection is single-source where `status` is two-source: no sentence proves
"no affiliation", so there is no `alive`-analogue proved by acting late. Marker-bearing
snippets, latest-first — which is what makes the scalar mean "end of tome" and absorbs
an intra-tome switch without dating it.

The marker vocabulary only **retrieves**; the classifier decides. STU-538 measured
that lesson at 340 fires and 0 true positives when a pattern *was* the verdict.

Every helper here fails toward an omitted slot. `affiliation` is OPT with no declared
fallback: a false affiliation puts a character in the wrong army on a page nobody will
reread, and reads as fact; an absent one says nothing.
"""

from __future__ import annotations

import json

from wiki_creator.roster import has_marker, is_quoted, latest_first, normalize

SNIPPETS_PER_ENTITY = 5
SNIPPET_CHARS = 300


def select_affiliation_snippets(snippets: list[dict], markers: list[str]) -> list[dict]:
    """Up to ``SNIPPETS_PER_ENTITY`` marker-bearing snippets, latest-first.

    Single-source, unlike `select_status_snippets`. `status` needs the latest
    snippets too because `alive` is proved by a character acting late; nothing
    proves the absence of an affiliation, so a snippet with no marker can only
    confirm the character exists.

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
            "snippets": select_affiliation_snippets(
                contexts.get(entity["canonical_name"], []), markers
            ),
        }
        for entity in entities
    ]


def parse_affiliation_verdict(payload: object, rows: list[dict]) -> dict[str, dict]:
    """Map the classifier's reply to verified verdicts, keyed by roster name.

    A name absent from the result renders no slot; unparseable input verdicts
    nothing. A verdict survives three rules:

    1. its name is on the roster (the model hallucinates characters);
    2. its quote is verbatim in **that entity's own** snippets (STU-539: these
       novels are in the model's training data);
    3. **the affiliation is literally in the quote.** This is the rule `status`
       does not need. Its value is an enum member, so verifying the quote verifies
       the verdict; here the value is a name, so the model can quote a real
       sentence and infer the wrong faction from it.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("affiliation")
    if not isinstance(entries, list):
        return {}

    rows_by_name = {row["name"]: row for row in rows}
    verdicts: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        affiliation = str(entry.get("affiliation", "") or "").strip()
        quote = str(entry.get("quote", "") or "").strip()
        row = rows_by_name.get(name)
        if row is None or name in verdicts or not affiliation:
            continue
        if not is_quoted(quote, row["snippets"]):
            continue
        if normalize(affiliation) not in normalize(quote):
            continue
        verdicts[name] = {"affiliation": affiliation, "quote": quote}
    return verdicts
