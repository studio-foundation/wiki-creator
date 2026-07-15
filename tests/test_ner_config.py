"""Tests for wiki_creator/ner.py — per-book NER backend declaration (STU-521)."""
import pytest

from wiki_creator.ner import GLINER, SPACY, ner_config


def test_absent_ner_block_is_spacy():
    assert ner_config({}).backend == SPACY
    assert ner_config({}).uses_gliner is False


def test_absent_book_config_is_spacy():
    assert ner_config(None).backend == SPACY


def test_gliner_block_selects_gliner_with_defaults():
    cfg = ner_config({"ner": {"backend": "gliner"}})
    assert cfg.uses_gliner
    assert cfg.model == "urchade/gliner_large-v2.1"
    assert cfg.threshold == 0.5


def test_model_and_threshold_are_read():
    cfg = ner_config({"ner": {"backend": GLINER, "model": "urchade/gliner_multi-v2.1",
                              "threshold": 0.35}})
    assert cfg.model == "urchade/gliner_multi-v2.1"
    assert cfg.threshold == 0.35


def test_unknown_backend_raises_rather_than_defaulting():
    with pytest.raises(ValueError, match="ner.backend"):
        ner_config({"ner": {"backend": "flair"}})


def test_unknown_key_raises():
    with pytest.raises(ValueError, match="unknown key"):
        ner_config({"ner": {"backend": "gliner", "labels": {"x": "PERSON"}}})


def test_non_mapping_ner_block_raises():
    with pytest.raises(ValueError, match="must be a mapping"):
        ner_config({"ner": "gliner"})


@pytest.mark.parametrize("threshold", [0, 1.5, -0.2, "0.5", True])
def test_out_of_range_threshold_raises(threshold):
    with pytest.raises(ValueError, match="ner.threshold"):
        ner_config({"ner": {"backend": "gliner", "threshold": threshold}})


def test_threshold_of_one_is_allowed():
    assert ner_config({"ner": {"backend": "gliner", "threshold": 1}}).threshold == 1.0
