"""The section-filter stage pair — wiring, not classification.

Every test here is LLM-free: the verdict either comes from the cache or arrives
as the `section-filter-verdict` call stage's output in the payload (STU-589).
Neither script may reach the network — the LLM invocation lives in the pipeline
YAML now, not in Python.
"""

import io
import json

import pytest
import yaml

from scripts import section_filter as stage
from scripts import section_filter_pre as pre_stage
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


def _payload(epub, epub_data, verdict=None):
    payload = {
        "additional_context": yaml.safe_dump({"file_path": str(epub)}),
        "previous_outputs": {"epub-parse": epub_data},
    }
    if verdict is not None:
        payload["all_stage_outputs"] = {"epub-parse": epub_data, "section-filter-verdict": verdict}
    return payload


def _run(monkeypatch, module, payload) -> dict:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    module.main()
    return json.loads(out.getvalue())


def test_neither_script_can_shell_out():
    """The subprocess boundary is gone (STU-589): the LLM call lives in the
    pipeline YAML. A subprocess import reappearing here is the old loop back."""
    assert not hasattr(stage, "subprocess")
    assert not hasattr(pre_stage, "subprocess")


def test_pre_asks_for_a_verdict_when_the_cache_is_cold(monkeypatch, book):
    epub, processing, epub_data = book

    result = _run(monkeypatch, pre_stage, _payload(epub, epub_data))

    assert result["needs_verdict"] is True
    assert result["book_title"] == "A Book"
    assert "cop | Copyright" in result["sections"]
    assert "c01 | Chapter 1" in result["sections"]


def test_pre_skips_the_call_on_a_cache_hit(monkeypatch, book):
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})

    assert _run(monkeypatch, pre_stage, _payload(epub, epub_data))["needs_verdict"] is False


def test_pre_ignores_a_cache_for_a_different_section_list(monkeypatch, book):
    """WIKI_MAX_CHAPTERS truncation must not replay a full-book verdict (STU-529)."""
    epub, processing, epub_data = book
    other_rows = section_rows([{"id": "x", "title": "X", "content": "y" * 300}])
    save_drop_cache(processing / "section_filter.json", other_rows, {"x": "junk"})

    assert _run(monkeypatch, pre_stage, _payload(epub, epub_data))["needs_verdict"] is True


def test_pre_fails_when_there_are_no_chapters(monkeypatch, book):
    epub, _, _ = book
    payload = {
        "additional_context": yaml.safe_dump({"file_path": str(epub)}),
        "previous_outputs": {"epub-parse": {"title": "A Book", "chapters": []}},
    }
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", io.StringIO())
    with pytest.raises(SystemExit):
        pre_stage.main()


def test_stage_applies_the_call_verdict_and_caches_it(monkeypatch, book):
    epub, processing, epub_data = book
    verdict = {"drop": [{"id": "cop", "reason": "copyright page"}]}

    result = _run(monkeypatch, stage, _payload(epub, epub_data, verdict=verdict))

    assert result["chapters"][0]["frontmatter"] is True
    assert "frontmatter" not in result["chapters"][1]
    cached = json.loads((processing / "section_filter.json").read_text(encoding="utf-8"))
    assert cached["drop"] == {"cop": "copyright page"}
    assert cached["sections"] == section_rows(CHAPTERS)


def test_stage_tags_cached_frontmatter_and_preserves_the_payload_shape(monkeypatch, book):
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})

    result = _run(monkeypatch, stage, _payload(epub, epub_data))

    # Shape must survive: entity-extraction reads this as previous_stage_output.
    assert result["title"] == "A Book"
    assert result["pov_detection"]["pov"] == "third_limited"
    assert [c["id"] for c in result["chapters"]] == ["cop", "c01"]
    assert result["chapters"][0]["frontmatter"] is True
    assert "frontmatter" not in result["chapters"][1]


def test_stage_prefers_the_cache_over_a_fresh_verdict(monkeypatch, book):
    """A cache hit means the call was condition-skipped; a verdict that somehow
    arrives anyway must not override the cached one for the same rows."""
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})
    verdict = {"drop": [{"id": "c01", "reason": "wrong"}]}

    result = _run(monkeypatch, stage, _payload(epub, epub_data, verdict=verdict))

    assert result["chapters"][0]["frontmatter"] is True
    assert "frontmatter" not in result["chapters"][1]


def test_stage_writes_the_tags_back_to_epub_data_json(monkeypatch, book):
    """chapter_summary --book and wiki_preparation read the file, not stdout."""
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})

    _run(monkeypatch, stage, _payload(epub, epub_data))

    on_disk = json.loads((processing / "epub_data.json").read_text(encoding="utf-8"))
    assert on_disk["chapters"][0]["frontmatter"] is True
    assert "frontmatter" not in on_disk["chapters"][1]


def test_stage_keeps_every_section_when_the_verdict_cannot_be_obtained(monkeypatch, book, capsys):
    """No cache and no call output (child failed under on_failure: continue, or
    was skipped): keep everything, and say so (STU-529)."""
    epub, processing, epub_data = book

    result = _run(monkeypatch, stage, _payload(epub, epub_data))

    assert not any("frontmatter" in c for c in result["chapters"])
    assert "no verdict" in capsys.readouterr().err
    assert not (processing / "section_filter.json").exists()


def test_stage_keeps_every_section_on_an_unparseable_verdict(monkeypatch, book):
    epub, processing, epub_data = book

    result = _run(monkeypatch, stage, _payload(epub, epub_data, verdict={"nonsense": True}))

    assert not any("frontmatter" in c for c in result["chapters"])


def test_stage_reads_chapters_from_previous_stage_output(monkeypatch, book):
    """A payload carrying the epub data only under previous_stage_output still works."""
    epub, processing, epub_data = book
    save_drop_cache(processing / "section_filter.json", section_rows(CHAPTERS), {"cop": "copyright page"})

    payload = {
        "additional_context": yaml.safe_dump({"file_path": str(epub)}),
        "previous_stage_output": epub_data,
    }
    assert _run(monkeypatch, stage, payload)["chapters"][0]["frontmatter"] is True


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

    result = _run(monkeypatch, stage, _payload(epub, epub_data))

    assert "chapter_number" not in result["chapters"][0]
    assert result["chapters"][1]["chapter_number"] == 1
    on_disk = json.loads((processing / "epub_data.json").read_text(encoding="utf-8"))
    assert on_disk["chapters"][1]["chapter_number"] == 1
