"""STU-671: `generation.single_call` collapses the PERSON per-section fan-out
(~6 calls → 1) by routing PERSON through the non-PERSON single-shot generator.

LLM-free: the walk runs through the CollectingRunner seam, so it counts the
planned map items (= the LLM calls a real run would dispatch) without a subprocess.
"""

from pathlib import Path

import pytest

import scripts.generate_wiki_pages as gwp
from scripts.generate_wiki_pages import CollectingRunner


def test_single_call_default_off_and_toggle():
    assert gwp.single_call_pages_enabled(None) is False
    assert gwp.single_call_pages_enabled({}) is False
    assert gwp.single_call_pages_enabled({"generation": {}}) is False
    assert gwp.single_call_pages_enabled({"generation": {"single_call": True}}) is True
    assert gwp.single_call_pages_enabled({"generation": {"single_call": False}}) is False


def test_single_call_rejects_non_bool():
    with pytest.raises(ValueError):
        gwp.single_call_pages_enabled({"generation": {"single_call": "yes"}})


def _routing_probe(monkeypatch):
    seen = {}
    monkeypatch.setattr(gwp, "_run_generation_sectioned", lambda **kw: seen.setdefault("path", "sectioned"))
    monkeypatch.setattr(gwp, "_run_generation_for_entity", lambda **kw: seen.setdefault("path", "single"))
    return seen


def _run(entity, book_config, monkeypatch):
    seen = _routing_probe(monkeypatch)
    gwp._run_generation(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography"], max_tokens=500, dry_run=False,
        debug_dir=Path("/tmp"), book_config=book_config)
    return seen["path"]


def test_person_routes_sectioned_by_default(monkeypatch):
    person = {"type": "PERSON", "canonical_name": "Chaol"}
    assert _run(person, {}, monkeypatch) == "sectioned"


def test_person_routes_single_call_when_enabled(monkeypatch):
    person = {"type": "PERSON", "canonical_name": "Chaol"}
    cfg = {"generation": {"single_call": True}}
    assert _run(person, cfg, monkeypatch) == "single"


def test_non_person_always_single_shot(monkeypatch):
    place = {"type": "PLACE", "canonical_name": "Rifthold"}
    assert _run(place, {}, monkeypatch) == "single"
    assert _run(place, {"generation": {"single_call": True}}, monkeypatch) == "single"


def _plan_item_count(book_config, monkeypatch, tmp_path):
    # Pin the section set so the count reflects the fan-out shape, not template
    # resolution: three content sections + infobox/references (never LLM'd).
    monkeypatch.setattr(
        gwp, "generation_profile",
        lambda cfg, importance, etype=None: (
            ["infobox", "biography", "personality", "trivia", "references"], 500),
    )
    entity = {
        "canonical_name": "Chaol", "type": "PERSON", "importance": "principal",
        "aliases": [], "context_by_chapter": {"C01": ["ctx"]}, "context_chapters": [1],
        "relationships": [],
    }
    config = gwp.GenerationConfig(
        book_title="ToG", generation_cfg=(book_config.get("generation") or {}),
        output_file=str(tmp_path / "pages.json"), debug_dir=tmp_path,
        language="fr", book_config=book_config,
    )
    collector = CollectingRunner()
    gwp.generate_pages([("b1.json", {"batch_id": "b1", "entities": [entity]})],
                       config, runner=collector)
    return len(collector.items)


def test_fanout_collapses_to_one_item_when_enabled(monkeypatch, tmp_path):
    off = _plan_item_count({}, monkeypatch, tmp_path)
    on = _plan_item_count({"generation": {"single_call": True}}, monkeypatch, tmp_path)
    assert off == 3           # biography + personality + trivia, each its own call
    assert on == 1            # whole page in a single call
