"""STU-612: the plan / fan-out / replay machinery — wiring, not generation.

Every test is LLM-free: the fan-out subprocess is mocked, and the walks run
through the same runner seam the rest of the suite already exercises.
"""

import json

import scripts.generate_wiki_pages as gwp
from scripts.generate_wiki_pages import (
    CollectingRunner,
    ReplayRunner,
    _fanout_results_by_key,
    _item_key,
)


ENTITY = {"canonical_name": "Lucy", "type": "PERSON", "importance": "principal"}

ITEM = {
    "title": "Lucy",
    "importance": "principal",
    "entity_type": "PERSON",
    "max_tokens": 900,
    "language": "en",
    "forbidden_names": [],
    "file_path": "",
    "prompt": "Write the biography section.",
}

PAGE_PAYLOAD = {
    "title": "Lucy",
    "content": "## Biographie\n\nLucy entre dans l'armoire.",
    "infobox_fields": {},
    "categories": [],
    "valid": True,
    "errors": [],
    "error_codes": [],
    "feedback": "",
}


def test_collecting_runner_records_each_item_once_and_fakes_success():
    runner = CollectingRunner()
    r1 = runner.run_item(dict(ITEM), ENTITY, timeout=5)
    r2 = runner.run_item(dict(ITEM), ENTITY, timeout=5)

    assert len(runner.items) == 1
    assert list(runner.items.values())[0]["prompt"] == ITEM["prompt"]
    # The fake success keeps the walk moving: non-empty content, no error.
    assert not r1.get("error") and r1["content"] and r2["content"]


def test_collecting_runner_fake_is_a_valid_page_for_a_non_person_entity():
    """The non-PERSON single-shot path returns the runner result as the page and
    the walk's _commit validates it as a WikiPage — a fake without the identity
    fields crashed the plan walk on the first PLACE of a book."""
    from wiki_creator.types import WikiPage

    place = {"canonical_name": "Port Saffron", "type": "PLACE", "importance": "figurant"}
    fake = CollectingRunner().run_item(dict(ITEM), place, timeout=5)

    page = WikiPage(**fake)
    assert page.importance == "figurant"
    assert page.entity_type == "PLACE"


def test_replay_runner_serves_a_success_as_a_parsed_page():
    key = _item_key(ITEM)
    runner = ReplayRunner({key: {"status": "success", "output": dict(PAGE_PAYLOAD), "run_id": "r-1"}})

    result = runner.run_item(dict(ITEM), ENTITY, timeout=5)

    assert not result.get("error")
    assert "Lucy entre dans l'armoire" in result["content"]
    assert result["run_metadata"]["run_id"] == "r-1"


def test_replay_runner_maps_a_failed_item_to_the_error_contract():
    key = _item_key(ITEM)
    runner = ReplayRunner({key: {"status": "failed", "error": "child boom", "run_id": "r-2"}})

    result = runner.run_item(dict(ITEM), ENTITY, timeout=5)

    assert result["error"] == "studio_map_item_failed"
    assert result["raw_response"] == "child boom"
    assert result["run_metadata"]["run_id"] == "r-2"


def test_replay_runner_missing_result_is_an_error_not_a_crash():
    runner = ReplayRunner({})
    result = runner.run_item(dict(ITEM), ENTITY, timeout=5)
    assert result["error"] == "studio_map_item_missing"


def test_replay_runner_records_the_in_walk_retry_and_serves_the_second_pass():
    """The forbidden-name retry re-requests the same item: without a second
    pass it is recorded in retry_items; with one, the retry gets the fresh
    attempt-2 output — the real second roll the attempt key buys (STU-612)."""
    key = _item_key(ITEM)
    first = {key: {"status": "success", "output": dict(PAGE_PAYLOAD), "run_id": "r-1"}}

    probe = ReplayRunner(first)
    probe.run_item(dict(ITEM), ENTITY, timeout=5)
    probe.run_item(dict(ITEM), ENTITY, timeout=5)
    assert list(probe.retry_items) == [key]

    second_payload = {**PAGE_PAYLOAD, "content": "## Biographie\n\nSecond roll."}
    final = ReplayRunner(first, {key: {"status": "success", "output": second_payload, "run_id": "r-9"}})
    final.run_item(dict(ITEM), ENTITY, timeout=5)
    retry = final.run_item(dict(ITEM), ENTITY, timeout=5)
    assert final.retry_items == {}
    assert "Second roll" in retry["content"]
    assert retry["run_metadata"]["run_id"] == "r-9"


def test_fanout_results_by_key_indexes_and_ignores_garbage():
    keys = [_item_key(ITEM), _item_key({**ITEM, "prompt": "other"})]
    map_output = {"results": [
        {"index": 1, "status": "success", "output": dict(PAGE_PAYLOAD)},
        {"index": 7, "status": "success"},  # out of range — dropped
        "garbage",
    ]}
    by_key = _fanout_results_by_key(keys, map_output)
    assert list(by_key) == [keys[1]]
    assert _fanout_results_by_key(keys, None) == {}


def test_item_key_is_stable_and_input_sensitive():
    assert _item_key(dict(ITEM)) == _item_key(json.loads(json.dumps(ITEM)))
    assert _item_key(ITEM) != _item_key({**ITEM, "prompt": "changed"})


def test_generate_pages_fanout_end_to_end(tmp_path, monkeypatch):
    """Plan walk enumerates the item, one fan-out serves it, the final walk
    writes the real output file — zero per-call subprocess."""
    batch = {"batch_id": "b1", "entities": [dict(ENTITY, context_by_chapter={"1": ["Lucy opens the wardrobe."]})]}
    config = gwp.GenerationConfig(
        book_title="Narnia",
        generation_cfg={},
        output_file=str(tmp_path / "wiki_pages.json"),
        debug_dir=tmp_path / "debug",
        language="en",
    )

    fanout_calls: list[tuple[int, int]] = []

    def fake_fanout(items, fingerprint, attempt, timeout):
        fanout_calls.append((len(items), attempt))
        payload = {**PAGE_PAYLOAD, "content": "## Biographie\n\nGenerated once."}
        return ({
            "total": len(items), "succeeded": len(items), "failed": 0, "resumed": 0,
            "results": [
                {"index": i, "status": "success", "output": dict(payload), "run_id": f"r-{i}"}
                for i in range(len(items))
            ],
        }, None)

    monkeypatch.setattr(gwp, "_run_pages_fanout", fake_fanout)

    pages = gwp.generate_pages_fanout([("b1.json", batch)], config)

    assert fanout_calls and all(attempt == 1 for _, attempt in fanout_calls)
    assert any("Generated once" in p.get("content", "") for p in pages)
    written = json.loads((tmp_path / "wiki_pages.json").read_text(encoding="utf-8"))
    assert written  # final walk wrote the real file
