"""Tests for wiki_creator/nlp/loader.py — shared spaCy loading (STU-446)."""
import spacy

from wiki_creator.nlp.loader import (
    spacy_model_candidates,
    load_spacy_model_with_fallback,
    ensure_sentencizer,
    describe_pipeline,
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


def test_spacy_model_candidates_for_spanish_adds_lg_and_sm_fallback():
    assert spacy_model_candidates("es_core_news_md") == [
        "es_core_news_md",
        "es_core_news_lg",
        "es_core_news_sm",
    ]


def test_spacy_model_candidates_spanish_non_standard_gets_generic_fallback():
    assert spacy_model_candidates("models/wiki-ner-es/model-best", "es") == [
        "models/wiki-ner-es/model-best",
        "es_core_news_lg",
        "es_core_news_sm",
    ]


def test_spacy_model_candidates_dedupes():
    assert spacy_model_candidates("en_core_web_sm") == ["en_core_web_sm"]


def test_spacy_model_candidates_non_standard_gets_generic_fallback():
    # A local path can't be a prefix match — the generic per-language fallback
    # is what lets it degrade to a working stock model (STU-453).
    assert spacy_model_candidates("models/wiki-ner-fr/model-best", "fr") == [
        "models/wiki-ner-fr/model-best",
        "fr_core_news_lg",
        "fr_core_news_sm",
    ]
    assert spacy_model_candidates("models/wiki-ner-en/model-best", "en") == [
        "models/wiki-ner-en/model-best",
        "en_core_web_sm",
    ]


def test_spacy_model_candidates_generic_fallback_dedupes_with_prefix():
    assert spacy_model_candidates("fr_core_news_md", "fr") == [
        "fr_core_news_md",
        "fr_core_news_lg",
        "fr_core_news_sm",
    ]


def test_load_spacy_model_with_fallback_uses_generic_language_candidate():
    calls = []

    def fake_load(model_name):
        calls.append(model_name)
        if model_name == "fr_core_news_lg":
            return {"model": model_name}
        raise OSError("missing model")

    nlp, loaded = load_spacy_model_with_fallback(
        fake_load, "models/wiki-ner-fr/model-best", language="fr"
    )
    assert loaded == "fr_core_news_lg"
    assert calls == ["models/wiki-ner-fr/model-best", "fr_core_news_lg"]


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


def test_describe_pipeline_reports_components_and_empty_ner_labels():
    """A pipeline with no NER component reports it, not a crash (STU-453)."""
    nlp = spacy.blank("en")
    info = describe_pipeline(nlp)
    assert info["components"] == list(nlp.pipe_names)
    assert info["ner_labels"] == []


def test_describe_pipeline_reports_ner_labels():
    nlp = spacy.blank("en")
    ner = nlp.add_pipe("ner")
    ner.add_label("PERSON")
    ner.add_label("PLACE")
    info = describe_pipeline(nlp)
    assert "ner" in info["components"]
    assert info["ner_labels"] == ["PERSON", "PLACE"]
