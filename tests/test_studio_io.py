"""Tests for wiki_creator.studio_io (STU-445)."""

import io
import json

import pytest
import yaml

from wiki_creator import studio_io
from wiki_creator.paths import BookPaths


def test_read_payload_parses_stdin_json():
    stream = io.StringIO(json.dumps({"additional_context": "x", "previous_outputs": {}}))
    assert studio_io.read_payload(stream) == {
        "additional_context": "x",
        "previous_outputs": {},
    }


def test_paths_from_payload_strict_returns_bookpaths(tmp_path):
    epub = tmp_path / "01-book.yaml"
    epub.write_text("title: Book\n")
    payload = {"additional_context": yaml.safe_dump({"file_path": str(epub)})}
    paths = studio_io.paths_from_payload(payload)
    assert isinstance(paths, BookPaths)


def test_paths_from_payload_strict_raises_when_missing():
    with pytest.raises(ValueError, match="missing file_path"):
        studio_io.paths_from_payload({"additional_context": ""})


def test_paths_from_payload_tolerant_returns_none_when_missing():
    assert studio_io.paths_from_payload({"additional_context": ""}, strict=False) is None
    assert studio_io.paths_from_payload({}, strict=False) is None


def test_write_output_writes_json_without_ascii_escaping():
    stream = io.StringIO()
    studio_io.write_output({"name": "Élide"}, stream)
    assert stream.getvalue() == '{"name": "Élide"}'


def test_extract_first_json_object():
    assert studio_io.extract_first_json_object('noise {"a": 1} trailing') == {"a": 1}
    assert studio_io.extract_first_json_object("no object here") is None
    assert studio_io.extract_first_json_object("") is None


def test_extract_stage_output_from_run_payload():
    run_payload = {
        "stages": [
            {"stage_name": "a", "status": "failed", "output": {"x": 1}},
            {"stage_name": "b", "status": "success", "output": {"y": 2}},
        ]
    }
    assert studio_io.extract_stage_output_from_run_payload(run_payload, "b") == {"y": 2}
    assert studio_io.extract_stage_output_from_run_payload(run_payload, "a") is None
    assert studio_io.extract_stage_output_from_run_payload({}, "b") is None


def test_studio_run_log_path_and_load_stage_output(tmp_path, monkeypatch):
    runs_dir = tmp_path / ".studio" / "runs"
    runs_dir.mkdir(parents=True)
    log = runs_dir / "20260712-abc12345.jsonl"
    log.write_text(
        "\n".join(
            [
                json.dumps({"event": "stage_start", "stage": "s"}),
                json.dumps(
                    {"event": "stage_complete", "stage": "s", "status": "success", "output": {"ok": True}}
                ),
            ]
        )
    )
    monkeypatch.setattr(studio_io, "PROJECT_ROOT", tmp_path)
    assert studio_io.studio_run_log_path("abc12345") == log
    assert studio_io.load_studio_stage_output("abc12345", "s") == {"ok": True}
    assert studio_io.load_studio_stage_output("abc12345", "missing") is None
    assert studio_io.studio_run_log_path("nope") is None


def test_slugify_filename():
    assert studio_io.slugify_filename("Chaol Westfall!") == "Chaol_Westfall"
    assert studio_io.slugify_filename("  ") == "untitled"
    assert studio_io.slugify_filename("") == "untitled"
