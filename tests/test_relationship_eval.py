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
    assert chaol.primary == "strained_friendship"
    assert "budding_attraction" in chaol.acceptable
    assert chaol.expects_relation and not chaol.expects_null

    westfall = by_pair[re.pair_key("Westfall", "Kaltain")]
    assert westfall.acceptable == ("null",)
    assert westfall.expects_null and not westfall.expects_relation


def test_load_gold_single_expected_becomes_one_element_tuple():
    gold = re.load_gold(FIXTURE)
    cain = next(gp for gp in gold if gp.key == re.pair_key("Cain", "Celaena"))
    assert cain.acceptable == ("antagonist",)


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


# ------------------------------------------------- confidence grading (STU-476)

def test_load_gold_reads_max_confidence_and_leaves_ungraded_pairs_none():
    gold = re.load_gold(FIXTURE)
    by_pair = {gp.key: gp for gp in gold}
    assert by_pair[re.pair_key("Celaena", "Dorian")].max_confidence == "inferred"
    assert by_pair[re.pair_key("Westfall", "Kaltain")].max_confidence is None


def test_confidences_from_relationships_normalizes():
    rels = [
        {"entity_a": "A", "entity_b": "B", "confidence": "Explicit"},
        {"entity_a": "C", "entity_b": "D", "confidence": None},
        {"entity_b": "no_a", "confidence": "explicit"},
    ]
    conf = re.confidences_from_relationships(rels)
    assert conf[re.pair_key("A", "B")] == "explicit"
    assert conf[re.pair_key("C", "D")] is None
    assert len(conf) == 2


def _graded(*specs):
    return [
        re.GoldPair(a, b, ("friend",), max_confidence=mc) for a, b, mc in specs
    ]


def test_score_confidence_flags_a_stronger_claim_than_the_excerpts_support():
    gold = _graded(("Celaena", "Dorian", "inferred"))
    m = re.score_confidence(gold, {re.pair_key("Celaena", "Dorian"): "explicit"})
    assert m["overgraded_count"] == 1
    assert m["overgraded_rate"] == 1.0
    assert m["rows"][0].verdict == "overgraded"


def test_score_confidence_does_not_penalize_a_weaker_grade():
    gold = _graded(("A", "B", "explicit"))
    m = re.score_confidence(gold, {re.pair_key("A", "B"): "interpretation"})
    assert m["overgraded_count"] == 0
    assert m["rows"][0].verdict == "ok"


def test_score_confidence_counts_a_missing_grade_as_ungraded_not_overgraded():
    gold = _graded(("A", "B", "inferred"))
    m = re.score_confidence(gold, {})
    assert m["ungraded_count"] == 1
    assert m["overgraded_count"] == 0


def test_score_confidence_skips_pairs_the_gold_leaves_ungraded():
    gold = _graded(("A", "B", None))
    m = re.score_confidence(gold, {re.pair_key("A", "B"): "explicit"})
    assert m["scored"] == 0
    assert m["overgraded_rate"] == 0.0


def test_render_report_appends_the_confidence_section():
    gold = _graded(("Celaena", "Dorian", "inferred"))
    metrics = re.score(gold, {re.pair_key("Celaena", "Dorian"): "friend"})
    conf = re.score_confidence(gold, {re.pair_key("Celaena", "Dorian"): "explicit"})
    report = re.render_report("throne-of-glass-01", metrics, conf)
    assert "Over-graded rate" in report
    assert "overgraded" in report


def test_render_report_omits_the_confidence_section_when_nothing_is_graded():
    gold = _graded(("A", "B", None))
    metrics = re.score(gold, {re.pair_key("A", "B"): "friend"})
    report = re.render_report("x", metrics, re.score_confidence(gold, {}))
    assert "Over-graded rate" not in report


def test_fixture_grades_score_clean_against_a_gold_mirroring_prediction_set():
    gold = re.load_gold(FIXTURE)
    conf = {gp.key: gp.max_confidence for gp in gold if gp.max_confidence}
    m = re.score_confidence(gold, conf)
    assert m["scored"] >= 10
    assert m["overgraded_count"] == 0
    assert m["ungraded_count"] == 0
