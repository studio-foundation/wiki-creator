from scripts.chapter_summary_validator import (
    check_temporal_context,
    check_bullets_not_empty,
    check_grounding,
    validate_summary,
)

CHAPTER_TEXT = (
    "Celaena Sardothien est escortée hors des mines d'Endovier par le "
    "capitaine Chaol Westfall. Le prince Dorian l'observe. Duke Perrington "
    "les accompagne jusqu'à Rifthold. Nehemia n'est pas encore arrivée."
)


def _meta():
    return {"chapter_content": CHAPTER_TEXT}


def test_grounding_flags_invented_name():
    summary = {"summary_bullets": ["Le Duke of Niflaren trahit le roi Eadmund."]}
    errors = check_grounding(summary, _meta())
    assert errors != []
    assert "Niflaren" in errors[0]
    assert "Eadmund" in errors[0]


def test_grounding_passes_real_names():
    summary = {"summary_bullets": ["Celaena quitte Endovier avec Chaol et Dorian."]}
    assert check_grounding(summary, _meta()) == []


def test_grounding_ignores_sentence_initial_common_word():
    # "Elle"/"Le" are capitalized at sentence start but appear lowercased in text.
    summary = {"summary_bullets": ["Elle quitte les mines. Le capitaine la suit."]}
    assert check_grounding(summary, _meta()) == []


def test_grounding_handles_possessive():
    summary = {"summary_bullets": ["Celaena's escape from Endovier begins."]}
    # "Celaena" and "Endovier" are in the text; "s" is lowercase and skipped.
    assert check_grounding(summary, _meta()) == []


def test_grounding_handles_accented_name():
    summary = {"summary_bullets": ["Nehemia arrivera bientôt à Rifthold."]}
    assert check_grounding(summary, _meta()) == []


def test_grounding_graceful_without_chapter_text():
    summary = {"summary_bullets": ["Le Duke of Niflaren trahit le roi Eadmund."]}
    assert check_grounding(summary, {}) == []


def test_validate_summary_rejects_hallucinated_names():
    summary = {
        "temporal_context": "present",
        "summary_bullets": ["Le Duke of Niflaren rejoint King Davoth."],
    }
    result = validate_summary(summary, _meta())
    assert result["valid"] is False
    assert any("Niflaren" in e for e in result["errors"])

def test_check_temporal_context_missing():
    summary = {"temporal_context": None, "summary_bullets": ["Bullet 1"]}
    errors = check_temporal_context(summary)
    assert errors != []

def test_check_temporal_context_present():
    summary = {"temporal_context": "present", "summary_bullets": ["Bullet 1"]}
    assert check_temporal_context(summary) == []

def test_check_bullets_not_empty():
    summary = {"summary_bullets": []}
    errors = check_bullets_not_empty(summary)
    assert errors != []

def test_check_bullets_not_empty_passes():
    summary = {"summary_bullets": ["Celaena sort des mines."]}
    assert check_bullets_not_empty(summary) == []

def test_validate_summary_valid():
    summary = {
        "temporal_context": "present",
        "summary_bullets": ["Celaena est escortée hors d'Endovier."],
    }
    result = validate_summary(summary, meta={})
    assert result["valid"] is True

def test_validate_summary_invalid():
    summary = {"temporal_context": None, "summary_bullets": []}
    result = validate_summary(summary, meta={})
    assert result["valid"] is False
    assert len(result["errors"]) >= 2
