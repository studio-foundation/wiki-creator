"""End-to-end smoke test — EPUB → parse → NER extraction on an original,
copyright-free mini-novella (tests/fixtures/e2e/).

Purpose: make the pipeline verifiable from a fresh clone. Real books
(EPUBs) are never committed, so this is the only in-repo path that
exercises the extraction stages against an actual EPUB file.

Tier 1 (always runs): EPUB build + scripts/parse_epub.py.
Tier 2 (skips without en_core_web_sm): scripts/entity_extraction.py.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from ebooklib import epub

from _markers import requires_en_sm

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "e2e"

CHAPTER_TITLES = ["Harbor Fog", "The Granite Hall", "Warehouse Nine", "North"]


def _build_smoke_epub(tmp_path: Path) -> Path:
    """Build a small EPUB from the committed fixture chapters.

    Layout matches what book_paths_from_epub expects:
    <series>/books/<slug>.epub → outputs under <series>/processing_output/<slug>/.
    """
    book = epub.EpubBook()
    book.set_identifier("smoke-novella")
    book.set_title("The Salt Guild Ledger")
    book.set_language("en")
    book.add_author("Wiki Creator Fixtures")

    items = []
    for i, title in enumerate(CHAPTER_TITLES, start=1):
        text = (FIXTURE_DIR / f"ch{i:02d}.txt").read_text(encoding="utf-8")
        item = epub.EpubHtml(
            title=title, file_name=f"ch{i:02d}.xhtml", lang="en"
        )
        item.set_content(f"<h1>{title}</h1>" + "".join(
            f"<p>{para}</p>" for para in text.strip().split("\n\n")
        ))
        book.add_item(item)
        items.append(item)

    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items

    books_dir = tmp_path / "smoke-series" / "books"
    books_dir.mkdir(parents=True)
    epub_path = books_dir / "smoke-novella.epub"
    epub.write_epub(str(epub_path), book)
    return epub_path


def _run_stage(script: str, payload: dict) -> dict:
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=300,
    )
    assert result.returncode == 0, (
        f"{script} failed (rc={result.returncode}):\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def smoke_epub(tmp_path_factory) -> Path:
    return _build_smoke_epub(tmp_path_factory.mktemp("e2e"))


@pytest.fixture(scope="module")
def parse_result(smoke_epub: Path) -> dict:
    ctx = yaml.safe_dump({"file_path": str(smoke_epub), "language": "en"})
    return _run_stage("parse_epub.py", {"additional_context": ctx})


def test_parse_epub_extracts_all_chapters(parse_result):
    assert parse_result["title"] == "The Salt Guild Ledger"
    assert parse_result["author"] == "Wiki Creator Fixtures"
    contents = [ch["content"] for ch in parse_result["chapters"]]
    assert len(contents) == len(CHAPTER_TITLES)
    assert any("Elias Thorn" in c for c in contents)
    assert any("Port Saffron" in c for c in contents)


def test_parse_epub_reports_language_and_pov(parse_result):
    assert parse_result["language"] == "en"
    pov = parse_result["pov_detection"]
    # Third-person narration with 'she/he ... thought/knew' style markers.
    assert pov["pov"] in {"third_limited", "omniscient"}
    assert pov["total_tokens"] > 0


def test_parse_epub_writes_epub_data_json(parse_result, smoke_epub):
    data_file = (
        smoke_epub.parent.parent / "processing_output" / "smoke-novella" / "epub_data.json"
    )
    assert data_file.exists()
    on_disk = json.loads(data_file.read_text(encoding="utf-8"))
    assert on_disk["title"] == parse_result["title"]


@requires_en_sm
def test_entity_extraction_finds_fixture_entities(parse_result, smoke_epub):
    ctx = yaml.safe_dump({
        "file_path": str(smoke_epub),
        "spacy_model": "en_core_web_sm",
        "min_mentions_absolute": 2,
    })
    extraction = _run_stage("entity_extraction.py", {
        "additional_context": ctx,
        "previous_outputs": {"epub-parse": parse_result},
    })
    # entities_for_resolution: dict keyed by entity_id, each entity carrying
    # {type, raw_mentions, first_seen, mention_count} (no mentions_by_chapter).
    entities = extraction["entities_for_resolution"]
    assert entities, "no entities extracted from the smoke novella"

    def mentions(type_filter: str | None = None) -> set[str]:
        return {
            m
            for e in entities.values()
            if type_filter is None or e.get("type") == type_filter
            for m in e.get("raw_mentions", [])
        }

    persons = mentions("PERSON")
    # The two protagonists are each mentioned 4+ times with full names —
    # any reasonable NER model must surface them.
    assert any("Thorn" in m for m in persons), f"PERSON mentions: {persons}"
    assert any("Vale" in m for m in persons), f"PERSON mentions: {persons}"
    assert any("Saffron" in m for m in mentions()), f"all mentions: {mentions()}"

    # Per-type registries and chapters.json land in processing_output/<slug>/
    processing = smoke_epub.parent.parent / "processing_output" / "smoke-novella"
    assert (processing / "persons_full.json").exists()
    assert (processing / "chapters.json").exists()
    persons_full = json.loads((processing / "persons_full.json").read_text(encoding="utf-8"))
    assert persons_full["persons_full"], "persons_full.json is empty"
    # Mentions must be keyed by chapter id (repo gotcha: id, not title)
    chapter_ids = {ch["id"] for ch in parse_result["chapters"]}
    for entity in persons_full["persons_full"].values():
        assert set(entity.get("mentions_by_chapter", {})) <= chapter_ids
