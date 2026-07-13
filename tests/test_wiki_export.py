"""Tests for wiki_export.py — _failed page filtering and the copyright gate."""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.wiki_export import _copyright_gate, _filter_exportable_pages


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


# --- INV-WC-01 copyright gate ---


def test_copyright_gate_blocks_on_fail():
    prev = {
        "copyright-check": {
            "status": "fail",
            "feedback": "Violations copyright détectées dans : [Celaena].",
            "violations": [
                {"page_title": "Celaena", "chapter": "ch03",
                 "wiki_excerpt": "…", "consecutive_words": 18},
            ],
            "pages": [{"title": "Celaena"}],
        }
    }
    result = _copyright_gate(prev)
    assert result is not None
    assert result["error"] == "copyright_check_failed"
    assert result["violating_pages"] == ["Celaena"]
    assert result["violations"][0]["consecutive_words"] == 18


def test_copyright_gate_passes_on_pass():
    prev = {"copyright-check": {"status": "pass", "violations": [], "pages": []}}
    assert _copyright_gate(prev) is None


def test_copyright_gate_passes_when_stage_absent():
    # Pipelines without a copyright-check stage must still export.
    assert _copyright_gate({}) is None
    assert _copyright_gate({"copyright-check": None}) is None


def test_copyright_gate_dedupes_and_sorts_titles():
    prev = {
        "copyright-check": {
            "status": "fail",
            "violations": [
                {"page_title": "Zed", "chapter": "c1", "wiki_excerpt": "", "consecutive_words": 15},
                {"page_title": "Ada", "chapter": "c2", "wiki_excerpt": "", "consecutive_words": 16},
                {"page_title": "Zed", "chapter": "c3", "wiki_excerpt": "", "consecutive_words": 17},
            ],
        }
    }
    result = _copyright_gate(prev)
    assert result["violating_pages"] == ["Ada", "Zed"]


# --- SP4 synopsis page rendering (STU-482) ---

from scripts.wiki_export import render_page

_LABELS = {
    "persons": "Personnages",
    "principal": "Personnages principaux",
    "secondary": "Personnages secondaires",
    "locations": "Lieux",
    "organizations": "Organisations",
}


def test_render_page_person_keeps_infobox_subdir_and_categories():
    page = {"title": "Celaena Sardothien", "entity_type": "PERSON", "importance": "principal",
            "infobox_fields": {"nom": "Celaena"}, "content": "## Biographie\n\nHéroïne."}
    rel_path, content = render_page(page, _LABELS)
    assert rel_path == "characters/Celaena_Sardothien.wiki"
    assert "{{Infobox character" in content
    assert "[[Category:Personnages]]" in content


def test_render_page_synopsis_goes_to_wiki_root_without_infobox():
    page = {"title": "Synopsis", "entity_type": "SYNOPSIS", "importance": "principal",
            "infobox_fields": {}, "content": "## Synopsis\n\nL'intrigue du livre."}
    rel_path, content = render_page(page, _LABELS)
    assert rel_path == "Synopsis.wiki"
    assert "{{Infobox" not in content
    assert "[[Category:" not in content
    assert "== Synopsis ==" in content
    assert "L'intrigue du livre." in content
