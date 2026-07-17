"""Pin STU-565's conclusions so the measurement cannot silently rot.

    cd research/death-circumstance-eval && PYTHONPATH=../.. python -m pytest tests/ -q

These are not tests of the feature (that is `tests/test_entity_status.py`). They
assert the *measured result*: what the real gate renders for Eragon's verified
verdicts. If the gate changes and these move, the number in results.md is stale.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))          # eval dir
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))          # repo root

from corpus import TYPING_CACHED, TYPING_REEXTRACT, VERDICTS
from measure import _rendered, measure


def _by_name():
    return {v.name: v for v in VERDICTS}


# --- The headline: false circumstance rate is 0 ------------------------------


def test_no_false_circumstance_in_either_scenario():
    # The metric that matters: not one rendered agent/place is untrue, on the
    # cached roster or a re-extracted one.
    for typing in (TYPING_CACHED, TYPING_REEXTRACT):
        assert measure(typing)["false_fields"] == 0


def test_the_three_named_verdicts_render_no_circumstance_on_the_cached_roster():
    # Brom, Morzan, Marian — the verdicts the ticket names by hand — all render
    # an absent row, which is the outcome STU-552 shipped on.
    v = _by_name()
    for name in ("Brom", "Morzan", "Marian"):
        assert _rendered(v[name], TYPING_CACHED)["label"] is None


# --- Brom: the ticket's "interesting positive" is a negative -----------------


def test_brom_renders_nothing_because_his_killer_is_an_ORG():
    # The novel's killer is the Ra'zac (ORG on the cached extraction), not Durza.
    # agent gated out by type, no place in the quote → absent row.
    brom = _by_name()["Brom"]
    out = _rendered(brom, TYPING_CACHED)
    assert out["agent"] is None and out["place"] is None


def test_the_tickets_false_belief_is_dropped_against_broms_real_quote():
    # "Killed by Durza at Farthen Dûr" is the design doc's synthetic example, not
    # the novel. Fed against Brom's real death sentence, both fields drop: neither
    # name is in the quote. This is why the false-circumstance rate is 0.
    from wiki_creator.entity_status import build_name_index, parse_status_verdict
    from corpus import name_index_entities

    real_quote = '"Brom\'s dead," said Eragon abruptly. "The Ra\'zac killed him."'
    rows = [{"name": "Brom", "aliases": [], "snippets": [{"text": real_quote, "chapter_id": "cN"}]}]
    parsed = parse_status_verdict(
        {"status": [{"name": "Brom", "status": "deceased", "quote": real_quote,
                     "agent": "Durza", "place": "Farthen Dûr"}]},
        rows,
        build_name_index(name_index_entities(TYPING_CACHED)),
    )["Brom"]
    assert "agent" not in parsed and "place" not in parsed
    assert parsed["status"] == "deceased"  # the verdict itself survives


# --- Recall is low by design, and that is the point --------------------------


def test_recall_is_below_full_on_the_cached_roster():
    # The quote/type gates are strict; some stated killers are dropped (Brom's
    # Ra'zac, Vrael's Galbatorix). STU-565: expected non-zero misses, cheap.
    m = measure(TYPING_CACHED)
    assert m["recall_hits"] < m["recall_opportunities"]


def test_a_true_backstory_place_can_still_surface():
    # Tornac died fleeing Urû'baen (a roster PLACE named in the quote). The gates
    # are conservative, not blind: a grounded true field renders.
    out = _rendered(_by_name()["Tornac"], TYPING_CACHED)
    assert out["label"] == "Mort à Urû'baen"


def test_reextraction_lifts_a_true_killer_onto_the_roster():
    # Sensitivity: the finding does not rest on ORG typing. Even when Galbatorix
    # is a PERSON, what renders (Tué par Galbatorix) is true — never false.
    out = _rendered(_by_name()["Vrael"], TYPING_REEXTRACT)
    assert out["label"] == "Tué par Galbatorix"
