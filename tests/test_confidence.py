from wiki_creator.confidence import (
    EXPLICIT,
    INFERRED,
    INTERPRETATION,
    relationship_confidence,
)


def test_classified_with_evidence_is_explicit():
    rel = {"relationship_type": "amoureux", "evidence": "Rowan embrassa Aelin."}
    assert relationship_confidence(rel) == EXPLICIT


def test_classified_without_evidence_is_inferred():
    # Unanchored classification degrades to inferred (grounding synergy).
    rel = {"relationship_type": "amoureux", "evidence": ""}
    assert relationship_confidence(rel) == INFERRED


def test_cooccurrence_only_is_inferred():
    rel = {"relationship_type": None, "cooccurrence_count": 42}
    assert relationship_confidence(rel) == INFERRED


def test_missing_fields_is_inferred():
    assert relationship_confidence({}) == INFERRED


def test_whitespace_evidence_is_inferred():
    rel = {"relationship_type": "ami", "evidence": "   "}
    assert relationship_confidence(rel) == INFERRED


def test_tiers_are_distinct():
    assert len({EXPLICIT, INFERRED, INTERPRETATION}) == 3
