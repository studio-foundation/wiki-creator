"""Tests for wiki_creator/ner.py — per-book NER declaration (STU-521, STU-537)."""
import pytest

from wiki_creator.ner import ner_config


def test_absent_ner_block_keeps_spacy():
    assert ner_config({}).invented_names is False


def test_absent_book_config_keeps_spacy():
    assert ner_config(None).invented_names is False


def test_invented_names_selects_gliner_with_defaults():
    cfg = ner_config({"ner": {"invented_names": True}})
    assert cfg.invented_names
    assert cfg.model == "urchade/gliner_large-v2.1"
    assert cfg.threshold == 0.5


def test_invented_names_false_keeps_spacy():
    assert ner_config({"ner": {"invented_names": False}}).invented_names is False


def test_model_and_threshold_are_read():
    cfg = ner_config({"ner": {"invented_names": True, "model": "urchade/gliner_multi-v2.1",
                              "threshold": 0.35}})
    assert cfg.model == "urchade/gliner_multi-v2.1"
    assert cfg.threshold == 0.35


@pytest.mark.parametrize("value", ["true", 1, "gliner"])
def test_non_boolean_invented_names_raises(value):
    with pytest.raises(ValueError, match="ner.invented_names"):
        ner_config({"ner": {"invented_names": value}})


def test_retired_backend_key_raises_rather_than_being_ignored():
    with pytest.raises(ValueError, match="unknown key"):
        ner_config({"ner": {"backend": "gliner"}})


def test_unknown_key_raises():
    with pytest.raises(ValueError, match="unknown key"):
        ner_config({"ner": {"invented_names": True, "labels": {"x": "PERSON"}}})


def test_non_mapping_ner_block_raises():
    with pytest.raises(ValueError, match="must be a mapping"):
        ner_config({"ner": "gliner"})


@pytest.mark.parametrize("threshold", [0, 1.5, -0.2, "0.5", True])
def test_out_of_range_threshold_raises(threshold):
    with pytest.raises(ValueError, match="ner.threshold"):
        ner_config({"ner": {"invented_names": True, "threshold": threshold}})


def test_threshold_of_one_is_allowed():
    assert ner_config({"ner": {"invented_names": True, "threshold": 1}}).threshold == 1.0
