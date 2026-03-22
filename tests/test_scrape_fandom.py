"""Tests for scripts/scrape_fandom.py."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.scrape_fandom import parse_infobox


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
