import json
import subprocess
import sys
from pathlib import Path
import pytest

import scripts.classify_relationships as clf
from scripts.classify_relationships import _load_done_keys, _save
from wiki_creator import studio_io
from wiki_creator.types import RelationshipBundle


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
    pairs = [{"entity_a": "A", "entity_b": "B", "cooccurrence_count": 5}]
    _save(output, base, pairs)
    written = json.loads(output.read_text())
    assert written["relationships"][0]["entity_a"] == "A"
    assert written["relationships"][0]["entity_b"] == "B"
    assert written["relationships"][0]["cooccurrence_count"] == 5
    assert written["entities"] == []


def test_stray_llm_key_does_not_crash_save(tmp_path, monkeypatch):
    """A classifier returning an extra top-level key (freeform LLM JSON) must not
    brick the incremental _save via Relationship(**r) — the stray key is dropped."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    input_bundle = RelationshipBundle(relationships=[clf.Relationship(
        entity_a="Celaena", entity_b="Chaol", cooccurrence_count=9,
        chapters=["ch01"], sample_contexts=["they spoke"],
    )])
    studio_io.save_artifact(processing / "relationships.json", input_bundle, RelationshipBundle)

    monkeypatch.setattr(clf, "_run_studio_classifier_item", lambda pair, **kw: {
        "relationship_type": "allies", "direction": "mutual", "evolution": None,
        "key_moments": [], "evidence": "they train together",
        "reasoning": "stray freeform key the LLM invented",  # not in Relationship
    })
    monkeypatch.setattr(sys, "argv", ["classify_relationships.py", "--book", str(book_yaml)])

    clf.main()  # must not raise

    out = studio_io.load_artifact(
        processing / "relationships_classified.json", RelationshipBundle
    )
    rel = out.relationships[0]
    assert rel.relationship_type == "allies"
    assert rel.evidence == "they train together"
    assert not hasattr(rel, "reasoning")


def test_dry_run_with_missing_book_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "scripts/classify_relationships.py",
         "--book", "nonexistent.yaml", "--dry-run"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode != 0
