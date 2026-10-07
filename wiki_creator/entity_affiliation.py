"""Decide which faction a character belongs to at the end of this tome.

The `affiliation` infobox slot has been declared and inert since STU-504. STU-551
asked for a dated edge; it is a scalar. The wiki is per-tome and earlier tomes are
never regenerated, so "tome 3's faction on tome 3's page" is true by construction —
and STU-488 measured that dating a fact from the snippet that quotes it does not
work (3 of 4 derived chapters wrong: the place where the text states a fact is not
the place where the fact happens).

Since STU-2018 code picks the evidence: `book_search.select_passages` chooses
the passages naming each PERSON, favouring those holding a `affiliation_markers`
keyword (cue_words), within a fixed token budget, and the classifier judges
them in one call with no tools (STU-753's search loop is gone). It must still
ground every claim in a verbatim quote.

Every helper here fails toward an omitted slot. `affiliation` is OPT with no declared
fallback: a false affiliation puts a character in the wrong army on a page nobody will
reread, and reads as fact; an absent one says nothing.
"""

from __future__ import annotations

import json

from wiki_creator.roster import is_quoted, quote_names_entity, quote_names_value

# Stamped on the artifact this stage writes — informational (STU-753 moved the
# cache-hit decision to the engine's per-item resume, so nothing reads this back
# to gate a call anymore).
ARTIFACT_VERSION = 2


def entity_rows(entities: list[dict]) -> list[dict]:
    """One row per PERSON entity — the map fan-out's items.

    Identity only (``name``, ``aliases``); the pre stage attaches each row's
    passages (STU-2018).
    """
    return [
        {
            "name": entity["canonical_name"],
            "aliases": sorted(a for a in (entity.get("aliases") or []) if a),
        }
        for entity in entities
    ]


def parse_affiliation_verdict(
    payload: object, name: str, aliases: list[str], book_text: str
) -> dict | None:
    """This entity's verified affiliation, from the agent's reply, or None.

    A reply survives three rules (see `quote_names_value` for rule 3,
    `quote_names_entity` for rule 2):

    1. its quote is verbatim somewhere in the book's own text (STU-539: these
       novels are in the model's training data);
    2. that quote actually names this character — what a pre-selected snippet
       pack used to give for free (STU-753);
    3. **the affiliation is literally in the quote.** This is the rule `status`
       does not need. Its value is an enum member, so verifying the quote verifies
       the verdict; here the value is a name, so the model can quote a real
       sentence and infer the wrong faction from it.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None

    affiliation = str(payload.get("affiliation", "") or "").strip()
    quote = str(payload.get("quote", "") or "").strip()
    if not affiliation:
        return None
    if not is_quoted(quote, [{"text": book_text}]):
        return None
    if not quote_names_entity(quote, name, aliases):
        return None
    if not quote_names_value(quote, affiliation):
        return None
    return {"affiliation": affiliation, "quote": quote}
