"""Tests for load_wiki_pages.py — _failed page filtering at pipeline entry point."""
import io
import json
import sys
from pathlib import Path

import pytest
import yaml

from wiki_creator import studio_io
from wiki_creator.types import WikiPage

from scripts.load_wiki_pages import _filter_failed_pages, _read_pages, main


def _page(**overrides) -> WikiPage:
    fields = {"title": "A", "entity_type": "PERSON", "importance": "principal",
              "infobox_fields": {}, "content": "content"}
    fields.update(overrides)
    return WikiPage(**fields)


def test_filter_failed_pages_excludes_failed():
    pages = [
        _page(title="Celaena", content="## Bio\n\nHero."),
        _page(title="Arobynn Hamel", content="", _failed=True),
        _page(title="Chaol", importance="secondary", content="## Bio\n\nCaptain."),
    ]
    result = _filter_failed_pages(pages)
    assert len(result) == 2
    assert all(not p._failed for p in result)
    assert {p.title for p in result} == {"Celaena", "Chaol"}


def test_filter_failed_pages_all_valid():
    pages = [_page()]
    assert _filter_failed_pages(pages) == pages


def test_filter_failed_pages_all_failed():
    pages = [_page(title="Arobynn", content="", _failed=True)]
    assert _filter_failed_pages(pages) == []


def test_filter_failed_pages_empty():
    assert _filter_failed_pages([]) == []


def test_read_pages_validates_and_round_trips(tmp_path):
    path = tmp_path / "wiki_pages.json"
    path.write_text(json.dumps({"pages": [
        {"title": "Celaena", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "## Bio\n\nHero.",
         "run_metadata": {"command": ["studio"], "run_id": "r1"},
         "_identity_corrected": True},
    ]}), encoding="utf-8")
    pages = _read_pages(path)
    assert pages == [WikiPage(
        title="Celaena", entity_type="PERSON", importance="principal",
        content="## Bio\n\nHero.", run_metadata={"command": ["studio"], "run_id": "r1"},
        _identity_corrected=True,
    )]


def test_read_pages_rejects_schema_drift(tmp_path):
    """An unknown key on a wiki_pages.json page must be rejected."""
    path = tmp_path / "wiki_pages.json"
    path.write_text(json.dumps({"pages": [
        {"title": "Celaena", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "## Bio", "surprise": "unexpected"},
    ]}), encoding="utf-8")
    with pytest.raises(studio_io.ArtifactSchemaError):
        _read_pages(path)


# --- SP4 synopsis page (STU-482) ---

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


# --- STU-511: collective pages ---

from scripts.load_wiki_pages import _load_extra_pages


def _collation_page(**extra):
    page = {"title": "Personnages mineurs", "entity_type": "COLLATION", "importance": "figurant",
            "infobox_fields": {}, "content": "## Cain\n\nMentionné 3 fois dans 1 chapitre(s)."}
    page.update(extra)
    return page


def test_load_collation_pages_reads_artifact(tmp_path):
    (tmp_path / "collation_pages.json").write_text(
        json.dumps({"pages": [_collation_page(), _collation_page(_failed=True)]}), encoding="utf-8"
    )
    pages = _load_extra_pages(tmp_path, "collation_pages.json", "collation pages")
    assert [p["entity_type"] for p in pages] == ["COLLATION"]


def test_load_collation_pages_absent(tmp_path):
    assert _load_extra_pages(tmp_path, "collation_pages.json", "collation pages") == []


def _run_main(tmp_path, monkeypatch, capsys, naming_cfg=None):
    """Drive load_wiki_pages.main end-to-end with two homonym pages."""
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "01"
    processing.mkdir(parents=True)
    (processing / "wiki_pages.json").write_text(json.dumps({"pages": [
        {"title": "Adarlan", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "## Bio\n\nKing."},
        {"title": "Adarlan", "entity_type": "PLACE", "importance": "principal",
         "infobox_fields": {}, "content": "## Bio\n\nKingdom."},
    ]}), encoding="utf-8")
    cfg = {
        "file_path": str(tmp_path / "library" / "a" / "s" / "books" / "01.epub"),
        "export": {"categories": {"labels": {"persons": "Characters", "locations": "Locations"}}},
    }
    if naming_cfg is not None:
        cfg["naming"] = naming_cfg
    payload = {"additional_context": yaml.safe_dump(cfg)}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    main()
    return json.loads(capsys.readouterr().out)["pages"]


def test_main_disambiguates_cross_type_homonyms(tmp_path, monkeypatch, capsys):
    titles = {p["title"] for p in _run_main(tmp_path, monkeypatch, capsys)}
    assert titles == {"Adarlan (Characters)", "Adarlan (Locations)"}


def test_main_merge_policy_leaves_titles_untouched(tmp_path, monkeypatch, capsys):
    pages = _run_main(tmp_path, monkeypatch, capsys, naming_cfg={"collision_policy": "merge"})
    assert [p["title"] for p in pages] == ["Adarlan", "Adarlan"]
