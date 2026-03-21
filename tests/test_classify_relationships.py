import json
import sys
from pathlib import Path
import pytest
from scripts.classify_relationships import _load_done_keys, _save


def test_load_done_keys_returns_empty_when_file_missing(tmp_path):
    keys, pairs = _load_done_keys(tmp_path / "nonexistent.json")
    assert keys == set()
    assert pairs == []


def test_load_done_keys_returns_existing_pairs(tmp_path):
    output = tmp_path / "out.json"
    data = {
        "relationships": [
            {"entity_a": "A", "entity_b": "B", "relationship_type": "ami"},
        ]
    }
    output.write_text(json.dumps(data))
    keys, pairs = _load_done_keys(output)
    assert ("A", "B") in keys
    assert len(pairs) == 1


def test_load_done_keys_returns_empty_on_corrupt_file(tmp_path):
    output = tmp_path / "corrupt.json"
    output.write_text("not valid json")
    keys, pairs = _load_done_keys(output)
    assert keys == set()
    assert pairs == []


def test_load_done_keys_skips_malformed_pairs(tmp_path):
    """A pair missing entity_a/entity_b is skipped, not a full reset."""
    output = tmp_path / "out.json"
    data = {
        "relationships": [
            {"entity_a": "A", "entity_b": "B", "relationship_type": "ami"},
            {"broken": True},
        ]
    }
    output.write_text(json.dumps(data))
    keys, pairs = _load_done_keys(output)
    assert ("A", "B") in keys
    assert len(pairs) == 2


def test_save_writes_valid_json(tmp_path):
    output = tmp_path / "out.json"
    base = {"entities": [], "stats": {}, "narrator": None}
    pairs = [{"entity_a": "A", "entity_b": "B"}]
    _save(output, base, pairs)
    written = json.loads(output.read_text())
    assert written["relationships"] == pairs
    assert written["entities"] == []
