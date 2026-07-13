"""Tests for scripts/verify_entity_types.py — entity type verification."""
import sys
import os
import json
import io
import yaml

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


# --- pass-through integration (no Ollama) ---

def test_passthrough_mode_via_main(monkeypatch, capsys):
    """When verify_entity_types is false, output equals input clusters unchanged."""
    import io
    clusters = [
        {"cluster_id": "single_entity_042", "type": "PLACE",
         "canonical_candidate": "Barrido", "all_mentions": ["Barrido"],
         "entity_ids": ["entity_042"], "entity_count": 1, "total_mentions": 5}
    ]
    payload = {
        "additional_context": "verify_entity_types: false",
        "previous_outputs": {
            "entity-clustering": {
                "clusters": clusters,
                "stats": {"input_entities": 1, "total_items": 1}
            }
        }
    }
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(
        io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"
    ))
    captured_output = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured_output)

    from scripts.verify_entity_types import main
    main()

    result = json.loads(captured_output.getvalue())
    assert result["type_corrections"] == []
    assert result["clusters"][0]["type"] == "PLACE"  # unchanged


# --- main() file persistence ---


def _make_payload(tmp_path, verify_enabled: bool, clusters: list) -> dict:
    """Build a Studio-style payload with file_path pointing into tmp_path."""
    # book_paths_from_epub expects: <anything>/books/<slug>.epub
    # It derives: series_dir = tmp_path, slug = "testbook"
    # → paths.processing = tmp_path / "processing_output" / "testbook"
    book_file = tmp_path / "books" / "testbook.epub"
    book_file.parent.mkdir(parents=True, exist_ok=True)
    book_file.touch()
    ctx = yaml.dump({"file_path": str(book_file), "verify_entity_types": verify_enabled})
    return {
        "additional_context": ctx,
        "previous_outputs": {
            "entity-clustering": {
                "clusters": clusters,
                "stats": {"input_entities": len(clusters), "total_items": len(clusters)},
            }
        },
    }


def _run_main(monkeypatch, payload: dict) -> dict:
    """Pipe payload through main() and return parsed stdout."""
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    # Patch _call_ollama to avoid real network calls
    import scripts.verify_entity_types as _vt
    monkeypatch.setattr(_vt, "_call_ollama", lambda name, ctx, model: "PERSON")
    from scripts.verify_entity_types import main
    main()
    return json.loads(captured.getvalue())


def test_main_writes_corrections_file(monkeypatch, tmp_path):
    """enabled=True + clusters → entity_type_corrections.json written."""
    clusters = [
        {
            "cluster_id": "cluster_042",
            "type": "PLACE",
            "canonical_candidate": "Arobynn",
            "all_mentions": ["Arobynn"],
            "entity_ids": ["entity_042"],
            "entity_count": 1,
            "total_mentions": 10,
        }
    ]
    # Provide places_full.json so load_context_for_cluster returns something
    processing_dir = tmp_path / "processing_output" / "testbook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "places_full.json").write_text(
        json.dumps({
            "places_full": {
                "entity_042": {
                    "type": "PLACE",
                    "raw_mentions": ["Arobynn"],
                    "mentions_by_chapter": {"ch01": ["Arobynn sourit depuis le trône."]},
                }
            }
        })
    )

    payload = _make_payload(tmp_path, verify_enabled=True, clusters=clusters)
    _run_main(monkeypatch, payload)

    corrections_file = processing_dir / "entity_type_corrections.json"
    assert corrections_file.exists(), "entity_type_corrections.json must be written"
    data = json.loads(corrections_file.read_text())
    assert len(data) == 1
    assert data[0]["name"] == "Arobynn"
    assert data[0]["to"] == "PERSON"
    assert data[0]["from"] == "PLACE"


def test_main_writes_empty_file_when_no_corrections(monkeypatch, tmp_path):
    """enabled=True but _call_ollama returns None for all → file written as []."""
    import scripts.verify_entity_types as _vt
    monkeypatch.setattr(_vt, "_call_ollama", lambda name, ctx, model: None)

    processing_dir = tmp_path / "processing_output" / "testbook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "places_full.json").write_text(
        json.dumps({
            "places_full": {
                "entity_042": {
                    "type": "PLACE",
                    "raw_mentions": ["SomePlace"],
                    "mentions_by_chapter": {"ch01": ["SomePlace was cold."]},
                }
            }
        })
    )
    clusters = [
        {
            "cluster_id": "cluster_042",
            "type": "PLACE",
            "canonical_candidate": "SomePlace",
            "all_mentions": ["SomePlace"],
            "entity_ids": ["entity_042"],
            "entity_count": 1,
            "total_mentions": 3,
        }
    ]
    payload = _make_payload(tmp_path, verify_enabled=True, clusters=clusters)

    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    from scripts.verify_entity_types import main
    main()

    corrections_file = processing_dir / "entity_type_corrections.json"
    assert corrections_file.exists()
    assert json.loads(corrections_file.read_text()) == []


def test_main_no_file_when_disabled(monkeypatch, tmp_path):
    """`verify_entity_types: false` → early return, no file written."""
    processing_dir = tmp_path / "processing_output" / "testbook"
    # Do NOT pre-create the directory — should not be created by the disabled path

    payload = _make_payload(tmp_path, verify_enabled=False, clusters=[])
    _run_main(monkeypatch, payload)

    assert not (processing_dir / "entity_type_corrections.json").exists()


def test_main_no_file_when_no_paths(monkeypatch, tmp_path):
    """Payload without file_path → no file written (test mode)."""
    payload = {
        "additional_context": "verify_entity_types: true",
        "previous_outputs": {
            "entity-clustering": {"clusters": [], "stats": {}}
        },
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    import scripts.verify_entity_types as _vt
    monkeypatch.setattr(_vt, "_call_ollama", lambda name, ctx, model: "PERSON")
    from scripts.verify_entity_types import main
    main()

    # No file should have been written anywhere near tmp_path
    # (nothing to check beyond no exception raised)
