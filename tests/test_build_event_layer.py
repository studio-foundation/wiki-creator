import json
import importlib.util
from pathlib import Path


def _load_stage():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_event_layer.py"
    spec = importlib.util.spec_from_file_location("build_event_layer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stage_writes_events_json(tmp_path):
    proc = tmp_path
    (proc / "chapter_summaries.json").write_text(json.dumps({
        "Chapter 12": {"chapter_id": "C12.xhtml", "chapter_title": "Chapter 12",
                       "summary_bullets": ["Celaena defeats Cain"]}
    }), encoding="utf-8")
    (proc / "relationships_classified.json").write_text(json.dumps([
        {"entity_a": "Celaena", "entity_b": "Cain",
         "key_moments": ["Ch12: Celaena defeats Cain"]}
    ]), encoding="utf-8")
    # No registry.json → registry is None, names pass through unresolved.

    stage = _load_stage()
    stage.run_for_processing(proc, language="en")

    out = json.loads((proc / "events.json").read_text(encoding="utf-8"))
    assert "events" in out
    assert len(out["events"]) == 1
    assert out["events"][0]["chapter"] == 12
