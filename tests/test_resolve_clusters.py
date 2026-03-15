"""Tests for scripts/resolve_clusters.py — noise_words handling."""
from scripts.resolve_clusters import is_relevant, _NOISE_WORDS


def test_is_relevant_respects_custom_noise_words():
    custom = frozenset({"testword"})
    assert not is_relevant("Testword", noise_words=custom)
    assert is_relevant("Testword")  # not in default noise_words


def test_default_noise_words_contains_en_and_fr():
    assert "yes" in _NOISE_WORDS   # English
    assert "oui" in _NOISE_WORDS   # French
