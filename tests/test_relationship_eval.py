"""Unit tests for the relationship-classifier eval harness (STU-499). Pure logic."""
from pathlib import Path

import pytest

from wiki_creator import relationship_eval as re

FIXTURE = Path(__file__).parent / "fixtures/relationship_eval/throne-of-glass-01.yaml"


# --------------------------------------------------------------- primitives

def test_pair_key_is_order_insensitive():
    assert re.pair_key("Celaena", "Chaol") == re.pair_key("Chaol", "Celaena")


def test_label_collapses_null_sentinels():
    assert re._label(None) == "null"
    assert re._label("null") == "null"
    assert re._label("") == "null"
    assert re._label("ami") == "ami"


# ---------------------------------------------------------------- gold load

def test_load_gold_parses_fixture():
    gold = re.load_gold(FIXTURE)
    assert len(gold) >= 10
    by_pair = {gp.key: gp for gp in gold}
    chaol = by_pair[re.pair_key("Celaena", "Chaol")]
    assert chaol.primary == "ami"
    assert "allié" in chaol.acceptable
    assert chaol.expects_relation and not chaol.expects_null

    westfall = by_pair[re.pair_key("Westfall", "Kaltain")]
    assert westfall.acceptable == ("null",)
    assert westfall.expects_null and not westfall.expects_relation


def test_load_gold_single_expected_becomes_one_element_tuple():
    gold = re.load_gold(FIXTURE)
    cain = next(gp for gp in gold if gp.key == re.pair_key("Cain", "Celaena"))
    assert cain.acceptable == ("antagoniste",)


# ------------------------------------------------------- predictions parsing

def test_predictions_from_relationships_normalizes_null_sentinel():
    rels = [
        {"entity_a": "Celaena", "entity_b": "Chaol", "relationship_type": "ami"},
        {"entity_a": "Westfall", "entity_b": "Kaltain", "relationship_type": "null"},
        {"entity_a": "A", "entity_b": "B", "relationship_type": None},
        {"entity_b": "no_a", "relationship_type": "ami"},  # malformed → skipped
    ]
    preds = re.predictions_from_relationships(rels)
    assert preds[re.pair_key("Celaena", "Chaol")] == "ami"
    assert preds[re.pair_key("Westfall", "Kaltain")] is None
    assert preds[re.pair_key("A", "B")] is None
    assert len(preds) == 3


# --------------------------------------------------------------- scoring

def _gold(*specs):
    return [re.GoldPair(a, b, tuple(acc)) for a, b, acc in specs]


def test_score_perfect():
    gold = _gold(
        ("Celaena", "Chaol", ["ami"]),
        ("Cain", "Celaena", ["antagoniste"]),
        ("Westfall", "Kaltain", ["null"]),
    )
    preds = {
        re.pair_key("Celaena", "Chaol"): "ami",
        re.pair_key("Cain", "Celaena"): "antagoniste",
        re.pair_key("Westfall", "Kaltain"): None,
    }
    m = re.score(gold, preds)
    assert m["overall_accuracy"] == 1.0
    assert m["type_accuracy"] == 1.0
    assert m["false_null_rate"] == 0.0
    assert m["hallucination_rate"] == 0.0
    assert m["missing"] == []


def test_score_false_null():
    """A typed pair predicted null counts as false_null, not hallucination."""
    gold = _gold(("Brullo", "Celaena", ["mentor/protégé"]))
    m = re.score(gold, {re.pair_key("Brullo", "Celaena"): None})
    assert m["false_null_count"] == 1
    assert m["false_null_rate"] == 1.0
    assert m["hallucination_count"] == 0
    assert m["rows"][0].verdict == "false_null"


def test_score_hallucination():
    """A must-stay-null pair predicted a type counts as hallucination."""
    gold = _gold(("Westfall", "Kaltain", ["null"]))
    m = re.score(gold, {re.pair_key("Westfall", "Kaltain"): "ami"})
    assert m["hallucination_count"] == 1
    assert m["hallucination_rate"] == 1.0
    assert m["false_null_count"] == 0
    assert m["rows"][0].verdict == "hallucination"


def test_score_wrong_type():
    gold = _gold(("Cain", "Celaena", ["antagoniste"]))
    m = re.score(gold, {re.pair_key("Cain", "Celaena"): "ami"})
    assert m["wrong_type_count"] == 1
    assert m["false_null_count"] == 0
    assert m["hallucination_count"] == 0
    assert m["rows"][0].verdict == "wrong_type"


def test_score_acceptable_alternate_credited_to_primary():
    """An acceptable non-primary answer scores as correct and lands on the primary class."""
    gold = _gold(("Celaena", "Chaol", ["ami", "allié"]))
    m = re.score(gold, {re.pair_key("Celaena", "Chaol"): "allié"})
    assert m["type_accuracy"] == 1.0
    assert m["rows"][0].verdict == "ok"
    # credited to primary "ami", not counted against "allié"
    assert m["per_class"]["ami"].tp == 1
    assert "allié" not in m["per_class"] or m["per_class"]["allié"].fp == 0


def test_score_missing_prediction_flagged_and_scored_as_null():
    gold = _gold(
        ("Celaena", "Chaol", ["ami"]),
        ("Westfall", "Kaltain", ["null"]),
    )
    m = re.score(gold, {re.pair_key("Westfall", "Kaltain"): None})
    assert [gp.key for gp in m["missing"]] == [re.pair_key("Celaena", "Chaol")]
    # missing typed pair scored as null → false_null
    assert m["false_null_count"] == 1


def test_per_class_precision_recall():
    gold = _gold(
        ("A", "B", ["ami"]),
        ("C", "D", ["ami"]),
        ("E", "F", ["antagoniste"]),
    )
    preds = {
        re.pair_key("A", "B"): "ami",          # tp ami
        re.pair_key("C", "D"): "antagoniste",  # ami→antagoniste: fn ami, fp antagoniste
        re.pair_key("E", "F"): "antagoniste",  # tp antagoniste
    }
    m = re.score(gold, preds)
    ami = m["per_class"]["ami"]
    assert ami.tp == 1 and ami.fn == 1
    assert ami.recall == 0.5
    assert ami.precision == 1.0
    anta = m["per_class"]["antagoniste"]
    assert anta.tp == 1 and anta.fp == 1
    assert anta.precision == 0.5


# --------------------------------------------------------------- report

def test_render_report_has_headline_rates_and_pairs():
    gold = _gold(
        ("Brullo", "Celaena", ["mentor/protégé"]),
        ("Westfall", "Kaltain", ["null"]),
    )
    preds = {
        re.pair_key("Brullo", "Celaena"): None,   # false_null
        re.pair_key("Westfall", "Kaltain"): "ami",  # hallucination
    }
    report = re.render_report("throne-of-glass-01", re.score(gold, preds))
    assert "False-null rate" in report
    assert "Hallucination rate" in report
    assert "Brullo ↔ Celaena" in report
    assert "false_null" in report
    assert "hallucination" in report


def test_render_report_on_real_fixture_all_correct():
    """Sanity: the fixture scores 100% against a gold-mirroring prediction set."""
    gold = re.load_gold(FIXTURE)
    preds = {gp.key: (None if gp.expects_null else gp.primary) for gp in gold}
    m = re.score(gold, preds)
    assert m["overall_accuracy"] == 1.0
    assert m["false_null_rate"] == 0.0
    assert m["hallucination_rate"] == 0.0
