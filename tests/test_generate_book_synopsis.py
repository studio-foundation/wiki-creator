"""Tests for scripts/generate_book_synopsis.py — the SP4 stage script."""
import json

import scripts.generate_book_synopsis as gbs
from wiki_creator.synopsis import SYNOPSIS_ENTITY_TYPE, SYNOPSIS_TITLE


def _write_events(processing_dir, events):
    (processing_dir / "events.json").write_text(
        json.dumps({"events": events}, ensure_ascii=False), encoding="utf-8"
    )


def _events():
    return [
        {"event_id": "e_ch1_0", "chapter": 1, "description": "Celaena is freed",
         "participants": ["Celaena Sardothien", "Dorian Havilliard"], "places": ["Endovier"],
         "outcome": None, "salience": 0.2, "source_bullets": ["C1: freed"]},
        {"event_id": "e_ch12_0", "chapter": 12, "description": "Celaena defeats Cain",
         "participants": ["Cain", "Celaena Sardothien"], "places": ["Rifthold"],
         "outcome": "Celaena defeats Cain", "salience": 1.0, "source_bullets": ["C12: duel"]},
    ]


def _page_result(content="## Synopsis\n\nCelaena est libérée puis triomphe de Cain."):
    return {
        "title": SYNOPSIS_TITLE,
        "importance": "principal",
        "entity_type": SYNOPSIS_ENTITY_TYPE,
        "infobox_fields": {},
        "content": content,
        "run_metadata": {"run_id": "r1"},
    }


# --- read_events ---


def test_read_events_distinguishes_absent_from_empty(tmp_path):
    assert gbs.read_events(tmp_path) is None
    _write_events(tmp_path, [])
    assert gbs.read_events(tmp_path) == []


def test_read_events_tolerates_invalid_json(tmp_path):
    (tmp_path / "events.json").write_text("{not json", encoding="utf-8")
    assert gbs.read_events(tmp_path) == []


# --- run_for_processing ---


def test_run_skips_when_events_missing(tmp_path):
    got = gbs.run_for_processing(tmp_path, book_cfg={}, language="en")
    assert got is None
    assert not (tmp_path / "book_synopsis.json").exists()


def test_run_skips_when_events_empty(tmp_path):
    _write_events(tmp_path, [])
    got = gbs.run_for_processing(tmp_path, book_cfg={}, language="en")
    assert got is None
    assert not (tmp_path / "book_synopsis.json").exists()


def test_run_dry_writes_stub_artifact(tmp_path):
    _write_events(tmp_path, _events())
    page = gbs.run_for_processing(tmp_path, book_cfg={}, language="en", dry_run=True)
    data = json.loads((tmp_path / "book_synopsis.json").read_text(encoding="utf-8"))
    assert data["page"] == page
    assert page["title"] == SYNOPSIS_TITLE
    assert page["entity_type"] == SYNOPSIS_ENTITY_TYPE
    assert not page.get("_failed")


def test_run_live_writes_page_with_references(tmp_path, monkeypatch):
    _write_events(tmp_path, _events())
    (tmp_path / "epub_data.json").write_text(
        json.dumps({"title": "Throne of Glass"}), encoding="utf-8"
    )
    captured = {}

    def fake_execute(item_input, entity, timeout):
        captured["item_input"] = item_input
        return _page_result()

    monkeypatch.setattr(gbs, "_execute_wiki_page_item", fake_execute)
    page = gbs.run_for_processing(tmp_path, book_cfg={}, language="en")

    assert page["title"] == SYNOPSIS_TITLE
    assert "## Références" in page["content"]
    assert "- Throne of Glass" in page["content"]
    assert page["infobox_fields"] == {}
    assert "run_metadata" not in page
    # the writer prompt is anchored in the events
    assert "[Chapitre 12] Celaena defeats Cain" in captured["item_input"]["prompt"]
    assert captured["item_input"]["title"] == SYNOPSIS_TITLE
    data = json.loads((tmp_path / "book_synopsis.json").read_text(encoding="utf-8"))
    assert data["page"] == page


def test_finalize_strips_authored_references_before_appending():
    result = _page_result(
        "## Synopsis\n\nDu texte.\n\n## Références\n\n- Un autre livre\n"
    )
    page = gbs._finalize_page(result, "Throne of Glass")
    assert "Un autre livre" not in page["content"]
    assert page["content"].count("## Références") == 1
    assert "- Throne of Glass" in page["content"]


def test_generation_error_yields_failed_stub(tmp_path, monkeypatch):
    _write_events(tmp_path, _events())
    monkeypatch.setattr(
        gbs, "_execute_wiki_page_item",
        lambda item_input, entity, timeout: {"error": "studio_run_failed"},
    )
    page = gbs.run_for_processing(tmp_path, book_cfg={}, language="en")
    assert page["_failed"] is True
    data = json.loads((tmp_path / "book_synopsis.json").read_text(encoding="utf-8"))
    assert data["page"]["_failed"] is True


def test_persistent_spoiler_is_rejected(tmp_path, monkeypatch):
    _write_events(tmp_path, _events())
    calls = []

    def fake_execute(item_input, entity, timeout):
        calls.append(item_input)
        return _page_result("## Synopsis\n\nAelin sauve le royaume.")

    monkeypatch.setattr(gbs, "_execute_wiki_page_item", fake_execute)
    book_cfg = {"validation": {"forbidden_names": ["Aelin"]}}
    page = gbs.run_for_processing(tmp_path, book_cfg=book_cfg, language="en")
    assert len(calls) == 2  # initial + one retry
    assert page["_failed"] is True
    assert page["_spoiler_rejected"] is True


def test_spoiler_retry_recovers(tmp_path, monkeypatch):
    _write_events(tmp_path, _events())
    outputs = [
        _page_result("## Synopsis\n\nAelin sauve le royaume."),
        _page_result("## Synopsis\n\nCelaena sauve le royaume."),
    ]
    monkeypatch.setattr(
        gbs, "_execute_wiki_page_item",
        lambda item_input, entity, timeout: outputs.pop(0),
    )
    book_cfg = {"validation": {"forbidden_names": ["Aelin"]}}
    page = gbs.run_for_processing(tmp_path, book_cfg=book_cfg, language="en")
    assert not page.get("_failed")
    assert "Celaena sauve le royaume" in page["content"]


def test_synopsis_config_caps_events(tmp_path, monkeypatch):
    events = _events() + [
        {"event_id": "e_ch1_1", "chapter": 1, "description": "a minor beat",
         "participants": [], "places": [], "outcome": None, "salience": 0.05,
         "source_bullets": ["C1: minor"]},
    ]
    _write_events(tmp_path, events)
    captured = {}

    def fake_execute(item_input, entity, timeout):
        captured["item_input"] = item_input
        return _page_result()

    monkeypatch.setattr(gbs, "_execute_wiki_page_item", fake_execute)
    book_cfg = {"generation": {"synopsis": {"max_events_per_chapter": 1, "max_tokens": 900}}}
    gbs.run_for_processing(tmp_path, book_cfg=book_cfg, language="en")
    prompt = captured["item_input"]["prompt"]
    assert "Celaena is freed" in prompt
    assert "a minor beat" not in prompt  # lower salience, capped out
    assert captured["item_input"]["max_tokens"] == 900
