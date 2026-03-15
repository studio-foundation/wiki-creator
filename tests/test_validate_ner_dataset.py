"""Tests for scripts/validate_ner_dataset.py"""
import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.validate_ner_dataset import validate_example, validate_dataset, resolve_overlaps


# ---------------------------------------------------------------------------
# validate_example
# ---------------------------------------------------------------------------

def _make(text, entities):
    return {"text": text, "entities": entities}


def test_valid_example_passes():
    ex = _make("Bilbo lived in the Shire.", [
        {"start": 0, "end": 5, "label": "PERSON", "text": "Bilbo"},
        {"start": 19, "end": 24, "label": "PLACE", "text": "Shire"},
    ])
    errors = validate_example(ex)
    assert errors == []


def test_offset_mismatch_rejected():
    ex = _make("Bilbo lived in the Shire.", [
        {"start": 0, "end": 5, "label": "PERSON", "text": "Frodo"},  # text doesn't match
    ])
    errors = validate_example(ex)
    assert any("mismatch" in e.lower() for e in errors)


def test_out_of_bounds_start_rejected():
    ex = _make("Hi.", [
        {"start": -1, "end": 2, "label": "PERSON", "text": "Hi"},
    ])
    errors = validate_example(ex)
    assert any("bound" in e.lower() or "offset" in e.lower() for e in errors)


def test_out_of_bounds_end_rejected():
    ex = _make("Hi.", [
        {"start": 0, "end": 10, "label": "PERSON", "text": "Hi."},
    ])
    errors = validate_example(ex)
    assert any("bound" in e.lower() or "offset" in e.lower() for e in errors)


def test_overlapping_entities_rejected():
    ex = _make("Bilbo Baggins walked.", [
        {"start": 0, "end": 12, "label": "PERSON", "text": "Bilbo Baggins"},
        {"start": 6, "end": 12, "label": "PERSON", "text": "Baggins"},
    ])
    errors = validate_example(ex)
    assert any("overlap" in e.lower() for e in errors)


def test_empty_entities_is_valid():
    ex = _make("No entities here.", [])
    assert validate_example(ex) == []


def test_missing_text_field_rejected():
    ex = {"entities": []}
    errors = validate_example(ex)
    assert any("text" in e.lower() for e in errors)


def test_missing_entities_field_rejected():
    ex = {"text": "Hello."}
    errors = validate_example(ex)
    assert any("entities" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_dataset
# ---------------------------------------------------------------------------

def test_validate_dataset_returns_stats():
    examples = [
        _make("Bilbo walked.", [{"start": 0, "end": 5, "label": "PERSON", "text": "Bilbo"}]),
        _make("Bad.", [{"start": 0, "end": 99, "label": "PERSON", "text": "Bad"}]),  # invalid
    ]
    stats = validate_dataset(examples)
    assert stats["total"] == 2
    assert stats["valid"] == 1
    assert stats["rejected"] == 1


def test_validate_dataset_counts_labels():
    examples = [
        _make("Bilbo lived in Shire.", [
            {"start": 0, "end": 5, "label": "PERSON", "text": "Bilbo"},
            {"start": 15, "end": 20, "label": "PLACE", "text": "Shire"},
        ]),
    ]
    stats = validate_dataset(examples)
    assert stats["label_counts"]["PERSON"] == 1
    assert stats["label_counts"]["PLACE"] == 1


# ---------------------------------------------------------------------------
# resolve_overlaps
# ---------------------------------------------------------------------------

def test_resolve_overlaps_keeps_longer_span():
    entities = [
        {"start": 0, "end": 12, "label": "PERSON", "text": "Bilbo Baggins"},
        {"start": 6, "end": 12, "label": "PERSON", "text": "Baggins"},
    ]
    result = resolve_overlaps(entities)
    assert len(result) == 1
    assert result[0]["text"] == "Bilbo Baggins"


def test_resolve_overlaps_no_conflict_unchanged():
    entities = [
        {"start": 0, "end": 5, "label": "PERSON", "text": "Bilbo"},
        {"start": 15, "end": 20, "label": "PLACE", "text": "Shire"},
    ]
    result = resolve_overlaps(entities)
    assert len(result) == 2


def test_resolve_overlaps_three_way_keeps_longest():
    # A=[0,10), B=[0,6), C=[4,10) — all overlap, keep longest
    entities = [
        {"start": 0, "end": 10, "label": "PERSON", "text": "0123456789"},
        {"start": 0, "end": 6,  "label": "PERSON", "text": "012345"},
        {"start": 4, "end": 10, "label": "PLACE",  "text": "456789"},
    ]
    text = "0123456789 rest"
    result = resolve_overlaps(entities)
    assert len(result) == 1
    assert result[0]["end"] - result[0]["start"] == 10


def test_validate_example_with_resolve_passes():
    ex = _make("Bilbo Baggins walked.", [
        {"start": 0, "end": 13, "label": "PERSON", "text": "Bilbo Baggins"},
        {"start": 6, "end": 13, "label": "PERSON", "text": "Baggins"},
    ])
    errors = validate_example(ex, resolve=True)
    assert errors == []


def test_validate_example_with_resolve_fixes_example_in_place():
    ex = _make("Bilbo Baggins walked.", [
        {"start": 0, "end": 13, "label": "PERSON", "text": "Bilbo Baggins"},
        {"start": 6, "end": 13, "label": "PERSON", "text": "Baggins"},
    ])
    validate_example(ex, resolve=True)
    assert len(ex["entities"]) == 1


def test_validate_dataset_returns_valid_examples():
    good = _make("Bilbo.", [{"start": 0, "end": 5, "label": "PERSON", "text": "Bilbo"}])
    bad = _make("X.", [{"start": 0, "end": 99, "label": "PERSON", "text": "X"}])
    stats = validate_dataset([good, bad])
    assert len(stats["valid_examples"]) == 1
    assert stats["valid_examples"][0] is good
