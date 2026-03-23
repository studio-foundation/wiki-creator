"""Tests for scripts/scrape_fandom.py."""
import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.scrape_fandom import parse_infobox, parse_body, is_redirect, is_stub, fetch_category_members, fetch_wikitext, derive_wiki_slug, main


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


def test_is_redirect_detects_uppercase():
    assert is_redirect("#REDIRECT [[Celaena Sardothien]]") is True


def test_is_redirect_detects_lowercase():
    assert is_redirect("#redirect [[Celaena Sardothien]]") is True


def test_is_redirect_returns_false_for_normal_page():
    assert is_redirect("== Biography ==\nSome content.") is False


def test_is_stub_when_body_short():
    assert is_stub("Too short.") is True


def test_is_stub_when_body_long_enough():
    assert is_stub("x" * 200) is False


API_URL = "https://throneofglass.fandom.com/api.php"


def _mock_response(data: dict) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.json.return_value = data
    mock_resp.raise_for_status.return_value = None
    return mock_resp


def test_fetch_category_members_returns_titles():
    page_data = {
        "query": {
            "categorymembers": [
                {"title": "Celaena Sardothien"},
                {"title": "Dorian Havilliard"},
            ]
        }
    }
    with patch("scripts.scrape_fandom.requests.get", return_value=_mock_response(page_data)) as mock_get:
        with patch("scripts.scrape_fandom.time.sleep"):
            titles = fetch_category_members(API_URL, "Characters")
    assert titles == ["Celaena Sardothien", "Dorian Havilliard"]


def test_fetch_category_members_paginates():
    page1 = {
        "query": {"categorymembers": [{"title": "Page A"}]},
        "continue": {"cmcontinue": "token_abc", "continue": "-||"},
    }
    page2 = {
        "query": {"categorymembers": [{"title": "Page B"}]},
    }
    responses = [_mock_response(page1), _mock_response(page2)]
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            titles = fetch_category_members(API_URL, "Characters")
    assert titles == ["Page A", "Page B"]


def test_fetch_wikitext_returns_content():
    response_data = {
        "query": {
            "pages": {
                "123": {
                    "revisions": [{"*": "{{Infobox character}}\n== Bio ==\nContent here."}]
                }
            }
        }
    }
    with patch("scripts.scrape_fandom.requests.get", return_value=_mock_response(response_data)):
        with patch("scripts.scrape_fandom.time.sleep"):
            result = fetch_wikitext(API_URL, "Celaena Sardothien")
    assert "Infobox character" in result


def test_fetch_wikitext_returns_none_for_missing_page():
    response_data = {"query": {"pages": {"-1": {}}}}
    with patch("scripts.scrape_fandom.requests.get", return_value=_mock_response(response_data)):
        with patch("scripts.scrape_fandom.time.sleep"):
            result = fetch_wikitext(API_URL, "Nonexistent Page")
    assert result is None


def test_derive_wiki_slug_strips_fandom_suffix():
    assert derive_wiki_slug("https://throneofglass.fandom.com") == "throneofglass"


def test_derive_wiki_slug_with_trailing_slash():
    assert derive_wiki_slug("https://throneofglass.fandom.com/") == "throneofglass"


FAKE_CATEGORY_RESPONSE = {
    "query": {
        "categorymembers": [
            {"title": "Celaena Sardothien"},
        ]
    }
}

FAKE_PAGE_RESPONSE = {
    "query": {
        "pages": {
            "1": {
                "revisions": [{
                    "*": (
                        "{{Infobox character\n"
                        "| species = Human\n"
                        "| status  = Alive\n"
                        "}}\n"
                        "== Biography ==\n"
                        + "Celaena Sardothien is a world-famous assassin. " * 10
                    )
                }]
            }
        }
    }
}


def test_main_writes_jsonl(tmp_path):
    out_file = tmp_path / "output.jsonl"
    responses = [
        _mock_response(FAKE_CATEGORY_RESPONSE),  # discover PERSON
        _mock_response(FAKE_PAGE_RESPONSE),       # fetch page
    ]
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            main([
                "--wiki", "https://throneofglass.fandom.com",
                "--types", "PERSON",
                "--lang", "en",
                "--out", str(out_file),
            ])
    assert out_file.exists()
    lines = out_file.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["source"] == "fandom"
    assert record["wiki_slug"] == "throneofglass"
    assert record["page_title"] == "Celaena Sardothien"
    assert record["entity_type"] == "PERSON"
    assert record["infobox_fields"]["species"] == "Human"
    assert record["content_lang"] == "en"
    assert "scraped_at" in record


def test_main_skips_redirects(tmp_path):
    out_file = tmp_path / "output.jsonl"
    redirect_response = {
        "query": {
            "pages": {"1": {"revisions": [{"*": "#REDIRECT [[Celaena Sardothien]]"}]}}
        }
    }
    responses = [
        _mock_response(FAKE_CATEGORY_RESPONSE),
        _mock_response(redirect_response),
    ]
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            main([
                "--wiki", "https://throneofglass.fandom.com",
                "--types", "PERSON",
                "--out", str(out_file),
            ])
    # File may not exist or be empty — either is correct
    if out_file.exists():
        assert out_file.read_text().strip() == ""


def test_main_skips_stubs(tmp_path):
    out_file = tmp_path / "output.jsonl"
    stub_response = {
        "query": {
            "pages": {"1": {"revisions": [{"*": "{{Infobox character}}\n== Bio ==\nToo short."}]}}
        }
    }
    responses = [
        _mock_response(FAKE_CATEGORY_RESPONSE),
        _mock_response(stub_response),
    ]
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            main([
                "--wiki", "https://throneofglass.fandom.com",
                "--types", "PERSON",
                "--out", str(out_file),
            ])
    if out_file.exists():
        assert out_file.read_text().strip() == ""


def test_main_respects_limit(tmp_path):
    out_file = tmp_path / "output.jsonl"
    category_response = {
        "query": {
            "categorymembers": [
                {"title": "Page A"},
                {"title": "Page B"},
                {"title": "Page C"},
            ]
        }
    }
    long_body = "Some content about a character. " * 20
    page_response = {
        "query": {
            "pages": {
                "1": {"revisions": [{"*": f"{{{{Infobox character}}}}\n== Bio ==\n{long_body}"}]}
            }
        }
    }
    responses = (
        [_mock_response(category_response)]
        + [_mock_response(page_response)] * 3
    )
    with patch("scripts.scrape_fandom.requests.get", side_effect=responses):
        with patch("scripts.scrape_fandom.time.sleep"):
            main([
                "--wiki", "https://throneofglass.fandom.com",
                "--types", "PERSON",
                "--limit", "2",
                "--out", str(out_file),
            ])
    lines = out_file.read_text().strip().splitlines()
    assert len(lines) == 2
