"""Decide which species/race a character is.

The `species` infobox slot is declared, `genre_gated: true`, and inert since
STU-504 — STU-571 assumed the value was already collected into the FACTION bucket
(`Elves`, `Dwarves`) and a typing fix would feed it. It would not: `Elves` the
collective noun is an *entity* with its own page; Eragon's `human` is an
*attribute* of the Eragon PERSON. This is per-character attribution, a
classification task independent of NER typing (STU-574).

Same shape as `entity_affiliation` (STU-551), because the verdict is the same
kind of thing — a name the model reads off the text, not an enum member. Since
STU-753 the classifier no longer receives a pre-selected snippet pack — it
searches the book itself (`wiki_creator.book_search`, one call per PERSON,
STU-605-style per-item resume) and must ground every claim in what it found.
The marker vocabulary that used to *retrieve* (`species_markers` in each
language's cue_words) is gone from this path along with it.

Every helper here fails toward an omitted slot. `species` is OPT with no declared
fallback: a false species labels a character the wrong race on a page nobody will
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

    Identity only (``name``, ``aliases``): since STU-753 there is no snippet
    pack to attach, the agent searches the book itself for each one.
    """
    return [
        {
            "name": entity["canonical_name"],
            "aliases": sorted(a for a in (entity.get("aliases") or []) if a),
        }
        for entity in entities
    ]


def parse_species_verdict(
    payload: object, name: str, aliases: list[str], book_text: str
) -> dict | None:
    """This entity's verified species, from the agent's reply, or None.

    A reply survives three rules (see `quote_names_value` for rule 3,
    `quote_names_entity` for rule 2):

    1. its quote is verbatim somewhere in the book's own text (STU-539: these
       novels are in the model's training data);
    2. that quote actually names this character — what a pre-selected snippet
       pack used to give for free (STU-753);
    3. **the species is literally in the quote.** The value is a name, so the
       model can quote a real sentence — "Eragon killed the Urgal" — and pin
       the wrong race to the character it names.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None

    species = str(payload.get("species", "") or "").strip()
    quote = str(payload.get("quote", "") or "").strip()
    if not species:
        return None
    if not is_quoted(quote, [{"text": book_text}]):
        return None
    if not quote_names_entity(quote, name, aliases):
        return None
    if not quote_names_value(quote, species):
        return None
    return {"species": species, "quote": quote}
