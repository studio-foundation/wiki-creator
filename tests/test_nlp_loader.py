"""Tests for wiki_creator/nlp/loader.py — shared spaCy loading (STU-446)."""
import spacy

from wiki_creator.nlp.loader import (
    spacy_model_candidates,
    load_spacy_model_with_fallback,
    ensure_sentencizer,
)

from _markers import requires_en_sm


def test_spacy_model_candidates_for_english_adds_sm_fallback():
    assert spacy_model_candidates("en_core_web_lg") == ["en_core_web_lg", "en_core_web_sm"]


def test_spacy_model_candidates_for_french_adds_lg_and_sm_fallback():
    assert spacy_model_candidates("fr_core_news_md") == [
        "fr_core_news_md",
        "fr_core_news_lg",
        "fr_core_news_sm",
    ]


def test_spacy_model_candidates_dedupes():
    assert spacy_model_candidates("en_core_web_sm") == ["en_core_web_sm"]


def test_load_spacy_model_with_fallback_uses_second_candidate():
    calls = []

    def fake_load(model_name):
        calls.append(model_name)
        if model_name == "en_core_web_lg":
            raise OSError("missing model")
        if model_name == "en_core_web_sm":
            return {"model": model_name}
        raise OSError("unexpected model")

    nlp, loaded = load_spacy_model_with_fallback(fake_load, "en_core_web_lg")
    assert loaded == "en_core_web_sm"
    assert nlp == {"model": "en_core_web_sm"}
    assert calls == ["en_core_web_lg", "en_core_web_sm"]


def test_load_spacy_model_with_fallback_raises_when_all_candidates_fail():
    def always_fail(model_name):
        raise OSError(f"no such model: {model_name}")

    try:
        load_spacy_model_with_fallback(always_fail, "en_core_web_lg")
        assert False, "expected OSError"
    except OSError as exc:
        assert "en_core_web_lg" in str(exc)
        assert "en_core_web_sm" in str(exc)


def test_ensure_sentencizer_adds_sentencizer_when_missing():
    """A model with no sentence segmenter should get a sentencizer added."""
    nlp = spacy.blank("en")
    assert "sentencizer" not in nlp.pipe_names
    assert "parser" not in nlp.pipe_names
    ensure_sentencizer(nlp)
    assert "sentencizer" in nlp.pipe_names


@requires_en_sm
def test_ensure_sentencizer_skips_when_parser_present():
    """A model with a parser already sets sentence boundaries — don't add sentencizer."""
    nlp = spacy.load("en_core_web_sm")
    assert "parser" in nlp.pipe_names
    ensure_sentencizer(nlp)
    assert "sentencizer" not in nlp.pipe_names


def test_ensure_sentencizer_allows_doc_sents():
    """After ensure_sentencizer, doc.sents must not raise E030."""
    nlp_blank = spacy.blank("en")
    ensure_sentencizer(nlp_blank)
    doc = nlp_blank("Bilbo walked. Frodo ran.")
    sents = list(doc.sents)  # must not raise
    assert len(sents) >= 1
