"""Tests for wiki_creator/pov_attribution.py."""
from wiki_creator.pov_attribution import attribute_pov_character

MARKERS = ("thought", "wondered", "realized", "felt")
EXCLUDE = ("the", "and", "she", "he", "lord", "king")


def test_omniscient_returns_none():
    """Omniscient POV has no single focal character."""
    out = attribute_pov_character("Chaol Chaol Chaol wondered.", "omniscient", MARKERS, EXCLUDE)
    assert out == {"pov_character": None, "pov_character_confidence": "low"}


def test_empty_content_returns_none():
    out = attribute_pov_character("", "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character"] is None


def test_dominant_character_high_confidence():
    """One clearly dominant name near thought markers → high + that name."""
    text = (
        "Chaol wondered about the plan. Chaol felt uneasy. Chaol realized the truth. "
        "Chaol watched the door and thought of home."
    )
    out = attribute_pov_character(text, "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character"] == "Chaol"
    assert out["pov_character_confidence"] == "high"


def test_two_equal_names_not_high():
    """No dominant candidate → not high (medium or low), never a false 'high'."""
    text = "Chaol spoke. Dorian answered. Chaol left. Dorian stayed."
    out = attribute_pov_character(text, "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character_confidence"] != "high"


def test_excluded_words_not_chosen():
    """Title-cased stopwords/roles from cue-words are never the focal character."""
    text = "The The The Lord Lord King King. Celaena felt cold. Celaena felt tired. Celaena moved."
    out = attribute_pov_character(text, "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character"] == "Celaena"


def test_frequent_place_name_not_high_without_marker_adjacency():
    """A frequently-named place must not win 'high' when it never sits beside a
    thought marker — the focal character (here hidden behind pronouns) does. The
    markers cluster up front (no name near them); the place dominates by raw
    frequency far away, so it stays below 'high'."""
    text = (
        "She felt uneasy and she wondered and she realized much. "
        "Then came a wholly separate distant later passage where the place mattered. "
        "Adarlan rose. Adarlan fell. Adarlan stood. Adarlan waited."
    )
    out = attribute_pov_character(text, "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character"] == "Adarlan"  # it does win on frequency...
    assert out["pov_character_confidence"] != "high"  # ...but never with 'high' certainty


def test_marker_adjacent_name_still_high():
    """The regression guard must not block a genuinely focal, marker-adjacent name."""
    text = (
        "Celaena wondered. Celaena felt cold. Celaena realized the plan. "
        "Celaena thought of escape."
    )
    out = attribute_pov_character(text, "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character"] == "Celaena"
    assert out["pov_character_confidence"] == "high"
