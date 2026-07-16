import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aggregate import aggregate, flip

ROSTER = [
    {"canonical_name": "Brom", "aliases": ["Brom"]},
    {"canonical_name": "Eragon", "aliases": ["Eragon"]},
    {"canonical_name": "Garrow", "aliases": ["Garrow"]},
]


def vote(chapter, a, b, rel_type, direction="symétrique", evidence="x"):
    return {
        "chapter_id": chapter,
        "relations": [{
            "entity_a": a, "entity_b": b, "relationship_type": rel_type,
            "direction": direction, "evidence": evidence,
        }],
    }


def test_flip_is_an_involution():
    for d in ("A→B", "B→A", "symétrique"):
        assert flip(flip(d)) == d


def test_direction_is_restated_against_the_sorted_key():
    # The vote says Brom mentors Eragon, naming them (Brom, Eragon) — already the
    # sorted order, so the token survives unflipped.
    pairs, _ = aggregate([vote("ch1", "Brom", "Eragon", "mentor", "A→B")], ROSTER, set())
    assert pairs[0]["entity_a"] == "Brom"
    assert pairs[0]["direction"] == "A→B"


def test_direction_flips_when_the_vote_names_the_pair_reversed():
    # Same claim — Brom mentors Eragon — but named (Eragon, Brom), so "B→A".
    # Sorted, that is (Brom, Eragon), and the token must become "A→B".
    pairs, _ = aggregate([vote("ch1", "Eragon", "Brom", "mentor", "B→A")], ROSTER, set())
    assert (pairs[0]["entity_a"], pairs[0]["entity_b"]) == ("Brom", "Eragon")
    assert pairs[0]["direction"] == "A→B"


def test_both_orderings_of_one_claim_agree_instead_of_cancelling():
    pairs, _ = aggregate(
        [vote("ch1", "Brom", "Eragon", "mentor", "A→B"),
         vote("ch2", "Eragon", "Brom", "mentor", "B→A")],
        ROSTER, set(),
    )
    assert len(pairs) == 1
    assert pairs[0]["direction"] == "A→B"
    assert pairs[0]["chapters"] == ["ch1", "ch2"]


def test_acceptable_is_ordered_by_chapters_evidencing_it():
    votes = [
        vote("ch1", "Eragon", "Garrow", "family"),
        vote("ch2", "Eragon", "Garrow", "mentor"),
        vote("ch3", "Eragon", "Garrow", "family"),
    ]
    pairs, _ = aggregate(votes, ROSTER, set())
    assert pairs[0]["acceptable"] == ["family", "mentor"]


def test_a_vote_naming_an_entity_off_the_roster_is_rejected_not_folded():
    pairs, rejected = aggregate([vote("ch1", "Eragon", "Solembum", "friend")], ROSTER, set())
    assert pairs == []
    assert len(rejected) == 1
    assert "Solembum" in rejected[0]


def test_a_self_pair_is_rejected():
    pairs, rejected = aggregate([vote("ch1", "Eragon", "Eragon", "friend")], ROSTER, set())
    assert pairs == []
    assert "self-pair" in rejected[0]


def test_implicit_is_true_exactly_when_the_pair_shares_no_sentence():
    votes = [
        vote("ch1", "Brom", "Eragon", "mentor"),
        vote("ch1", "Eragon", "Garrow", "family"),
    ]
    pairs, _ = aggregate(votes, ROSTER, explicit_pairs={("Brom", "Eragon")})
    by_key = {(p["entity_a"], p["entity_b"]): p for p in pairs}
    assert by_key[("Brom", "Eragon")]["implicit"] is False
    assert by_key[("Eragon", "Garrow")]["implicit"] is True


def test_without_an_explicit_set_nothing_is_called_implicit():
    # The disarmed default: callers that mean the axis must pass the set.
    pairs, _ = aggregate([vote("ch1", "Brom", "Eragon", "mentor")], ROSTER)
    assert pairs[0]["implicit"] is False
