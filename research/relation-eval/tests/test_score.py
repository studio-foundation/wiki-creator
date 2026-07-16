import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from score import gold_support, score


def gold(a, b, acceptable, direction="symétrique", implicit=False):
    return {"entity_a": a, "entity_b": b, "acceptable": acceptable,
            "direction": direction, "implicit": implicit}


def pred(a, b, rel_type, direction="symétrique"):
    return {"entity_a": a, "entity_b": b, "relationship_type": rel_type, "direction": direction}


def test_a_pair_found_and_typed_right_scores_everywhere():
    r = score([gold("Brom", "Eragon", ["mentor"], "A→B")],
              [pred("Brom", "Eragon", "mentor", "A→B")])
    o = r["overall"]
    assert o["detection"]["f1"] == 1.0
    assert o["typing"]["accuracy_end_to_end"] == 1.0
    assert o["direction"] == {"accuracy": 1.0, "n": 1}


def test_pair_order_does_not_have_to_match_the_gold():
    r = score([gold("Brom", "Eragon", ["mentor"])], [pred("Eragon", "Brom", "mentor")])
    assert r["overall"]["detection"]["recall"] == 1.0


def test_an_acceptable_alternate_counts_as_a_hit():
    r = score([gold("Eragon", "Murtagh", ["wary_alliance", "friend"])],
              [pred("Eragon", "Murtagh", "friend")])
    assert r["overall"]["typing"]["accuracy_end_to_end"] == 1.0


def test_an_alternate_reports_its_support_under_the_primary_not_itself():
    # Otherwise per-type support stops summing to the gold's own distribution.
    r = score([gold("Eragon", "Murtagh", ["wary_alliance", "friend"])],
              [pred("Eragon", "Murtagh", "friend")])
    per_type = r["overall"]["typing"]["per_type"]
    assert per_type["wary_alliance"]["tp"] == 1
    assert "friend" not in per_type


def test_detection_ignores_the_type_but_typing_does_not():
    r = score([gold("Brom", "Eragon", ["mentor"])], [pred("Brom", "Eragon", "antagonist")])
    assert r["overall"]["detection"]["f1"] == 1.0
    assert r["overall"]["typing"]["accuracy_end_to_end"] == 0.0


def test_an_undiscovered_pair_is_a_typing_miss_end_to_end():
    r = score([gold("Brom", "Eragon", ["mentor"])], [])
    assert r["overall"]["detection"]["recall"] == 0.0
    assert r["overall"]["typing"]["accuracy_end_to_end"] == 0.0
    assert r["overall"]["typing"]["per_type"]["mentor"]["fn"] == 1
    assert r["missed"] == [("Brom", "Eragon")]


def test_conditional_typing_ignores_pairs_the_arm_never_found():
    # The number that flatters low recall: one pair found, typed right, 1.0 —
    # while end-to-end sees the pair it missed.
    r = score([gold("Brom", "Eragon", ["mentor"]), gold("Eragon", "Garrow", ["family"])],
              [pred("Brom", "Eragon", "mentor")])
    assert r["overall"]["typing_conditional"] == {"accuracy": 1.0, "n": 1}
    assert r["overall"]["typing"]["accuracy_end_to_end"] == 0.5


def test_conditional_typing_is_none_when_the_arm_found_nothing():
    r = score([gold("Brom", "Eragon", ["mentor"])], [])
    assert r["overall"]["typing_conditional"] is None


def test_a_predicted_pair_absent_from_the_gold_is_over_connection():
    r = score([gold("Brom", "Eragon", ["mentor"])],
              [pred("Brom", "Eragon", "mentor"), pred("Eragon", "Horst", "friend")])
    assert r["overall"]["detection"]["fp"] == 1
    assert r["overall"]["detection"]["precision"] == 0.5
    assert r["over_connected"] == [("Eragon", "Horst")]


def test_a_type_the_reader_would_never_see_scores_as_no_type():
    # STU-501: "null"/None never reach a page, so they cannot earn typing credit.
    for junk in (None, "null", "none", ""):
        r = score([gold("Brom", "Eragon", ["mentor"])], [pred("Brom", "Eragon", junk)])
        assert r["overall"]["detection"]["f1"] == 1.0, junk
        assert r["overall"]["typing"]["accuracy_end_to_end"] == 0.0, junk


def test_direction_is_scored_only_on_correctly_typed_pairs():
    # Right direction, wrong type: not partial credit, a different claim.
    r = score([gold("Brom", "Eragon", ["mentor"], "A→B")],
              [pred("Brom", "Eragon", "antagonist", "A→B")])
    assert r["overall"]["direction"] is None


def test_direction_counts_a_mismatch():
    r = score([gold("Brom", "Eragon", ["mentor"], "A→B")],
              [pred("Brom", "Eragon", "mentor", "B→A")])
    assert r["overall"]["direction"] == {"accuracy": 0.0, "n": 1}


def test_strata_partition_the_gold():
    g = [gold("Brom", "Eragon", ["mentor"]), gold("Eragon", "Garrow", ["family"], implicit=True)]
    r = score(g, [pred("Brom", "Eragon", "mentor")])
    assert r["explicit"]["n_gold"] == 1
    assert r["implicit"]["n_gold"] == 1
    assert r["overall"]["n_gold"] == 2
    # The charge under test: the explicit pair is found, the implicit one is not.
    assert r["explicit"]["detection"]["recall"] == 1.0
    assert r["implicit"]["detection"]["recall"] == 0.0


def test_empty_denominators_are_none_not_zero():
    r = score([], [])
    assert r["overall"]["detection"]["precision"] is None
    assert r["overall"]["typing"]["accuracy_end_to_end"] is None


def test_gold_support_counts_the_primary_in_declaration_order():
    g = [gold("Eragon", "Murtagh", ["wary_alliance", "friend"]),
         gold("Brom", "Eragon", ["mentor"])]
    assert gold_support(g) == {"wary_alliance": 1, "mentor": 1}
