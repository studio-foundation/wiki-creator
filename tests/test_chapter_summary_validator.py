from scripts.chapter_summary_validator import check_temporal_context, check_bullets_not_empty, validate_summary

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
