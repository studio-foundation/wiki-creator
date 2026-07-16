from scripts.relationship_classifier_validator import (
    check_confidence_graded,
    check_relationship_type_valid,
    check_evolution_not_generic,
    check_evidence_contains_both_names,
    validate_classification,
)


def test_check_relationship_type_valid_passes():
    clf = {"relationship_type": "friend", "direction": "symétrique", "evolution": "ils se rapprochent.", "key_moments": ["ch01: rencontre"]}
    assert check_relationship_type_valid(clf) == []


def test_check_relationship_type_valid_unknown():
    clf = {"relationship_type": "rival", "direction": "symétrique", "evolution": "x", "key_moments": []}
    errors = check_relationship_type_valid(clf)
    assert errors != []


def test_check_evolution_not_generic_detects_filler():
    clf = {"relationship_type": "friend", "evolution": "relation stable dans les extraits fournis"}
    errors = check_evolution_not_generic(clf)
    assert errors != []


def test_check_evolution_not_generic_passes():
    clf = {"relationship_type": "friend", "evolution": "Leur méfiance mutuelle se transforme en respect."}
    assert check_evolution_not_generic(clf) == []


def test_check_evolution_null_passes():
    """evolution: null est explicitement autorisé quand aucune évolution n'est observable."""
    clf = {"relationship_type": "friend", "evolution": None}
    assert check_evolution_not_generic(clf) == []


def test_check_evolution_empty_string_fails():
    """evolution: empty string should fail validation."""
    clf = {"relationship_type": "friend", "evolution": ""}
    errors = check_evolution_not_generic(clf)
    assert errors != []


def test_validate_classification_valid():
    clf = {
        "relationship_type": "friend",
        "direction": "symétrique",
        "evolution": "Leur complicité grandit au fil des chapitres.",
        "key_moments": ["ch03: ils s'entraînent ensemble"],
        "confidence": "explicit",
    }
    result = validate_classification(clf, meta={})
    assert result["valid"] is True


def test_validate_classification_invalid():
    clf = {
        "relationship_type": "rival",
        "direction": "symétrique",
        "evolution": "relation stable dans les extraits fournis",
        "key_moments": [],
    }
    result = validate_classification(clf, meta={})
    assert result["valid"] is False
    assert len(result["errors"]) >= 2


# ---------------------------------------------------------------------------
# STU-287: evidence must mention both entity names
# ---------------------------------------------------------------------------

def test_check_evidence_contains_both_names_passes():
    """Evidence that names both entities passes validation."""
    clf = {"relationship_type": "friend", "evidence": "Chaol escorted Celaena to the training grounds."}
    meta = {"entity_a": "Celaena", "entity_b": "Chaol"}
    assert check_evidence_contains_both_names(clf, meta) == []


def test_check_evidence_missing_entity_b_fails():
    """Evidence that only mentions entity_a must fail."""
    clf = {"relationship_type": "friend", "evidence": "Celaena défiant un adversaire en solitaire."}
    meta = {"entity_a": "Celaena", "entity_b": "Elena"}
    errors = check_evidence_contains_both_names(clf, meta)
    assert errors != []


def test_check_evidence_missing_entity_a_fails():
    """Evidence that only mentions entity_b must fail."""
    clf = {"relationship_type": "friend", "evidence": "Elena apparut dans un couloir sombre."}
    meta = {"entity_a": "Celaena", "entity_b": "Elena"}
    errors = check_evidence_contains_both_names(clf, meta)
    assert errors != []


def test_check_evidence_is_case_insensitive():
    """Name matching in evidence must be case-insensitive."""
    clf = {"relationship_type": "friend", "evidence": "CHAOL et celaena s'entraînèrent."}
    meta = {"entity_a": "Celaena", "entity_b": "Chaol"}
    assert check_evidence_contains_both_names(clf, meta) == []


def test_check_evidence_null_relationship_type_skips_evidence_check():
    """If relationship_type is null (no direct interaction), evidence check is skipped."""
    clf = {"relationship_type": None, "evidence": None}
    meta = {"entity_a": "Celaena", "entity_b": "Gavin"}
    assert check_evidence_contains_both_names(clf, meta) == []


def test_check_evidence_missing_from_clf_fails():
    """If evidence is absent (or empty) but relationship_type is non-null, must fail."""
    clf = {"relationship_type": "friend", "evidence": None}
    meta = {"entity_a": "Celaena", "entity_b": "Chaol"}
    errors = check_evidence_contains_both_names(clf, meta)
    assert errors != []


# ---------------------------------------------------------------------------
# STU-495: role-asymmetric authority relations accept single-name evidence
# ---------------------------------------------------------------------------

def test_check_evidence_asymmetric_accepts_only_role_holder():
    """mentor evidence naming only the role-holder (group-directed) passes."""
    clf = {"relationship_type": "mentor", "evidence": "Brullo shouted at the other Champions."}
    meta = {"entity_a": "Brullo", "entity_b": "Celaena"}
    assert check_evidence_contains_both_names(clf, meta) == []


def test_check_evidence_asymmetric_accepts_only_subordinate():
    """employment evidence naming only the subordinate passes."""
    clf = {"relationship_type": "employment", "evidence": "At lessons Celaena could freely whack him."}
    meta = {"entity_a": "Brullo", "entity_b": "Celaena"}
    assert check_evidence_contains_both_names(clf, meta) == []


