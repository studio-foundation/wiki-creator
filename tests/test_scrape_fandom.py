"""Tests for scripts/scrape_fandom.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.scrape_fandom import parse_infobox, parse_body


WIKITEXT_WITH_INFOBOX = """\
{{Infobox character
| name    = Celaena Sardothien
| species = Human
| status  = Alive
| gender  = Female
}}
== Biography ==
Celaena is an assassin.
"""

WIKITEXT_NO_INFOBOX = """\
== Biography ==
A short article with no infobox.
"""


def test_parse_infobox_extracts_fields():
    result = parse_infobox(WIKITEXT_WITH_INFOBOX)
    assert result["name"] == "Celaena Sardothien"
    assert result["species"] == "Human"
    assert result["status"] == "Alive"


def test_parse_infobox_returns_empty_dict_when_absent():
    result = parse_infobox(WIKITEXT_NO_INFOBOX)
    assert result == {}


def test_parse_infobox_strips_wikitext_from_values():
    wikitext = """\
{{Infobox character
| home = [[Rifthold]]
}}
"""
    result = parse_infobox(wikitext)
    assert result["home"] == "Rifthold"


WIKITEXT_BODY = """\
{{Infobox character
| name = Celaena
}}
== Biography ==
Celaena Sardothien is a famous assassin.<ref>Source</ref>

She lives in [[Rifthold]].

== Relationships ==
Her mentor is [[Arobynn Hamel]].

[[File:Celaena.png|thumb|Celaena]]
"""


def test_parse_body_removes_templates():
    result = parse_body(WIKITEXT_BODY)
    assert "{{" not in result
    assert "}}" not in result


def test_parse_body_converts_headings():
    result = parse_body(WIKITEXT_BODY)
    assert "## Biography" in result
    assert "## Relationships" in result


def test_parse_body_removes_refs():
    result = parse_body(WIKITEXT_BODY)
    assert "<ref>" not in result
    assert "Source" not in result


def test_parse_body_removes_file_links():
    result = parse_body(WIKITEXT_BODY)
    assert "File:" not in result
    assert "Celaena.png" not in result


def test_parse_body_keeps_plain_text():
    result = parse_body(WIKITEXT_BODY)
    assert "Celaena Sardothien is a famous assassin" in result


def test_parse_body_is_stub_when_short():
    result = parse_body("== Section ==\nShort.")
    assert len(result) < 200
