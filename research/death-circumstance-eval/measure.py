"""STU-565 — measure the death circumstance against Eragon's verified verdicts.

Runs the *real* gate (`wiki_creator.entity_status.parse_status_verdict`) over the
four verified `deceased` verdicts, once per roster-typing scenario, and reports
the two numbers STU-565 asks for:

* **False circumstance rate** — a rendered `agent`/`place` that is not what the
  novel says. The asymmetry STU-552 is built on; the one that matters.
* **Recall** — book-1 death sentences that DO state a killer/place, where the
  gates dropped it. Expected non-zero by design; cheap; worth knowing the size.

Why this is a valid measurement without an LLM: STU-552's correctness lives
entirely in the deterministic gate. The model only *proposes* a circumstance; the
gate decides what renders. We feed the gate the novel's real death sentences and
the model's best-case (truthful) proposal, so every dropped field is the gate's
doing. Reproduces, byte for byte, every time.

    cd research/death-circumstance-eval && PYTHONPATH=../.. python measure.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root

from wiki_creator.entity_status import (  # noqa: E402  (after sys.path)
    build_name_index,
    death_label,
    parse_status_verdict,
)

from corpus import (  # noqa: E402
    TYPING_CACHED,
    TYPING_REEXTRACT,
    VERDICTS,
    Verdict,
    name_index_entities,
)


def _rendered(verdict: Verdict, typing: dict[str, str]) -> dict:
    """Run one verdict through the real gate; return what actually renders.

    The model's reply carries its best-case proposal. The gate keeps a field
    only if it is on the roster (right type) and verbatim in this quote.
    """
    name_index = build_name_index(name_index_entities(typing))
    rows = [{"name": verdict.name, "aliases": [], "snippets": [{"text": verdict.quote, "chapter_id": "cN"}]}]
    entry = {"name": verdict.name, "status": "deceased", "quote": verdict.quote}
    if verdict.proposed_agent is not None:
        entry["agent"] = verdict.proposed_agent
    if verdict.proposed_place is not None:
        entry["place"] = verdict.proposed_place

    parsed = parse_status_verdict({"status": [entry]}, rows, name_index).get(verdict.name, {})
    agent, place = parsed.get("agent"), parsed.get("place")
    return {
        "agent": agent,
        "place": place,
        "label": death_label(agent, place, "fr"),  # what the infobox row shows
    }


def measure(typing: dict[str, str]) -> dict:
    """Metrics for one roster-typing scenario."""
    rows, rendered_fields, false_fields = [], 0, 0
    recall_hits, recall_opportunities = 0, 0

    for v in VERDICTS:
        out = _rendered(v, typing)

        # A rendered field is FALSE when it is not what the novel says. Best-case
        # proposals are all true, so a surviving field is true by construction;
        # a false field would only appear if a gate let an untrue value through.
        for kind, value, proposed in (
            ("agent", out["agent"], v.proposed_agent),
            ("place", out["place"], v.proposed_place),
        ):
            if value is not None:
                rendered_fields += 1
                if value != proposed:  # gate let through something not proposed/true
                    false_fields += 1

        # Recall: the text states a field, did the gate surface it?
        for states, value in (
            (v.text_states_agent, out["agent"]),
            (v.text_states_place, out["place"]),
        ):
            if states:
                recall_opportunities += 1
                if value is not None:
                    recall_hits += 1

        rows.append((v, out))

    return {
        "rows": rows,
        "rendered_fields": rendered_fields,
        "false_fields": false_fields,
        "false_rate": (false_fields / rendered_fields) if rendered_fields else 0.0,
        "circumstances_rendered": sum(1 for _, o in rows if o["label"] is not None),
        "recall_hits": recall_hits,
        "recall_opportunities": recall_opportunities,
    }


def _print(scenario: str, typing: dict[str, str]) -> dict:
    m = measure(typing)
    print(f"\n=== {scenario} ===")
    print(f"{'verdict':<9} {'in-book':<8} {'agent':<12} {'place':<11} rendered row")
    print("-" * 62)
    for v, out in m["rows"]:
        print(
            f"{v.name:<9} "
            f"{('yes' if v.in_book_death else 'backstory'):<8} "
            f"{str(out['agent']):<12} "
            f"{str(out['place']):<11} "
            f"{out['label'] or '—'}"
        )
    print("-" * 62)
    print(
        f"circumstances rendered : {m['circumstances_rendered']}/{len(m['rows'])}"
    )
    print(
        f"false circumstance rate: {m['false_fields']}/{m['rendered_fields']} "
        f"fields = {m['false_rate']:.0%}"
    )
    print(
        f"agent/place recall     : {m['recall_hits']}/{m['recall_opportunities']} "
        "stated fields surfaced"
    )
    return m


# --- Adversarial arm: the false facts the gate must reject -------------------
# Best-case proposals make the false rate trivially 0. This arm proves the 0 is
# the gate's doing: it feeds FALSE circumstances — including the exact one the
# STU-565 ticket itself believed ("Brom killed by Durza at Farthen Dûr", which is
# the STU-552 design doc's synthetic example, not the novel) — against Brom's
# REAL death quote, and shows each renders nothing.

_BROM_QUOTE = '"Brom\'s dead," said Eragon abruptly. "The Ra\'zac killed him."'

ADVERSARIAL = [
    # (label, subject, quote shown, agent proposed, place proposed)
    ("ticket's belief: Durza / Farthen Dûr", "Brom", _BROM_QUOTE, "Durza", "Farthen Dûr"),
    ("hallucinated killer on the real quote", "Brom", _BROM_QUOTE, "Durza", None),
    ("real killer, wrong type (Ra'zac=ORG)", "Brom", _BROM_QUOTE, "Ra'zac", None),
    # The synthetic sentence in isolation: all three gates pass — proof the gate
    # is not simply refusing everything. It renders; it just never gets this
    # sentence, because the novel does not contain it.
    (
        "synthetic sentence (design-doc example)",
        "Brom",
        "Durza's blade took Brom in the side at Farthen Dûr",
        "Durza",
        "Farthen Dûr",
    ),
]


def _adversarial(typing: dict[str, str]) -> None:
    name_index = build_name_index(name_index_entities(typing))
    print(f"\n=== Adversarial (roster: {'cached' if typing is TYPING_CACHED else 're-extract'}) ===")
    print(f"{'case':<42} renders")
    print("-" * 62)
    for label, subject, quote, agent, place in ADVERSARIAL:
        rows = [{"name": subject, "aliases": [], "snippets": [{"text": quote, "chapter_id": "cN"}]}]
        entry = {"name": subject, "status": "deceased", "quote": quote}
        if agent is not None:
            entry["agent"] = agent
        if place is not None:
            entry["place"] = place
        parsed = parse_status_verdict({"status": [entry]}, rows, name_index).get(subject, {})
        rendered = death_label(parsed.get("agent"), parsed.get("place"), "fr")
        print(f"{label:<42} {rendered or '— (dropped)'}")


def main() -> None:
    print("STU-565 — death circumstance vs Eragon's 4 verified `deceased` verdicts")
    print("(best case for the model: it proposes the TRUE killer/place every time)")
    _print("Scenario A — cached spaCy extraction (what STU-488/565 measured)", TYPING_CACHED)
    _print("Scenario B — prompt-typed re-extraction (killers on PERSON roster)", TYPING_REEXTRACT)
    _adversarial(TYPING_CACHED)


if __name__ == "__main__":
    main()
