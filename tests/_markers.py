"""Shared pytest skip markers for tests that need optional local artifacts.

The test suite must stay hermetic: tests depending on a spaCy model or on
the optional fastcoref extra skip cleanly when the artifact is absent,
instead of failing on a fresh clone or in CI.
"""
import importlib.util

import pytest


def spacy_model_available(name: str) -> bool:
    try:
        import spacy.util
        return spacy.util.is_package(name)
    except Exception:
        return False


def fastcoref_available() -> bool:
    return importlib.util.find_spec("fastcoref") is not None


requires_en_sm = pytest.mark.skipif(
    not spacy_model_available("en_core_web_sm"),
    reason="requires spaCy model en_core_web_sm (python -m spacy download en_core_web_sm)",
)

requires_fr_lg = pytest.mark.skipif(
    not spacy_model_available("fr_core_news_lg"),
    reason="requires spaCy model fr_core_news_lg (python -m spacy download fr_core_news_lg)",
)

requires_fastcoref = pytest.mark.skipif(
    not fastcoref_available(),
    reason="requires the coref extra (pip install -e '.[coref]')",
)
