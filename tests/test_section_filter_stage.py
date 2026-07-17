"""The section-filter stage itself — wiring, not classification.

Every test here is LLM-free: the verdict cache is pre-seeded, so `main()` takes the
cache-hit path and never shells out to `studio`. A test that reached the network
would be exercising the model, not the stage.
"""

import io
import json

import pytest
import yaml

from scripts import section_filter as stage
from wiki_creator.section_filter import save_drop_cache, section_rows


CHAPTERS = [
    {"id": "cop", "title": "Copyright", "content": "Copyright (c) 2023 by A. Writer. " * 20},
    {"id": "c01", "title": "Chapter 1", "content": "Celaena entered the glass castle. " * 60},
]


@pytest.fixture
def book(tmp_path):
    """A book laid out the way paths.py expects, with an epub_data.json on disk."""
    books_dir = tmp_path / "author" / "series" / "books"
    books_dir.mkdir(parents=True)
    epub = books_dir / "01-a-book.epub"
    epub.write_bytes(b"not a real epub - only the path is used")

    processing = tmp_path / "author" / "series" / "processing_output" / "01-a-book"
    processing.mkdir(parents=True)
    epub_data = {
        "title": "A Book",
        "author": "A. Writer",
        "chapters": [dict(c) for c in CHAPTERS],
        "pov_detection": {"pov": "third_limited", "confidence": "high"},
    }
    (processing / "epub_data.json").write_text(json.dumps(epub_data), encoding="utf-8")
    return epub, processing, epub_data


def _payload(epub, epub_data):
    return {
        "additional_context": yaml.safe_dump({"file_path": str(epub)}),
        "previous_outputs": {"epub-parse": epub_data},
    }


def _run(monkeypatch, payload) -> dict:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    stage.main()
    return json.loads(out.getvalue())


def _forbid_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("stage must not shell out to studio on a cache hit")
    monkeypatch.setattr(stage.subprocess, "run", boom)


def test_stage_tags_cached_frontmatter_and_preserves_the_payload_shape(monkeypatch, book):
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})
    _forbid_network(monkeypatch)

    result = _run(monkeypatch, _payload(epub, epub_data))

    # Shape must survive: entity-extraction reads this as previous_stage_output.
    assert result["title"] == "A Book"
    assert result["pov_detection"]["pov"] == "third_limited"
    assert [c["id"] for c in result["chapters"]] == ["cop", "c01"]
    assert result["chapters"][0]["frontmatter"] is True
    assert "frontmatter" not in result["chapters"][1]


def test_stage_writes_the_tags_back_to_epub_data_json(monkeypatch, book):
    """chapter_summary --book and wiki_preparation read the file, not stdout."""
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})
    _forbid_network(monkeypatch)

    _run(monkeypatch, _payload(epub, epub_data))

    on_disk = json.loads((processing / "epub_data.json").read_text(encoding="utf-8"))
    assert on_disk["chapters"][0]["frontmatter"] is True
    assert "frontmatter" not in on_disk["chapters"][1]


def test_stage_keeps_every_section_when_the_verdict_cannot_be_obtained(monkeypatch, book, capsys):
    """No cache and no studio CLI: keep everything, and say so."""
    epub, processing, epub_data = book
    monkeypatch.setattr(stage.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))

    result = _run(monkeypatch, _payload(epub, epub_data))

    assert not any("frontmatter" in c for c in result["chapters"])
    assert "studio_cli_missing" in capsys.readouterr().err


def test_stage_reads_chapters_from_previous_stage_output(monkeypatch, book):
    """Studio passes the prior stage under previous_stage_output, not previous_outputs."""
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})
    _forbid_network(monkeypatch)

    payload = {
        "additional_context": yaml.safe_dump({"file_path": str(epub)}),
        "previous_stage_output": epub_data,
    }
    assert _run(monkeypatch, payload)["chapters"][0]["frontmatter"] is True


def test_stage_fails_when_there_are_no_chapters(monkeypatch, book):
    epub, _, _ = book
    payload = {
        "additional_context": yaml.safe_dump({"file_path": str(epub)}),
        "previous_outputs": {"epub-parse": {"title": "A Book", "chapters": []}},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    with pytest.raises(SystemExit):
        stage.main()


def test_stage_numbers_the_narrative_chapters(monkeypatch, book):
    """STU-550: the number is assigned here — the only place both the reading
    order and the front-matter verdict are known."""
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})
    _forbid_network(monkeypatch)

    result = _run(monkeypatch, _payload(epub, epub_data))

    assert "chapter_number" not in result["chapters"][0]
    assert result["chapters"][1]["chapter_number"] == 1
    on_disk = json.loads((processing / "epub_data.json").read_text(encoding="utf-8"))
    assert on_disk["chapters"][1]["chapter_number"] == 1
