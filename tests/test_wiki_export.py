"""Tests for wiki_export.py — _failed page filtering and the copyright gate."""
import sys
from pathlib import Path


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


# --- STU-486: per-tome categories in the rendered wikitext ---

_LABELS_WITH_TOMES = {
    **_LABELS,
    "persons_by_tome": "Personnages du Tome {n}",
    "locations_by_tome": "Lieux du Tome {n}",
    "organizations_by_tome": "Organisations du Tome {n}",
}


def test_render_page_person_present_in_two_tomes_gets_both_categories():
    page = {"title": "Chaol Westfall", "entity_type": "PERSON", "importance": "secondary",
            "infobox_fields": {}, "content": "## Biographie\n\nGarde du corps.",
            "books": ["01-throne-of-glass", "02-crown-of-midnight"]}
    _, content = render_page(page, _LABELS_WITH_TOMES)
    assert "[[Category:Personnages du Tome 1]]" in content
    assert "[[Category:Personnages du Tome 2]]" in content


def test_render_page_tome_two_only_entity_lacks_tome_one_category():
    page = {"title": "Dorian Havilliard", "entity_type": "PERSON", "importance": "secondary",
            "infobox_fields": {}, "content": "## Biographie\n\nPrince.",
            "books": ["02-crown-of-midnight"]}
    _, content = render_page(page, _LABELS_WITH_TOMES)
    assert "[[Category:Personnages du Tome 2]]" in content
    assert "[[Category:Personnages du Tome 1]]" not in content
