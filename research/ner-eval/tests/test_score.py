import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from score import gold_support, score  # noqa: E402


def case(cid, spans):
    return {cid: {"id": cid, "spans": [
        {"start": s, "end": e, "label": lb} for s, e, lb in spans]}}


def test_perfect_prediction_scores_one_everywhere():
    gold = case("a", [(0, 7, "PERSON")])
    got = score(gold, case("a", [(0, 7, "PERSON")]))
    for axis in got.values():
        assert axis["global"]["f1"] == 1.0


def test_right_span_wrong_label_is_detection_hit_and_typing_miss():
    gold = case("a", [(0, 7, "FACTION")])
    got = score(gold, case("a", [(0, 7, "ORG")]))

    assert got["detection_overlap"]["global"]["f1"] == 1.0
    assert got["typing_overlap"]["global"]["f1"] == 0.0
    # The miss is charged to both sides: FN against gold's type, FP against the
    # predicted type. This is what separates a typing error from a hallucination.
    assert got["typing_overlap"]["per_type"]["FACTION"]["fn"] == 1
    assert got["typing_overlap"]["per_type"]["ORG"]["fp"] == 1


def test_partial_span_passes_overlap_and_fails_exact():
    gold = case("a", [(0, 16, "PERSON")])  # "Eragon Bromsson"
    got = score(gold, case("a", [(0, 6, "PERSON")]))  # "Eragon"

    assert got["detection_overlap"]["global"]["recall"] == 1.0
    assert got["detection_exact"]["global"]["recall"] == 0.0


def test_hallucinated_span_is_precision_only_penalty():
    gold = case("a", [(0, 6, "PERSON")])
    got = score(gold, case("a", [(0, 6, "PERSON"), (50, 60, "PLACE")]))

    assert got["detection_overlap"]["global"]["recall"] == 1.0
    assert got["detection_overlap"]["global"]["precision"] == 0.5
    assert got["detection_overlap"]["per_type"]["PLACE"]["fp"] == 1


def test_missing_case_in_predictions_counts_as_all_false_negatives():
    gold = case("a", [(0, 6, "PERSON")])
    got = score(gold, {})

    assert got["detection_overlap"]["global"]["recall"] == 0.0
    assert got["detection_overlap"]["per_type"]["PERSON"]["fn"] == 1


def test_one_prediction_covering_two_gold_spans_hits_both():
    gold = case("a", [(0, 6, "PERSON"), (7, 15, "PERSON")])
    got = score(gold, case("a", [(0, 15, "PERSON")]))

    assert got["detection_overlap"]["recall_global"] == 1.0


def test_gold_support_counts_spans_per_type():
    gold = {}
    gold.update(case("a", [(0, 6, "PERSON"), (7, 15, "PLACE")]))
    gold.update(case("b", [(0, 6, "PERSON")]))

    assert gold_support(gold) == {"PERSON": 2, "PLACE": 1}


def test_empty_gold_does_not_divide_by_zero():
    got = score(case("a", []), case("a", []))
    assert got["detection_overlap"]["global"]["f1"] == 0.0
    assert got["detection_overlap"]["recall_global"] == 0.0
