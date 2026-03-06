import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.copyright_check import tokenize, mask_short_quotes


def test_tokenize_lowercases_and_strips_punctuation():
    tokens = tokenize("David Martín entra, les mains vides.")
    assert tokens == ["david", "martín", "entra", "les", "mains", "vides"]


def test_tokenize_handles_newlines_and_extra_spaces():
    tokens = tokenize("Il entra.\n\nElle sortit.  Voilà.")
    assert tokens == ["il", "entra", "elle", "sortit", "voilà"]


def test_mask_short_quotes_french_guillemets():
    text = "Il dit « bonjour ami » et repartit."
    result = mask_short_quotes(text, max_words=5)
    assert "bonjour" not in result
    assert "Il dit" in result
    assert "et repartit" in result


def test_mask_short_quotes_preserves_long_quotes():
    # 6 words — should NOT be masked
    text = "Il cria « un deux trois quatre cinq six » dans la nuit."
    result = mask_short_quotes(text, max_words=5)
    assert "un deux trois quatre cinq six" in result


def test_mask_short_quotes_double_quotes():
    text = 'Elle murmura "mon dieu" et ferma les yeux.'
    result = mask_short_quotes(text, max_words=5)
    assert "mon dieu" not in result
