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
        {"title": "Chaol", "entity_type": "PERSON", "importance": "secondary",
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


# --- STU-492: mw-collapsible sections + relations index ---


def _page():
    return {
        "title": "Celaena", "entity_type": "PERSON", "importance": "principal",
        "content": "## Biographie\n\nBio.\n\n## Relations\n\nProse.",
        "infobox_fields": {"nom": "Celaena"},
        "content_units": [
            {"section": "biography", "revealed_at_chapter": 1},
            {"section": "relationships", "revealed_at_chapter": 20},
        ],
        "relationship_index": ["* [[Chaol]] — amoureux (ch.1→ch.55)"],
    }


LABELS = {"persons": "Personnages", "principal": "Personnages principaux",
          "secondary": "Personnages secondaires", "locations": "Lieux",
          "organizations": "Organisations", "events": "Événements",
          "persons_by_tome": "Personnages du Tome {n}", "locations_by_tome": "Lieux du Tome {n}",
          "organizations_by_tome": "Organisations du Tome {n}"}


def test_render_page_off_by_default_no_collapsible_but_index_present():
    _, content = render_page(_page(), LABELS)
    assert "mw-collapsible" not in content              # feature off
    assert "''Évolution :''" in content                # index always injected
    assert "* [[Chaol]] — amoureux (ch.1→ch.55)" in content


def test_render_page_collapses_late_sections_when_configured():
    _, content = render_page(_page(), LABELS, collapse_after=5)
    # Relations revealed ch.20 > 5 → wrapped; index rides inside it
    assert 'data-expandtext="Chapitre 20 — révéler"' in content
    assert content.index("mw-collapsible") < content.index("Évolution")
    assert "== Biographie ==" in content                # ch.1 <= 5 stays open
    assert "mw-collapsible mw-collapsed\">\n== Biographie" not in content


# --- STU-567: infobox status/death gated by spoiler mode ---


def _person_with_status():
    page = _page()
    page["infobox_fields"] = {"nom": "Brom", "status": "Décédé",
                              "death": "Tué par Durza à Farthen Dûr"}
    return page


def test_render_page_gates_infobox_status_when_spoiler_on():
    _, content = render_page(_person_with_status(), LABELS, collapse_after=5)
    assert '|status=<span class="mw-collapsible mw-collapsed"' in content
    assert '|death=<span class="mw-collapsible mw-collapsed"' in content
    assert "Décédé</span>" in content
    assert "|nom=Brom" in content  # identity row untouched


def test_render_page_infobox_status_open_when_spoiler_off():
    _, content = render_page(_person_with_status(), LABELS)
    assert "|status=Décédé" in content
    assert "|death=Tué par Durza à Farthen Dûr" in content
    assert "mw-collapsible" not in content


# --- STU-494: per-relation subsection collapsibles ---


def test_render_page_per_relation_collapsibles():
    page = {
        "title": "Chaol",
        "entity_type": "PERSON",
        "importance": "principal",
        "infobox_fields": {},
        "content": ("## Relations\n\n"
                    "### [[Celaena]]\n\nProse arc.\n\n"
                    "### [[Cain]]\n\nRival.\n"),
        "relation_units": [{"name": "Celaena", "revealed_at_chapter": 55},
                           {"name": "Cain", "revealed_at_chapter": 2}],
        "relationship_index": [],
    }
    from scripts.wiki_export import render_page
    _, out = render_page(page, LABELS, collapse_after=3)
    assert 'data-expandtext="Chapitre 55 — révéler"' in out  # Celaena gated
    assert out.count("mw-collapsible") == 1                   # Cain (2<=3) not gated
    assert "''Évolution :''" not in out                       # dated index dropped


def test_render_page_per_relation_no_collapse_config():
    page = {
        "title": "Chaol", "entity_type": "PERSON", "importance": "principal",
        "infobox_fields": {},
        "content": "## Relations\n\n### [[Celaena]]\n\nProse.\n",
        "relation_units": [{"name": "Celaena", "revealed_at_chapter": 55}],
        "relationship_index": [],
    }
    from scripts.wiki_export import render_page
    _, out = render_page(page, LABELS, collapse_after=None)
    assert "=== [[Celaena]] ===" in out
    assert "mw-collapsible" not in out


def test_render_page_per_relation_still_gates_non_relationship_sections():
    page = {
        "title": "Chaol",
        "entity_type": "PERSON",
        "importance": "principal",
        "infobox_fields": {},
        "content": ("## Biographie\n\nBio tardive.\n\n## Relations\n\n"
                    "### [[Celaena]]\n\nProse.\n"),
        "content_units": [{"section": "biography", "revealed_at_chapter": 40}],
        "relation_units": [{"name": "Celaena", "revealed_at_chapter": 55}],
        "relationship_index": [],
    }
    from scripts.wiki_export import render_page
    _, out = render_page(page, LABELS, collapse_after=3)
    assert 'data-expandtext="Chapitre 40 — révéler"' in out  # Biographie gated
    assert "Chapitre 55" in out                              # Celaena gated
    assert out.count("mw-collapsible") == 2


# --- STU-511: collective page for a collated tier ---


def test_render_page_collation_goes_to_wiki_root_without_infobox_or_categories():
    page = {"title": "Personnages mineurs", "entity_type": "COLLATION", "importance": "figurant",
            "infobox_fields": {}, "content": "## Cain\n\nMentionné 3 fois dans 1 chapitre(s)."}
    rel_path, content = render_page(page, _LABELS)
    assert rel_path == "Personnages_mineurs.wiki"
    assert "{{Infobox" not in content
    assert "[[Category:" not in content
    assert "== Cain ==" in content
