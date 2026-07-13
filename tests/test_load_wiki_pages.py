"""Tests for load_wiki_pages.py — _failed page filtering at pipeline entry point."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.load_wiki_pages import _filter_failed_pages


def test_filter_failed_pages_excludes_failed():
    pages = [
        {"title": "Celaena", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "## Bio\n\nHero."},
        {"title": "Arobynn Hamel", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "", "_failed": True},
        {"title": "Chaol", "entity_type": "PERSON", "importance": "secondaire",
         "infobox_fields": {}, "content": "## Bio\n\nCaptain."},
    ]
    result = _filter_failed_pages(pages)
    assert len(result) == 2
    assert all(not p.get("_failed") for p in result)
    assert {p["title"] for p in result} == {"Celaena", "Chaol"}


def test_filter_failed_pages_all_valid():
    pages = [
        {"title": "A", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "content"},
    ]
    assert _filter_failed_pages(pages) == pages


def test_filter_failed_pages_all_failed():
    pages = [
        {"title": "Arobynn", "_failed": True, "entity_type": "PERSON",
         "importance": "principal", "infobox_fields": {}, "content": ""},
    ]
    assert _filter_failed_pages(pages) == []


def test_filter_failed_pages_empty():
    assert _filter_failed_pages([]) == []


# --- SP4 synopsis page (STU-482) ---

import json

from scripts.load_wiki_pages import _load_synopsis_page


def _synopsis_page(**extra):
    page = {"title": "Synopsis", "entity_type": "SYNOPSIS", "importance": "principal",
            "infobox_fields": {}, "content": "## Synopsis\n\nL'intrigue."}
    page.update(extra)
    return page


def test_load_synopsis_page_reads_artifact(tmp_path):
    (tmp_path / "book_synopsis.json").write_text(
        json.dumps({"page": _synopsis_page()}), encoding="utf-8"
    )
    page = _load_synopsis_page(tmp_path)
    assert page is not None
    assert page["title"] == "Synopsis"
    assert page["entity_type"] == "SYNOPSIS"


def test_load_synopsis_page_absent(tmp_path):
    assert _load_synopsis_page(tmp_path) is None


def test_load_synopsis_page_skips_failed(tmp_path):
    (tmp_path / "book_synopsis.json").write_text(
        json.dumps({"page": _synopsis_page(_failed=True)}), encoding="utf-8"
    )
    assert _load_synopsis_page(tmp_path) is None


def test_load_synopsis_page_tolerates_bad_json(tmp_path):
    (tmp_path / "book_synopsis.json").write_text("{not json", encoding="utf-8")
    assert _load_synopsis_page(tmp_path) is None
