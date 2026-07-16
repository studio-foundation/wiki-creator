"""STU-533: `studio run --json` stdout is cut at exactly 8192 bytes.

The run completed and the page is intact in `.studio/runs/*.jsonl`, but the
truncated stdout echo used to be turned into a total loss: the top-level object
failed to decode, `extract_first_json_object` silently returned the first nested
object that did decode (`stages[0]`), and `run_id` was read from it — the stage
id, not the run id — so the JSONL fallback looked up a run that never existed.

Fixtures are the real Narnia 01 artifacts: the 8192-byte stdout saved as
`Cair_Paravel.json#raw_response`, and the run log it should have been recovered
from (trimmed to its completion events).
"""
import json
import subprocess
from pathlib import Path

import pytest

import scripts.generate_wiki_pages as gwp
from wiki_creator import studio_io

FIXTURES = Path(__file__).parent / "fixtures" / "stu533"
TRUNCATED_STDOUT = (FIXTURES / "cair_paravel_truncated_stdout.txt").read_text(encoding="utf-8")
RUN_LOG = FIXTURES / "2026-07-16T01h04m-wiki-page-item-d9f310e4.jsonl"


def test_the_committed_stdout_really_is_cut_mid_object():
    assert len(TRUNCATED_STDOUT.encode("utf-8")) == 8192
    with pytest.raises(json.JSONDecodeError):
        json.loads(TRUNCATED_STDOUT)


def test_extract_first_json_object_refuses_a_truncated_top_level_object():
    assert studio_io.extract_first_json_object(TRUNCATED_STDOUT) is None


def test_extract_first_json_object_still_skips_non_json_braces():
    assert studio_io.extract_first_json_object('{ not json } {"a": 1}') == {"a": 1}


def test_extract_run_id_survives_truncation():
    assert studio_io.extract_run_id(TRUNCATED_STDOUT) == "d9f310e4-1ec0-4094-8bd7-8b9602f36cdf"
    assert studio_io.extract_run_id("no id here") == ""


@pytest.fixture
def studio_runs_dir(tmp_path, monkeypatch):
    runs = tmp_path / ".studio" / "runs"
    runs.mkdir(parents=True)
    (runs / RUN_LOG.name).write_text(RUN_LOG.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(studio_io, "PROJECT_ROOT", tmp_path)
    return runs


def _fake_run(stdout):
    def run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    return run


def test_truncated_stdout_recovers_the_page_from_the_run_log(studio_runs_dir, monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(TRUNCATED_STDOUT))
    entity = {"canonical_name": "Cair Paravel", "type": "PLACE", "importance": "figurant"}

    result = gwp._execute_wiki_page_item({"language": "fr"}, entity, timeout=30)

    assert not result.get("error")
    assert not result.get("_failed")
    assert result["title"] == "Cair Paravel"
    assert "château côtier" in result["content"]
    assert result["run_metadata"]["run_id"] == "d9f310e4-1ec0-4094-8bd7-8b9602f36cdf"


def test_the_run_log_wins_over_the_stdout_echo(studio_runs_dir, monkeypatch):
    """The log is complete on disk; the stdout echo is a size-fragile duplicate."""
    stale = json.dumps(
        {
            "id": "d9f310e4-1ec0-4094-8bd7-8b9602f36cdf",
            "status": "success",
            "stages": [
                {
                    "stage_name": "wiki-page-item",
                    "status": "success",
                    "output": {"title": "Cair Paravel", "content": "## Biographie\n\nstale echo."},
                }
            ],
        }
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stale))
    entity = {"canonical_name": "Cair Paravel", "type": "PLACE", "importance": "figurant"}

    result = gwp._execute_wiki_page_item({"language": "fr"}, entity, timeout=30)

    assert "château côtier" in result["content"]


def test_no_run_id_is_reported_as_such(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run("not json at all"))

    result = gwp._execute_wiki_page_item({"language": "fr"}, {"canonical_name": "X"}, timeout=30)

    assert result["error"] == "studio_run_missing_id"
