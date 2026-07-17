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


def _write_run_log(tmp_path, run_id: str, stage: str, output: dict) -> None:
    runs_dir = tmp_path / ".studio" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"20260717-{run_id}.jsonl").write_text(
        json.dumps({"event": "stage_complete", "stage": stage, "status": "success", "output": output})
    )


def test_stage_output_from_stdout_recovers_a_truncated_echo(tmp_path, monkeypatch):
    """The whole point: the run the echo truncates is the run that needs the log.

    A caller that reads the run id out of the *parsed* payload recovers only from
    truncations it already survived — on a real oversized run the parse returns
    None and the log is never opened (STU-564).
    """
    monkeypatch.setattr(studio_io, "PROJECT_ROOT", tmp_path)
    _write_run_log(tmp_path, "abc12345", "s", {"merge": ["from the log"]})
    truncated = '{"id": "abc12345", "status": "success", "stages": [{"stage_name": "s", "outp'
    assert studio_io.extract_first_json_object(truncated) is None
    assert studio_io.stage_output_from_stdout(truncated, "s") == {"merge": ["from the log"]}


def test_stage_output_from_stdout_falls_back_to_the_echo_without_a_log(tmp_path, monkeypatch):
    monkeypatch.setattr(studio_io, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".studio" / "runs").mkdir(parents=True)
    intact = json.dumps(
        {"id": "nolog123", "stages": [{"stage_name": "s", "status": "success", "output": {"ok": True}}]}
    )
    assert studio_io.stage_output_from_stdout(intact, "s") == {"ok": True}
    assert studio_io.stage_output_from_stdout(intact, "other") is None
    assert studio_io.stage_output_from_stdout("not json at all", "s") is None


def test_slugify_filename():
    assert studio_io.slugify_filename("Chaol Westfall!") == "Chaol_Westfall"
    assert studio_io.slugify_filename("  ") == "untitled"
    assert studio_io.slugify_filename("") == "untitled"
