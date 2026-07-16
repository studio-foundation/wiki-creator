from wiki_creator.confidence import (
    EXPLICIT,
    INFERRED,
    INTERPRETATION,
    is_stronger,
    relationship_confidence,
)
from wiki_creator.page_templates import confidence_tokens


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


def test_classifier_grade_stands_when_evidence_anchors_it():
    """STU-476: the classifier read the excerpts; its grade is the answer."""
    rel = {
        "relationship_type": "romance",
        "evidence": "Their eyes met, and Chaol didn't hide his smile as she grinned at him.",
        "confidence": INTERPRETATION,
    }
    assert relationship_confidence(rel) == INTERPRETATION


def test_ungrounded_type_is_inferred_whatever_grade_it_claims():
    """The deterministic floor no grade may lift: no evidence, never explicit."""
    rel = {"relationship_type": "romance", "evidence": "", "confidence": EXPLICIT}
    assert relationship_confidence(rel) == INFERRED


def test_unknown_grade_falls_back_to_explicit_evidence_reading():
    rel = {"relationship_type": "ami", "evidence": "X et Y.", "confidence": "certain"}
    assert relationship_confidence(rel) == EXPLICIT


def test_grade_is_case_insensitive():
    rel = {"relationship_type": "ami", "evidence": "X et Y.", "confidence": "Interpretation"}
    assert relationship_confidence(rel) == INTERPRETATION


def test_base_yaml_declares_exactly_the_code_tiers():
    """The prompt vocabulary and the code constants are one thing (STU-476)."""
    assert set(confidence_tokens()) == {EXPLICIT, INFERRED, INTERPRETATION}


def test_is_stronger_orders_the_tiers():
    assert is_stronger(EXPLICIT, INFERRED)
    assert is_stronger(INFERRED, INTERPRETATION)
    assert not is_stronger(INTERPRETATION, EXPLICIT)
    assert not is_stronger(EXPLICIT, EXPLICIT)


def test_is_stronger_treats_an_unknown_tier_as_weakest():
    assert not is_stronger("certain", INTERPRETATION)
