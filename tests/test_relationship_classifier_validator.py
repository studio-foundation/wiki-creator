from scripts.relationship_classifier_validator import (
    check_relationship_type_valid,
    check_evolution_not_generic,
    validate_classification,
)


def test_check_relationship_type_valid_passes():
    clf = {"relationship_type": "ami", "direction": "symétrique", "evolution": "ils se rapprochent.", "key_moments": ["ch01: rencontre"]}
    assert check_relationship_type_valid(clf) == []


def test_check_relationship_type_valid_unknown():
    clf = {"relationship_type": "rival", "direction": "symétrique", "evolution": "x", "key_moments": []}
    errors = check_relationship_type_valid(clf)
    assert errors != []


def test_check_evolution_not_generic_detects_filler():
    clf = {"evolution": "relation stable dans les extraits fournis"}
    errors = check_evolution_not_generic(clf)
    assert errors != []


def test_check_evolution_not_generic_passes():
    clf = {"evolution": "Leur méfiance mutuelle se transforme en respect."}
    assert check_evolution_not_generic(clf) == []


def test_check_evolution_null_fails():
    clf = {"evolution": None}
    errors = check_evolution_not_generic(clf)
    assert errors != []


def test_validate_classification_valid():
    clf = {
        "relationship_type": "ami",
        "direction": "symétrique",
        "evolution": "Leur complicité grandit au fil des chapitres.",
        "key_moments": ["ch03: ils s'entraînent ensemble"],
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
