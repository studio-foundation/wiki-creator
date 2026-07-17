"""Tests for scripts/scrape_fandom_bulk.py — infobox identification (STU-557)."""
from unittest.mock import patch

from scripts.scrape_fandom_bulk import (
    WikiInfoboxTemplates,
    is_infobox_template,
    normalize_template_name,
    parse_infobox,
    resolve_infobox_templates,
    zero_infobox_reason,
)

# The five conventions the corpus actually holds (STU-557). Sources are the
# discriminating head of the real templates, not invented markup.
PORTABLE_SOURCE = """\
<infobox>
  <title source="name"><default>{{PAGENAME}}</default></title>
  <data source="species"><label>Species</label></data>
</infobox>
"""

WRAPPER_SOURCE = """\
{{Charcat/deep
|name = {{{name|}}}
|affiliation = {{{affiliation|}}}
}}
"""

TITLED_NON_PORTABLE_SOURCE = """\
{| class="infobox"
! Name
| {{{name|}}}
|}
"""


def test_normalize_template_name_folds_mediawiki_title_rules():
    assert normalize_template_name("character") == "Character"
    assert normalize_template_name("Infobox_character") == "Infobox character"
    assert normalize_template_name("  Charcat  ") == "Charcat"


def test_normalize_template_name_keeps_case_after_first_letter():
    # MediaWiki only case-folds the first letter; `charCat` is not `Charcat`.
    assert normalize_template_name("charCat") == "CharCat"


def test_is_infobox_template_by_title():
    assert is_infobox_template("Template:Infobox character", TITLED_NON_PORTABLE_SOURCE)


def test_is_infobox_template_by_portable_markup_when_title_is_silent():
    # ACOTAR/Inheritance/Enkidiev/Spiderwick: the template is just `Character`.
    assert is_infobox_template("Template:Character", PORTABLE_SOURCE)


def test_is_infobox_template_rejects_a_wrapper_whose_markup_is_one_call_away():
    # Warriors' `Charcat`: an infobox, but the `<infobox>` lives in
    # `Charcat/deep`. Reachable only by per-wiki declaration.
    assert not is_infobox_template("Template:Charcat", WRAPPER_SOURCE)


def test_is_infobox_template_tolerates_a_missing_source():
    assert not is_infobox_template("Template:Quote", None)
    assert is_infobox_template("Template:Infobox book", None)


def test_is_infobox_template_does_not_match_infobox_as_a_substring_of_a_tag():
    # `<infoboxes>` is not Portable Infobox markup; the word boundary matters.
    assert not is_infobox_template("Template:Quote", "<infoboxes-gallery />")


def test_wiki_infobox_templates_matches_a_page_template_by_normalized_name():
    templates = WikiInfoboxTemplates({"Infobox character", "Character"})
    assert templates.is_infobox("character")
    assert templates.is_infobox("Infobox_character")
    assert not templates.is_infobox("Quote")


def test_parse_infobox_uses_the_wikis_own_template_names():
    wikitext = """\
{{Quote|Some epigraph|Chapter 1}}
{{Character
| name    = Feyre Archeron
| species = High Fae
}}
== Biography ==
"""
    templates = WikiInfoboxTemplates({"Character"})
    assert parse_infobox(wikitext, templates) == {
        "name": "Feyre Archeron",
        "species": "High Fae",
    }


def test_parse_infobox_skips_a_well_filled_non_infobox_template():
    # The trap STU-557 names: `Dialogue` has >=4 params and is not an infobox.
    wikitext = """\
{{Dialogue
| speaker1 = Feyre
| line1    = Hello
| speaker2 = Rhysand
| line2    = Hello yourself
}}
"""
    templates = WikiInfoboxTemplates({"Character"})
    assert parse_infobox(wikitext, templates) == {}


def test_parse_infobox_returns_empty_when_the_wiki_has_no_infobox_templates():
    templates = WikiInfoboxTemplates(set())
    assert parse_infobox("{{Character|name=Feyre}}", templates) == {}


def test_resolve_infobox_templates_unions_title_and_markup_tests():
    titles = ["Template:Character", "Template:Quote", "Template:Infobox book"]
    sources = {
        "Template:Character": PORTABLE_SOURCE,
        "Template:Quote": "''{{{1}}}''",
        "Template:Infobox book": TITLED_NON_PORTABLE_SOURCE,
    }
    with patch("scripts.scrape_fandom_bulk.fetch_template_namespace_prefix", return_value="Template"), \
            patch("scripts.scrape_fandom_bulk.fetch_template_namespace_titles", return_value=titles), \
            patch("scripts.scrape_fandom_bulk.fetch_pages_batch", return_value=sources):
        templates = resolve_infobox_templates("http://x/api.php")
    assert templates.names == {"Character", "Infobox book"}


def test_resolve_infobox_templates_strips_a_localized_namespace_prefix():
    # Enkidiev (fr) names the Template: namespace `Modèle:`. A page still calls
    # {{Roi+Dieu}}, so a name left prefixed matches nothing and the whole wiki
    # silently parses zero infoboxes.
    with patch("scripts.scrape_fandom_bulk.fetch_template_namespace_prefix", return_value="Modèle"), \
            patch("scripts.scrape_fandom_bulk.fetch_template_namespace_titles", return_value=["Modèle:Roi+Dieu"]), \
            patch("scripts.scrape_fandom_bulk.fetch_pages_batch", return_value={"Modèle:Roi+Dieu": PORTABLE_SOURCE}):
        templates = resolve_infobox_templates("http://x/api.php")
    assert templates.names == {"Roi+Dieu"}
    assert templates.is_infobox("Roi+Dieu")
    assert templates.titles() == ["Modèle:Roi+Dieu"]


def test_resolve_infobox_templates_adds_declared_names():
    # Warriors declares `Charcat`; neither test can find it.
    with patch("scripts.scrape_fandom_bulk.fetch_template_namespace_prefix", return_value="Template"), \
            patch("scripts.scrape_fandom_bulk.fetch_template_namespace_titles", return_value=["Template:Charcat"]), \
            patch("scripts.scrape_fandom_bulk.fetch_pages_batch", return_value={"Template:Charcat": WRAPPER_SOURCE}):
        templates = resolve_infobox_templates("http://x/api.php", declared=["Charcat"])
    assert templates.is_infobox("Charcat")


def test_resolve_infobox_templates_declares_a_name_the_wiki_never_lists():
    # A declaration is a claim about the wiki; if the template is absent the
    # declaration is honoured anyway rather than silently dropped.
    with patch("scripts.scrape_fandom_bulk.fetch_template_namespace_prefix", return_value="Template"), \
            patch("scripts.scrape_fandom_bulk.fetch_template_namespace_titles", return_value=[]), \
            patch("scripts.scrape_fandom_bulk.fetch_pages_batch", return_value={}):
        templates = resolve_infobox_templates("http://x/api.php", declared=["Charcat"])
    assert templates.is_infobox("Charcat")


def test_zero_infobox_reason_names_an_unidentified_template():
    reason = zero_infobox_reason(WikiInfoboxTemplates(set()))
    assert "no infobox template found on this wiki" in reason


def test_zero_infobox_reason_names_pages_that_carry_no_infobox():
    # discworld/inheritance: the wiki has infobox templates, the sampled pages
    # are stubs that call none. A different failure, and not ours.
    reason = zero_infobox_reason(WikiInfoboxTemplates({"Character"}))
    assert "the pages sampled carry no infobox" in reason
