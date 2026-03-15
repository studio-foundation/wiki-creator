"""Tests for scripts/convert_to_docbin.py"""
import sys, os
import pytest
import spacy
from spacy.tokens import DocBin

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.convert_to_docbin import examples_to_docbin, split_train_dev


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def nlp():
    return spacy.blank("en")


def _ex(text, entities):
    return {"text": text, "entities": entities}


# ---------------------------------------------------------------------------
# examples_to_docbin
# ---------------------------------------------------------------------------

def test_converts_single_valid_example(nlp):
    examples = [
        _ex("Bilbo lived in the Shire.", [
            {"start": 0,  "end": 5,  "label": "PERSON", "text": "Bilbo"},
            {"start": 19, "end": 24, "label": "PLACE",  "text": "Shire"},
        ])
    ]
    db = examples_to_docbin(examples, nlp)
    docs = list(db.get_docs(nlp.vocab))
    assert len(docs) == 1
    ents = [(e.start_char, e.end_char, e.label_) for e in docs[0].ents]
    assert (0, 5, "PERSON") in ents
    assert (19, 24, "PLACE") in ents


def test_example_with_no_entities_is_included(nlp):
    examples = [_ex("No entities here.", [])]
    db = examples_to_docbin(examples, nlp)
    docs = list(db.get_docs(nlp.vocab))
    assert len(docs) == 1
    assert docs[0].ents == ()


def test_invalid_char_span_is_skipped_not_crash(nlp):
    # end > len(text) — char_span returns None, should skip that entity
    examples = [
        _ex("Hi.", [
            {"start": 0, "end": 99, "label": "PERSON", "text": "Hi."},
        ])
    ]
    db = examples_to_docbin(examples, nlp)
    docs = list(db.get_docs(nlp.vocab))
    assert len(docs) == 1
    assert docs[0].ents == ()


def test_returns_docbin_instance(nlp):
    db = examples_to_docbin([], nlp)
    assert isinstance(db, DocBin)


# ---------------------------------------------------------------------------
# split_train_dev
# ---------------------------------------------------------------------------

def test_split_80_20_default():
    examples = [{"id": i} for i in range(100)]
    train, dev = split_train_dev(examples)
    assert len(train) == 80
    assert len(dev) == 20


def test_split_custom_ratio():
    examples = [{"id": i} for i in range(10)]
    train, dev = split_train_dev(examples, dev_ratio=0.3)
    assert len(dev) == 3
    assert len(train) == 7


def test_split_is_reproducible():
    examples = [{"id": i} for i in range(50)]
    train_a, dev_a = split_train_dev(examples, seed=42)
    train_b, dev_b = split_train_dev(examples, seed=42)
    assert [e["id"] for e in train_a] == [e["id"] for e in train_b]


def test_split_different_seeds_differ():
    examples = [{"id": i} for i in range(50)]
    train_a, _ = split_train_dev(examples, seed=1)
    train_b, _ = split_train_dev(examples, seed=2)
    assert [e["id"] for e in train_a] != [e["id"] for e in train_b]


def test_split_no_overlap():
    examples = [{"id": i} for i in range(20)]
    train, dev = split_train_dev(examples)
    train_ids = {e["id"] for e in train}
    dev_ids = {e["id"] for e in dev}
    assert train_ids & dev_ids == set()
    assert train_ids | dev_ids == set(range(20))
