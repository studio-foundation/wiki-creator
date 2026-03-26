"""Tests for wiki_export.py — focusing on _failed page filtering."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.wiki_export import _filter_exportable_pages


def test_filter_exportable_pages_excludes_failed():
    pages = [
        {"title": "Celaena", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "## Bio\n\nHero."},
        {"title": "Dorian", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "stub", "_failed": True},
        {"title": "Chaol", "entity_type": "PERSON", "importance": "secondaire",
         "infobox_fields": {}, "content": "## Bio\n\nCaptain."},
    ]
    result = _filter_exportable_pages(pages)
    assert len(result) == 2
    assert all(not p.get("_failed") for p in result)
    assert {p["title"] for p in result} == {"Celaena", "Chaol"}


def test_filter_exportable_pages_all_valid():
    pages = [
        {"title": "A", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "content"},
    ]
    assert _filter_exportable_pages(pages) == pages


def test_filter_exportable_pages_all_failed():
    pages = [
        {"title": "A", "_failed": True, "entity_type": "PERSON",
         "importance": "principal", "infobox_fields": {}, "content": ""},
    ]
    assert _filter_exportable_pages(pages) == []
