"""Tests for scripts/merge_entities.py."""
import sys, os, json, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.merge_entities import merge_entities

RESOLVED_PERSON = {"canonical_name": "David Martín", "type": "PERSON",
                   "aliases": ["Martín"], "source_ids": ["e001"], "relevant": True}
RESOLVED_PLACE  = {"canonical_name": "Barcelone", "type": "PLACE",
                   "aliases": ["Barcelona"], "source_ids": ["e040"], "relevant": True}
SINGLE_PERSON   = {"canonical_name": "Piquillo", "type": "PERSON",
                   "aliases": ["Piquillo"], "source_ids": ["e010"], "relevant": True}

NARRATOR = {"entity": "David Martín", "pov": "first_person",
            "reliability": "reliable", "evidence": ["ch01: ..."]}

ALL_STAGE_OUTPUTS = {
    "split-clusters": {
        "singles_resolved": [SINGLE_PERSON],
        "PERSON": [], "PLACE": [], "ORG": [], "EVENT": [], "OTHER": [],
    },
    "entity-resolution-PERSON": {"entities": [RESOLVED_PERSON], "narrator": NARRATOR},
    "entity-resolution-PLACE":  {"entities": [RESOLVED_PLACE],  "narrator": None},
    "entity-resolution-ORG":    {"entities": [],                "narrator": None},
}


def test_all_entities_concatenated():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    names = {e["canonical_name"] for e in result["entities"]}
    assert names == {"David Martín", "Barcelone", "Piquillo"}


def test_narrator_taken_from_person_resolver():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    assert result["narrator"] == NARRATOR


def test_narrator_null_when_no_person_resolver():
    outputs = {
        "split-clusters": {"singles_resolved": [SINGLE_PERSON]},
        "entity-resolution-PLACE": {"entities": [RESOLVED_PLACE], "narrator": None},
    }
    result = merge_entities(outputs)
    assert result["narrator"] is None


def test_missing_resolver_stage_is_skipped():
    # ORG resolver missing entirely — should not crash
    outputs = {
        "split-clusters": {"singles_resolved": []},
        "entity-resolution-PERSON": {"entities": [RESOLVED_PERSON], "narrator": None},
    }
    result = merge_entities(outputs)
    assert len(result["entities"]) == 1


def test_output_shape():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    assert "entities" in result
    assert "narrator" in result


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
    assert len(out["entities"]) == 3
