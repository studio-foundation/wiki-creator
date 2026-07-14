"""Tests for scripts/merge_entities.py."""
import sys, os, json, subprocess
from scripts.merge_entities import merge_entities

RESOLVED_PERSON = {"canonical_name": "David Martín", "type": "PERSON",
                   "aliases": ["Martín"], "source_ids": ["e001"], "relevant": True}
RESOLVED_PLACE  = {"canonical_name": "Barcelone", "type": "PLACE",
                   "aliases": ["Barcelona"], "source_ids": ["e040"], "relevant": True}

NARRATOR = {"entity": "David Martín", "pov": "first_person",
            "reliability": "reliable", "evidence": ["ch01: ..."]}

ALL_STAGE_OUTPUTS = {
    "resolve-clusters": {"entities": [RESOLVED_PERSON, RESOLVED_PLACE], "narrator": NARRATOR},
}


def test_entities_passed_through():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    names = {e["canonical_name"] for e in result["entities"]}
    assert names == {"David Martín", "Barcelone"}


def test_narrator_passed_through():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    assert result["narrator"] == NARRATOR


def test_output_shape():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    assert "entities" in result
    assert "narrator" in result


def test_empty_stage_outputs_returns_empty():
    result = merge_entities({})
    assert result["entities"] == []
    assert result["narrator"] is None


def test_non_list_entities_warns_and_returns_empty(capsys):
    result = merge_entities({"resolve-clusters": {"entities": "not-a-list", "narrator": None}})
    assert result["entities"] == []
    assert "Warning" in capsys.readouterr().err


def test_studio_interface():
    """Integration: Studio stdin/stdout contract with all_stage_outputs key."""
    payload = json.dumps({
        "all_stage_outputs": ALL_STAGE_OUTPUTS,
    })
    result = subprocess.run(
        [sys.executable, "scripts/merge_entities.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "entities" in out
    assert len(out["entities"]) == 2
