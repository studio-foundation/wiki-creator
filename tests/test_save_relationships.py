"""Tests for scripts/save_relationships.py."""
import json
import subprocess
import sys

import pytest

from wiki_creator import studio_io
from wiki_creator.types import RelationshipBundle

REL_OUTPUT = {
    "entities": [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "source_ids": ["e001"], "relevant": True},
    ],
    "relationships": [
        {
            "entity_a": "David Martín", "entity_b": "Piquillo",
            "cooccurrence_count": 12, "chapters": ["ch01", "ch02"],
            "sample_contexts": ["they walked together"],
            "relationship_type": None, "direction": None,
            "evolution": None, "key_moments": [],
        },
    ],
    "stats": {"total_pairs": 1},
    "narrator": "David Martín",
}


def test_studio_interface():
    """Integration: Studio stdin/stdout contract — pass-through unchanged."""
    payload = json.dumps({"previous_outputs": {"relationship-extraction": REL_OUTPUT}})
    result = subprocess.run(
        [sys.executable, "scripts/save_relationships.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0  # missing file_path in additional_context


def test_main_writes_validated_relationships_artifact(tmp_path):
    """Integration: disk relationships.json round-trips through the RelationshipBundle schema."""
    epub = tmp_path / "library" / "author" / "series" / "books" / "01-book.epub"
    processing = tmp_path / "library" / "author" / "series" / "processing_output" / "01-book"
    payload = json.dumps({
        "additional_context": f"file_path: {epub}\n",
        "previous_outputs": {"relationship-extraction": REL_OUTPUT},
    })
    result = subprocess.run(
        [sys.executable, "scripts/save_relationships.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr

    stdout = json.loads(result.stdout)
    assert stdout == REL_OUTPUT  # stdout stays raw pass-through

    rel_path = processing / "relationships.json"
    assert rel_path.exists()
    bundle = studio_io.load_artifact(rel_path, RelationshipBundle)
    assert bundle.narrator == "David Martín"
    assert bundle.relationships[0].entity_a == "David Martín"
    assert bundle.relationships[0].cooccurrence_count == 12


def test_relationships_artifact_drift_raises(tmp_path):
    """An unknown top-level key on relationships.json must be rejected."""
    path = tmp_path / "relationships.json"
    path.write_text(json.dumps({
        "entities": [], "relationships": [], "stats": {}, "narrator": None,
        "surprise": "unexpected",
    }), encoding="utf-8")
    with pytest.raises(studio_io.ArtifactSchemaError):
        studio_io.load_artifact(path, RelationshipBundle)
