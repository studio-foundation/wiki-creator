"""Tests for scripts/generate_event_pages.py — the SP3 stage script."""
import json

import scripts.generate_event_pages as gep
from wiki_creator.event_pages import EVENT_ENTITY_TYPE


def _write_events(processing_dir, events):
    (processing_dir / "events.json").write_text(
        json.dumps({"events": events}, ensure_ascii=False), encoding="utf-8"
    )


def _events():
    return [
        {"event_id": "e_ch1_0", "chapter": 1, "description": "Celaena is freed",
         "participants": ["Celaena Sardothien"], "places": ["Endovier"],
         "outcome": None, "salience": 0.2, "source_bullets": ["C1: freed"]},
        {"event_id": "e_ch12_0", "chapter": 12, "description": "Celaena defeats Cain",
         "participants": ["Cain", "Celaena Sardothien"], "places": ["Rifthold"],
         "outcome": "Celaena defeats Cain despite the poison", "salience": 0.9,
         "source_bullets": ["C12: duel"]},
    ]


def _page_result(content="## Déroulement\n\nCelaena triomphe de Cain."):
    return {
        "title": "x",
        "importance": "principal",
        "entity_type": EVENT_ENTITY_TYPE,
        "infobox_fields": {},
        "content": content,
        "run_metadata": {"run_id": "r1"},
    }


def test_run_skips_when_events_missing(tmp_path):
    got = gep.run_for_processing(tmp_path, book_cfg={}, language="en")
    assert got is None
    assert not (tmp_path / "event_pages.json").exists()


def test_run_skips_when_no_event_above_threshold(tmp_path):
    _write_events(tmp_path, [_events()[0]])  # salience 0.2 only
    got = gep.run_for_processing(tmp_path, book_cfg={}, language="en")
    assert got is None


def test_run_dry_writes_stub_artifacts(tmp_path):
    _write_events(tmp_path, _events())
    pages = gep.run_for_processing(tmp_path, book_cfg={}, language="en", dry_run=True)
    assert len(pages) == 1  # only the salience-0.9 event clears the default threshold
    page = pages[0]
    assert page["title"] == "Celaena defeats Cain"
    assert page["entity_type"] == EVENT_ENTITY_TYPE
    assert page["infobox_fields"]["chapitre"] == "12"
    assert page["infobox_fields"]["name"] == "Celaena defeats Cain"
    assert not page.get("_failed")
    data = json.loads((tmp_path / "event_pages.json").read_text(encoding="utf-8"))
    assert data["pages"] == pages


def test_run_live_builds_page_with_deterministic_infobox_and_references(tmp_path, monkeypatch):
    _write_events(tmp_path, _events())
    (tmp_path / "epub_data.json").write_text(
        json.dumps({"title": "Throne of Glass"}), encoding="utf-8"
    )
    captured = {}

    def fake_execute(item_input, entity, timeout):
        captured["item_input"] = item_input
        return _page_result()

    monkeypatch.setattr(gep, "_execute_wiki_page_item", fake_execute)
    pages = gep.run_for_processing(tmp_path, book_cfg={}, language="en")

    page = pages[0]
    assert page["title"] == "Celaena defeats Cain"
    assert "## References" in page["content"]  # localized to output language (STU-514)
    assert "- Throne of Glass" in page["content"]
    # infobox is deterministic, not authored by the LLM
    assert page["infobox_fields"]["participants"] == "Cain, Celaena Sardothien"
    assert page["infobox_fields"]["issue"] == "Celaena defeats Cain despite the poison"
    assert "run_metadata" not in page
    # the writer prompt is anchored in the event's facts
    assert "Celaena defeats Cain" in captured["item_input"]["prompt"]


def test_threshold_config_overrides_default(tmp_path, monkeypatch):
    _write_events(tmp_path, _events())
    monkeypatch.setattr(gep, "_execute_wiki_page_item",
                        lambda item_input, entity, timeout: _page_result())
    book_cfg = {"generation": {"event_pages": {"salience_threshold": 0.1}}}
    pages = gep.run_for_processing(tmp_path, book_cfg=book_cfg, language="en")
    assert len(pages) == 2  # both events now clear the threshold


def test_generation_error_yields_failed_stub(tmp_path, monkeypatch):
    _write_events(tmp_path, _events())
    monkeypatch.setattr(gep, "_execute_wiki_page_item",
                        lambda item_input, entity, timeout: {"error": "studio_run_failed"})
    pages = gep.run_for_processing(tmp_path, book_cfg={}, language="en")
    assert pages[0]["_failed"] is True


def test_persistent_spoiler_is_rejected(tmp_path, monkeypatch):
    _write_events(tmp_path, _events())
    calls = []

    def fake_execute(item_input, entity, timeout):
        calls.append(item_input)
        return _page_result("## Déroulement\n\nAelin sauve le royaume.")

    monkeypatch.setattr(gep, "_execute_wiki_page_item", fake_execute)
    book_cfg = {"validation": {"forbidden_names": ["Aelin"]}}
    pages = gep.run_for_processing(tmp_path, book_cfg=book_cfg, language="en")
    assert len(calls) == 2  # initial + one retry
    assert pages[0]["_failed"] is True
    assert pages[0]["_spoiler_rejected"] is True


def test_duplicate_titles_are_disambiguated(tmp_path, monkeypatch):
    events = [
        {"event_id": "e_ch3_0", "chapter": 3, "description": "A duel", "participants": ["Celaena"],
         "places": [], "outcome": None, "salience": 0.9, "source_bullets": []},
        {"event_id": "e_ch8_0", "chapter": 8, "description": "A duel", "participants": ["Cain"],
         "places": [], "outcome": None, "salience": 0.8, "source_bullets": []},
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(gep, "_execute_wiki_page_item",
                        lambda item_input, entity, timeout: _page_result())
    pages = gep.run_for_processing(tmp_path, book_cfg={}, language="en")
    titles = [p["title"] for p in pages]
    assert titles == ["A duel", "A duel (chapter 8)"]


def test_same_chapter_duplicate_titles_stay_unique(tmp_path, monkeypatch):
    events = [
        {"event_id": f"e_ch5_{i}", "chapter": 5, "description": "A duel",
         "participants": ["Celaena"], "places": [], "outcome": None,
         "salience": 0.9 - i * 0.01, "source_bullets": []}
        for i in range(3)
    ]
    _write_events(tmp_path, events)
    monkeypatch.setattr(gep, "_execute_wiki_page_item",
                        lambda item_input, entity, timeout: _page_result())
    pages = gep.run_for_processing(tmp_path, book_cfg={}, language="en")
    titles = [p["title"] for p in pages]
    assert len(set(titles)) == len(titles)  # all unique despite identical description+chapter
    assert titles == ["A duel", "A duel (chapter 5)", "A duel (chapter 5, #2)"]
