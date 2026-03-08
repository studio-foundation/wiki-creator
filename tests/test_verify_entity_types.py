"""Tests for scripts/verify_entity_types.py — entity type verification."""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.verify_entity_types import (
    is_obvious_geographic,
    load_context_for_cluster,
    apply_corrections,
)


# --- is_obvious_geographic ---

def test_obvious_geographic_rue():
    assert is_obvious_geographic("rue de la Paix") is True

def test_obvious_geographic_avenue():
    assert is_obvious_geographic("avenue Barcelona") is True

def test_obvious_geographic_eglise():
    assert is_obvious_geographic("Église Saint-Pierre") is True

def test_obvious_geographic_proper_name_not_geo():
    assert is_obvious_geographic("Barrido") is False

def test_obvious_geographic_hispanic_name():
    assert is_obvious_geographic("Marlasca") is False

def test_obvious_geographic_case_insensitive():
    assert is_obvious_geographic("Boulevard du Temple") is True


# --- load_context_for_cluster ---

def test_load_context_finds_entity(tmp_path):
    # Write a fake places_full.json
    data = {
        "places_full": {
            "entity_042": {
                "type": "PLACE",
                "raw_mentions": ["Barrido"],
                "mentions_by_chapter": {
                    "ch03": ["Barrido lui tendit la main en souriant."]
                }
            }
        }
    }
    places_file = tmp_path / "places_full.json"
    places_file.write_text(json.dumps(data))

    ctx = load_context_for_cluster(
        entity_ids=["entity_042"],
        original_type="PLACE",
        search_dirs=[str(tmp_path)],
    )
    assert len(ctx) == 1
    assert "Barrido lui tendit" in ctx[0]

def test_load_context_missing_entity_returns_empty(tmp_path):
    data = {"places_full": {}}
    places_file = tmp_path / "places_full.json"
    places_file.write_text(json.dumps(data))

    ctx = load_context_for_cluster(
        entity_ids=["entity_999"],
        original_type="PLACE",
        search_dirs=[str(tmp_path)],
    )
    assert ctx == []


# --- apply_corrections ---

def test_apply_corrections_reclassifies_person():
    clusters = [
        {
            "cluster_id": "single_entity_042",
            "type": "PLACE",
            "canonical_candidate": "Barrido",
            "all_mentions": ["Barrido"],
            "entity_ids": ["entity_042"],
            "entity_count": 1,
            "total_mentions": 5,
        }
    ]
    corrections = [{"cluster_id": "single_entity_042", "from": "PLACE", "to": "PERSON"}]
    result = apply_corrections(clusters, corrections)
    assert result[0]["type"] == "PERSON"

def test_apply_corrections_leaves_others_unchanged():
    clusters = [
        {"cluster_id": "cluster_001", "type": "PERSON", "canonical_candidate": "Martín",
         "all_mentions": ["Martín"], "entity_ids": ["entity_001"], "entity_count": 1, "total_mentions": 10},
        {"cluster_id": "single_entity_042", "type": "PLACE", "canonical_candidate": "Barrido",
         "all_mentions": ["Barrido"], "entity_ids": ["entity_042"], "entity_count": 1, "total_mentions": 5},
    ]
    corrections = [{"cluster_id": "single_entity_042", "from": "PLACE", "to": "PERSON"}]
    result = apply_corrections(clusters, corrections)
    assert result[0]["type"] == "PERSON"   # Martín unchanged
    assert result[1]["type"] == "PERSON"   # Barrido corrected
