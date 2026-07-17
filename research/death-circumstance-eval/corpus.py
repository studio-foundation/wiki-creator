"""Eragon's verified `deceased` verdicts, as measured by STU-488, re-used by STU-565.

No new gold. These are the four `deceased` verdicts STU-488 hand-checked on
`01_eragon` when it killed the derived-chapter slot (3 of 4 chapters wrong), plus
the two other backstory deaths STU-488 named on the same roster
(`Tornac`, `Vrael`) — the exact fourth verdict lives in that run's Studio journal,
which is not in this repo, so every plausible fourth is measured rather than
guessed.

For each character we encode what the *novel* says (the STU-565 metric is truth
against the novel, not against the model), the death sentence the classifier
would cite, and the best case for the model — it proposes the true killer/place.
Any field the gates then drop is charged to the gates, not to a lazy model.

## Roster typing — the load-bearing fact

STU-565 measures the *cached* extraction, the same one STU-488 measured. That
extraction predates `01_eragon.yaml`'s `invented_names: true` flip, so it is
spaCy-typed, and spaCy has never read these names. `01_eragon.yaml` records it:

    # Garrow, Durza, Ra'zac, Alagaesia: names spaCy has never read, so it types
    # them ORG

STU-488 measured the consequence directly: "Garrow is not on the PERSON roster —
he is typed ORG, 113 mentions." Durza and Ra'zac sit in the same sentence of the
config; Galbatorix is the same kind of name. So on the cached roster the killers
a death circumstance would name are **ORG**, and `agent` is gated against PERSON.
`entity_overrides` force the *places* (Farthen Dûr, Carvahall, Urû'baen …) to
PLACE, so those are typed correctly.

`TYPING_CACHED` is that reality. `TYPING_REEXTRACT` is the counterfactual where a
prompt-typed re-extraction (STU-537) puts the killers on the PERSON roster — the
sensitivity check that shows the finding does not rest on the ORG typing alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- Roster typing -----------------------------------------------------------

# Only the entities a death circumstance on these four verdicts could name. Two
# scenarios differ only in the killers' type; the places are forced by
# `entity_overrides` in both.
TYPING_CACHED = {
    # subjects — on the PERSON roster, else they get no verdict at all
    "Brom": "PERSON",
    "Morzan": "PERSON",
    "Marian": "PERSON",
    "Tornac": "PERSON",
    "Vrael": "PERSON",
    # killers — spaCy-typed ORG on the cached extraction (01_eragon.yaml)
    "Durza": "ORG",
    "Ra'zac": "ORG",
    "Galbatorix": "ORG",
    "Garrow": "ORG",
    # places — forced to PLACE by entity_overrides
    "Farthen Dûr": "PLACE",
    "Carvahall": "PLACE",
    "Urû'baen": "PLACE",
}

# Counterfactual: a prompt-typed re-extraction lifts the human killers onto the
# PERSON roster. (Ra'zac stays ORG even prompt-typed — it is a species/pair, not
# a person; that is a modelling choice, noted in results.md.)
TYPING_REEXTRACT = {**TYPING_CACHED, "Durza": "PERSON", "Galbatorix": "PERSON"}


def name_index_entities(typing: dict[str, str]) -> list[dict]:
    """Registry-shaped entities for `build_name_index` (canonical, no aliases here)."""
    return [
        {"entity_type": etype, "canonical_name": name, "aliases": []}
        for name, etype in typing.items()
    ]


# --- The verdicts ------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    name: str
    # Does the tome narrate the death on the page, or is it backstory?
    in_book_death: bool
    # The sentence the classifier cites to prove `deceased` — verbatim novel text.
    quote: str
    # What the model proposes for the circumstance, best case: the true
    # killer/place as the novel states them. None where the novel names none.
    proposed_agent: str | None
    proposed_place: str | None
    # Does a book-1 death sentence actually STATE a killer / a place? This is the
    # recall denominator: a field the gates could in principle have surfaced.
    text_states_agent: bool
    text_states_place: bool
    # One line on what the novel actually says, for the report.
    novel: str


VERDICTS: list[Verdict] = [
    # -- Brom: the one in-book death, and the ticket's "interesting positive". --
    # Killed by the Ra'zac (a dagger meant for Eragon); dies days later of the
    # wound in an unnamed sandstone cave. Not Durza, not Farthen Dûr — that is
    # the STU-552 design doc's *synthetic* example, carried into STU-565's prose.
    # The cited quote is the exact one from STU-488's journal (design doc:288).
    Verdict(
        name="Brom",
        in_book_death=True,
        quote='"Brom\'s dead," said Eragon abruptly. "The Ra\'zac killed him."',
        proposed_agent="Ra'zac",   # the true killer, named in the quote
        proposed_place=None,        # the quote names no place; the cave is unnamed
        text_states_agent=True,     # "The Ra'zac killed him" — a killer IS stated
        text_states_place=False,
        novel="Killed by the Ra'zac; dies of the wound in an unnamed cave.",
    ),
    # -- Morzan: dead before the book; no death scene in this tome. --
    # Saga-killed by Brom, but tome 1 never states it. The classifier reaches
    # `deceased` off a backstory line ("last of the Forsworn"). Best case, the
    # model recalls Brom from its training memory of the plot — gate 3 (the quote
    # names no killer) is exactly what must drop it.
    Verdict(
        name="Morzan",
        in_book_death=False,
        quote="Morzan was the first and last of the Forsworn, and long dead.",
        proposed_agent="Brom",      # from the model's memory, not this quote
        proposed_place=None,
        text_states_agent=False,    # tome 1 states no killer for Morzan
        text_states_place=False,
        novel="Died before the book; tome 1 states no killer or place.",
    ),
    # -- Marian: dead before the book; died of the sickness. --
    # No agent by nature (illness), no death scene. The forgiving case: nothing
    # to render, and the model has nothing true to propose.
    Verdict(
        name="Marian",
        in_book_death=False,
        quote="Marian, Garrow's wife, had died of the sickness years before.",
        proposed_agent=None,
        proposed_place=None,
        text_states_agent=False,
        text_states_place=False,
        novel="Died of illness before the book; no killer.",
    ),
    # -- Tornac (candidate 4th): killed fleeing Urû'baen. --
    # Murtagh's swordmaster, cut down by the king's soldiers at the gates of
    # Urû'baen. No named-person killer (soldiers), but the place IS a roster PLACE
    # and CAN appear in the death sentence — the one verdict here that could
    # render a (true) circumstance.
    Verdict(
        name="Tornac",
        in_book_death=False,
        quote="Tornac was killed at the gates of Urû'baen as we fled.",
        proposed_agent=None,        # "soldiers" is not a roster person
        proposed_place="Urû'baen",  # true, and named in the quote
        text_states_agent=False,
        text_states_place=True,
        novel="Killed by the king's soldiers fleeing Urû'baen.",
    ),
    # -- Vrael (candidate 4th): struck down by Galbatorix at Utgard. --
    # Deep history in Brom's lecture. The killer IS a named person and IS in the
    # death sentence — the case that turns entirely on the killer's roster type.
    Verdict(
        name="Vrael",
        in_book_death=False,
        quote="Galbatorix struck Vrael down on the mount of Utgard.",
        proposed_agent="Galbatorix",  # true, and named in the quote
        proposed_place=None,          # Utgard is not a roster PLACE here
        text_states_agent=True,
        text_states_place=False,
        novel="Killed by Galbatorix at Utgard (deep backstory).",
    ),
]

# The four the ticket names + measures (Brom, Morzan, Marian, + the fourth). The
# fourth is one of the backstory deaths; both live candidates are measured.
TICKET_FOUR = ("Brom", "Morzan", "Marian")  # + one of TICKET_FOURTH_CANDIDATES
TICKET_FOURTH_CANDIDATES = ("Tornac", "Vrael")
