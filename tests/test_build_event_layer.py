import json
import importlib.util
from pathlib import Path

import pytest

from wiki_creator import studio_io


def _load_stage():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_event_layer.py"
    spec = importlib.util.spec_from_file_location("build_event_layer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stage_writes_events_json(tmp_path):
    proc = tmp_path
    (proc / "chapter_summaries.json").write_text(json.dumps({
        "Chapter 1": {"chapter_id": "C01.xhtml", "chapter_title": "Chapter 1",
                      "summary_bullets": ["Celaena defeats Cain"]}
    }), encoding="utf-8")
    (proc / "relationships_classified.json").write_text(json.dumps({
        "entities": [],
        "relationships": [
            {"entity_a": "Celaena", "entity_b": "Cain", "cooccurrence_count": 3,
             "key_moments": ["Ch1: Celaena defeats Cain"]}
        ],
        "stats": {},
        "narrator": None,
    }), encoding="utf-8")
    # No registry.json → registry is None, names pass through unresolved.

    stage = _load_stage()
    stage.run_for_processing(proc, language="en")

    out = json.loads((proc / "events.json").read_text(encoding="utf-8"))
    assert "events" in out
    assert len(out["events"]) == 1
    assert out["events"][0]["chapter"] == 1


def test_read_summaries_rejects_schema_drift(tmp_path):
    """An unknown key on a chapter_summaries.json entry must be rejected."""
    path = tmp_path / "chapter_summaries.json"
    path.write_text(json.dumps({
        "chapter_summaries": {
            "Chapter 1": {
                "chapter_id": "C1.xhtml", "chapter_title": "Chapter 1",
                "summary_bullets": [], "surprise": "unexpected",
            }
        }
    }), encoding="utf-8")

    stage = _load_stage()
    with pytest.raises(studio_io.ArtifactSchemaError):
        stage._read_summaries(path)


def test_read_relationships_rejects_schema_drift(tmp_path):
    """An unknown top-level key on relationships_classified.json must be rejected."""
    path = tmp_path / "relationships_classified.json"
    path.write_text(json.dumps({
        "entities": [], "relationships": [], "stats": {}, "narrator": None,
        "surprise": "unexpected",
    }), encoding="utf-8")

    stage = _load_stage()
    with pytest.raises(studio_io.ArtifactSchemaError):
        stage._read_relationships(path)
