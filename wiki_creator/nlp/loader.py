"""Shared spaCy loading: fallback candidates + guaranteed sentencizer.

Single home for logic previously duplicated across entity_extraction.py,
relationship_extraction.py, and standalone test scripts (STU-446). Prepares
M3, where this loader becomes the single entry point for per-language models.
"""

from __future__ import annotations

import sys
from collections.abc import Callable

# Generic stock-model fallbacks per language, tried after any name-prefix
# fallbacks. Lets a non-standard requested model (a local path, a community
# model) still degrade to a working stock model when its language is known
# (STU-453).
_GENERIC_FALLBACKS = {
    "en": ["en_core_web_sm"],
    "fr": ["fr_core_news_lg", "fr_core_news_sm"],
}


def spacy_model_candidates(requested_model: str, language: str | None = None) -> list[str]:
    """Return ordered candidate models for robust loading.

    Name-prefix fallbacks come first (a smaller sibling of the same family).
    When *language* is known, its generic stock-model fallbacks are appended so
    a non-standard model name (local path, community model) can still degrade.
    """
    candidates = [requested_model]
    if requested_model.startswith("en_core_web_") and requested_model != "en_core_web_sm":
        candidates.append("en_core_web_sm")
    if requested_model.startswith("fr_core_news_"):
        if requested_model != "fr_core_news_lg":
            candidates.append("fr_core_news_lg")
        if requested_model != "fr_core_news_sm":
            candidates.append("fr_core_news_sm")
    if language:
        candidates.extend(_GENERIC_FALLBACKS.get(language, []))
    # De-duplicate while preserving order.
    return list(dict.fromkeys(candidates))


def describe_pipeline(nlp) -> dict:
    """Introspect a loaded pipeline: components present and NER labels emitted."""
    ner_labels = sorted(nlp.get_pipe("ner").labels) if "ner" in nlp.pipe_names else []
    return {"components": list(nlp.pipe_names), "ner_labels": ner_labels}


def log_pipeline(nlp, model_name: str) -> None:
    """Log the loaded pipeline's components and NER labels to stderr (STU-453).

    Surfaces a half-disconnected model — no ner/parser, or an ner emitting no
    labels — at load time instead of chapters into a run (STU-439).
    """
    info = describe_pipeline(nlp)
    print(
        f"[nlp] loaded '{model_name}' components={info['components']} "
        f"ner_labels={info['ner_labels']}",
        file=sys.stderr,
    )
    if "ner" not in info["components"]:
        print(
            f"[WARN] model '{model_name}' has no NER component; entity extraction will be empty",
            file=sys.stderr,
        )
    elif not info["ner_labels"]:
        print(f"[WARN] model '{model_name}' NER component emits no labels", file=sys.stderr)


def ensure_sentencizer(nlp) -> None:
    """Add a sentencizer to *nlp* if no sentence-boundary component is present.

    Fine-tuned models trained with only tok2vec+ner don't include a parser or
    senter, so doc.sents raises E030. Adding a sentencizer fixes this without
    altering NER behaviour.
    """
    if not any(p in nlp.pipe_names for p in ("parser", "senter", "sentencizer")):
        nlp.add_pipe("sentencizer", first=True)


def load_spacy_model_with_fallback(
    spacy_load: Callable, requested_model: str, language: str | None = None
):
    """Try requested spaCy model, then language-appropriate fallbacks."""
    errors = []
    for model in spacy_model_candidates(requested_model, language):
        try:
            return spacy_load(model), model
        except OSError as exc:
            errors.append(f"{model}: {exc}")
    raise OSError("Unable to load spaCy model. Tried: " + " | ".join(errors))


def load_spacy_model(requested_model: str, language: str | None = None, **spacy_load_kwargs):
    """Load requested_model with fallback candidates, guaranteeing a sentencizer.

    Convenience wrapper around load_spacy_model_with_fallback for callers
    that don't need to inject their own spacy.load callable.
    """
    import spacy

    nlp, loaded_model = load_spacy_model_with_fallback(
        lambda model: spacy.load(model, **spacy_load_kwargs), requested_model, language
    )
    ensure_sentencizer(nlp)
    log_pipeline(nlp, loaded_model)
    return nlp, loaded_model
