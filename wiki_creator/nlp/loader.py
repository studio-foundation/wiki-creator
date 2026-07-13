"""Shared spaCy loading: fallback candidates + guaranteed sentencizer.

Single home for logic previously duplicated across entity_extraction.py,
relationship_extraction.py, and standalone test scripts (STU-446). Prepares
M3, where this loader becomes the single entry point for per-language models.
"""

from __future__ import annotations

from collections.abc import Callable


def spacy_model_candidates(requested_model: str) -> list[str]:
    """Return ordered candidate models for robust loading."""
    candidates = [requested_model]
    if requested_model.startswith("en_core_web_") and requested_model != "en_core_web_sm":
        candidates.append("en_core_web_sm")
    if requested_model.startswith("fr_core_news_"):
        if requested_model != "fr_core_news_lg":
            candidates.append("fr_core_news_lg")
        if requested_model != "fr_core_news_sm":
            candidates.append("fr_core_news_sm")
    # De-duplicate while preserving order.
    return list(dict.fromkeys(candidates))


def ensure_sentencizer(nlp) -> None:
    """Add a sentencizer to *nlp* if no sentence-boundary component is present.

    Fine-tuned models trained with only tok2vec+ner don't include a parser or
    senter, so doc.sents raises E030. Adding a sentencizer fixes this without
    altering NER behaviour.
    """
    if not any(p in nlp.pipe_names for p in ("parser", "senter", "sentencizer")):
        nlp.add_pipe("sentencizer", first=True)


def load_spacy_model_with_fallback(spacy_load: Callable, requested_model: str):
    """Try requested spaCy model, then language-appropriate fallbacks."""
    errors = []
    for model in spacy_model_candidates(requested_model):
        try:
            return spacy_load(model), model
        except OSError as exc:
            errors.append(f"{model}: {exc}")
    raise OSError("Unable to load spaCy model. Tried: " + " | ".join(errors))


def load_spacy_model(requested_model: str, **spacy_load_kwargs):
    """Load requested_model with fallback candidates, guaranteeing a sentencizer.

    Convenience wrapper around load_spacy_model_with_fallback for callers
    that don't need to inject their own spacy.load callable.
    """
    import spacy

    nlp, loaded_model = load_spacy_model_with_fallback(
        lambda model: spacy.load(model, **spacy_load_kwargs), requested_model
    )
    ensure_sentencizer(nlp)
    return nlp, loaded_model
