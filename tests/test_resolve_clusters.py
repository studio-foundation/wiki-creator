"""Tests for scripts/resolve_clusters.py — noise_words handling, splits input."""
import io
import json
import sys

import pytest

import scripts.resolve_clusters as rc
from scripts.resolve_clusters import is_relevant, _NOISE_WORDS


def test_is_relevant_respects_custom_noise_words():
    custom = frozenset({"testword"})
    assert not is_relevant("Testword", noise_words=custom)
    assert is_relevant("Testword")  # not in default noise_words


def test_default_noise_words_contains_en_and_fr():
    assert "yes" in _NOISE_WORDS   # English
    assert "oui" in _NOISE_WORDS   # French


def _splits(name: str) -> dict:
    return {
        "by_type": {
            "PERSON": [],
            "PLACE": [],
            "ORG": [],
            "EVENT": [],
            "OTHER": [],
        },
        "singles_resolved": [{
            "canonical_name": name,
            "type": "PERSON",
            "aliases": [],
            "source_ids": ["p1"],
        }],
        "stats": {},
    }


def _run_main(monkeypatch, paths, payload) -> dict:
    monkeypatch.setattr(rc.studio_io, "paths_from_payload", lambda _payload: paths)
    stdin_backup, stdout_backup = sys.stdin, sys.stdout
    try:
        sys.stdin = io.StringIO(json.dumps(payload))
        sys.stdout = io.StringIO()
        rc.main()
        return json.loads(sys.stdout.getvalue())
    finally:
        sys.stdin, sys.stdout = stdin_backup, stdout_backup


def test_main_reads_splits_from_disk_not_from_stage_context(monkeypatch, tmp_path):
    """STU-455: split-clusters belongs to wiki-extraction, a different `studio run`,
    so its stage output never reaches this pipeline. Feed both and the disk wins —
    otherwise the loader stage could come back unnoticed."""
    processing = tmp_path / "processing"
    processing.mkdir()
    (processing / "splits.json").write_text(json.dumps(_splits("Celaena")), encoding="utf-8")
    paths = type("_Paths", (), {"processing": processing})()

    out = _run_main(monkeypatch, paths, {
        "additional_context": "file_path: fake.epub",
        "previous_outputs": {"split-clusters": _splits("Nehemia")},
    })

    assert [e["canonical_name"] for e in out["entities"]] == ["Celaena"]


def test_main_exits_when_extraction_has_not_run(monkeypatch, tmp_path):
    paths = type("_Paths", (), {"processing": tmp_path})()
    with pytest.raises(SystemExit):
        _run_main(monkeypatch, paths, {"additional_context": "file_path: fake.epub"})