def test_check_evidence_asymmetric_fails_when_neither_named():
    """Asymmetric evidence naming neither entity still fails."""
    clf = {"relationship_type": "mentor", "evidence": "The recruits trained all morning."}
    meta = {"entity_a": "Brullo", "entity_b": "Celaena"}
    errors = check_evidence_contains_both_names(clf, meta)
    assert errors != []


def test_check_evidence_symmetric_still_requires_both():
    """Non-asymmetric types (e.g. friend) still require both names."""
    clf = {"relationship_type": "friend", "evidence": "Brullo shouted at the other Champions."}
    meta = {"entity_a": "Brullo", "entity_b": "Celaena"}
    errors = check_evidence_contains_both_names(clf, meta)
    assert errors != []


# ---------------------------------------------------------------------------
# STU-496: structural relationships (evidence_kind=structural) accept one-name evidence
# ---------------------------------------------------------------------------

def test_check_evidence_structural_rivalry_accepts_one_name():
    """Structural rivalry (enemy) with a role line naming only one party passes."""
    clf = {
        "relationship_type": "enemy",
        "evidence_kind": "structural",
        "evidence": "Xavier—the thief from Melisande, a Champion.",
    }
    meta = {"entity_a": "Celaena", "entity_b": "Xavier"}
    assert check_evidence_contains_both_names(clf, meta) == []


def test_check_evidence_structural_mediated_causation_accepts_one_name():
    """Mediated killer/victim (enemy) grounded on a narrator-attributed line passes."""
    clf = {
        "relationship_type": "enemy",
        "evidence_kind": "structural",
        "evidence": "Cain was a demon-summoning psychopath.",
    }
    meta = {"entity_a": "Cain", "entity_b": "Xavier"}
    assert check_evidence_contains_both_names(clf, meta) == []


def test_check_evidence_structural_fails_when_neither_named():
    """Structural evidence naming neither entity still fails — must ground to a real quote."""
    clf = {
        "relationship_type": "enemy",
        "evidence_kind": "structural",
        "evidence": "The competition claimed another victim.",
    }
    meta = {"entity_a": "Cain", "entity_b": "Xavier"}
    assert check_evidence_contains_both_names(clf, meta) != []


def test_check_evidence_enemy_without_structural_flag_requires_both():
    """enemy is NOT asymmetric: absent the structural flag, both names required (guard)."""
    clf = {"relationship_type": "enemy", "evidence": "Xavier—the thief from Melisande."}
    meta = {"entity_a": "Celaena", "entity_b": "Xavier"}
    assert check_evidence_contains_both_names(clf, meta) != []


# STU-287: null relationship_type is a valid response (no direct interaction)

def test_null_relationship_type_is_valid():
    """relationship_type: null is allowed — signals co-occurrence without direct interaction."""
    clf = {
        "relationship_type": None,
        "direction": None,
        "evolution": None,
        "key_moments": [],
        "evidence": None,
    }
    errors = check_relationship_type_valid(clf)
    assert errors == []


def test_validate_classification_valid_when_type_is_null():
    """Full validate_classification passes when relationship_type is null."""
    clf = {
        "relationship_type": None,
        "direction": None,
        "evolution": None,
        "key_moments": [],
        "evidence": None,
    }
    result = validate_classification(clf, meta={"entity_a": "Elena", "entity_b": "Philippa"})
    assert result["valid"] is True


def test_validate_classification_invalid_when_evidence_lacks_entity():
    """validate_classification fails when evidence doesn't mention both entities."""
    clf = {
        "relationship_type": "friend",
        "direction": "symétrique",
        "evolution": "Leur complicité grandit.",
        "key_moments": ["ch01: rencontre"],
        "evidence": "Dorian se battit à l'épée avec Chaol.",
    }
    result = validate_classification(clf, meta={"entity_a": "Elena", "entity_b": "Philippa"})
    assert result["valid"] is False


def test_build_feedback_mentions_evidence():
    """Le message de feedback doit rappeler l'obligation de fournir evidence."""
    from scripts.relationship_classifier_validator import build_feedback
    msg = build_feedback(["❌ evolution générique"])
    assert "evidence" in msg.lower()


# ---------------------------------------------------------------------------
# STU-476: a typed relation carries a graded confidence
# ---------------------------------------------------------------------------


def test_check_confidence_graded_accepts_a_declared_tier():
    assert check_confidence_graded({"relationship_type": "friend", "confidence": "interpretation"}) == []


def test_check_confidence_graded_rejects_a_missing_grade():
    assert check_confidence_graded({"relationship_type": "friend"}) != []


def test_check_confidence_graded_rejects_a_tier_outside_the_vocabulary():
    assert check_confidence_graded({"relationship_type": "friend", "confidence": "certain"}) != []


def test_check_confidence_graded_requires_null_when_the_type_is_null():
    assert check_confidence_graded({"relationship_type": None, "confidence": None}) == []
    assert check_confidence_graded({"relationship_type": None, "confidence": "explicit"}) != []


def test_validate_classification_rejects_an_ungraded_typed_relation():
    clf = {
        "relationship_type": "friend",
        "direction": "symétrique",
        "evolution": "Leur complicité grandit.",
        "key_moments": ["ch03: entraînement"],
    }
    result = validate_classification(clf, meta={})
    assert result["valid"] is False
    assert any("confidence" in e for e in result["errors"])
