"""Decide whether a character is dead by the end of this tome.

The `status` infobox slot has been declared and inert since STU-504. Filling it
needs the one thing a regex cannot give: who a sentence is *about*. STU-538
measured that lesson at 340 fires and 0 true positives — a pattern matched in one
entity's context was credited to whichever entity happened to be paired with it.
"Eragon watched Brom die" holds a death marker in both characters' contexts and
kills exactly one of them.

Since STU-753 the classifier no longer receives a pre-selected snippet pack —
it searches the book itself (`wiki_creator.book_search`, one call per PERSON,
STU-605-style per-item resume) and must ground every claim in what it found.
The marker vocabulary that used to *retrieve* (`status_markers` in each
language's cue_words) is gone from this path along with it: nothing here picks
which passages the model sees anymore, so nothing here needs to.

Every helper here fails toward `unknown`. The asymmetry is STU-539's: a false
`deceased` kills a living character on a page nobody will reread, while a false
`unknown` renders the slot's own declared fallback.
"""

from __future__ import annotations

import json

from wiki_creator.page_templates import chrome_label
from wiki_creator.tokens import contains_token_run
from wiki_creator.roster import is_quoted, normalize, quote_names_entity

STATUS_VALUES = ("alive", "deceased", "missing", "unknown", "undead")
DEFAULT_STATUS = "unknown"

# Stamped on the artifact this stage writes — informational (no reader keys a
# cache-hit decision off it anymore, STU-753 moved that to the engine's
# per-item resume), kept so a future reader can tell which verdict shape wrote it.
ARTIFACT_VERSION = 3

# The two types a death circumstance can name (STU-552).
_CIRCUMSTANCE_TYPES = ("PERSON", "PLACE")


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
    verdict already had to prove. A name sourced from a neighbouring passage
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
    payload: object,
    name: str,
    aliases: list[str],
    book_text: str,
    name_index: dict[str, dict[str, str]],
) -> dict | None:
    """This entity's verified status, from the agent's reply, or None.

    A reply survives only when its status is in the enum and is not `unknown`,
    its quote is verbatim somewhere in the book's own text, and that quote
    actually names this character. The first check is the free-search analogue
    of STU-539's snippet check: the model has read this novel before, and
    without it a verdict from its memory of the plot and one from this run's
    text are indistinguishable. The second is what a pre-selected snippet pack
    used to give for free (STU-753): grounding against the whole book admits
    any real sentence, including one that is about someone else entirely.

    A `deceased` verdict may also carry `agent` / `place`, each kept only when
    `name_index` knows it under the right type and the quote names it (STU-552).
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return None
    if not isinstance(payload, dict):
        return None

    status = str(payload.get("status", "")).strip().lower()
    quote = str(payload.get("quote", "") or "").strip()
    if status not in STATUS_VALUES or status == DEFAULT_STATUS:
        return None
    if not is_quoted(quote, [{"text": book_text}]):
        return None
    if not quote_names_entity(quote, name, aliases):
        return None

    verdict = {"status": status, "quote": quote}
    if status == "deceased":
        agent = _grounded_name(payload.get("agent"), quote, name_index["PERSON"])
        if agent is not None and normalize(agent) == normalize(name):
            # The subject's own name is the one name guaranteed to clear the
            # quote gate (the quote is about them) — it must never render as
            # its own killer.
            agent = None
        place = _grounded_name(payload.get("place"), quote, name_index["PLACE"])
        if agent:
            verdict["agent"] = agent
        if place:
            verdict["place"] = place
    return verdict


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
