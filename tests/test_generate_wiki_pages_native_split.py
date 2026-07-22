"""STU-621: the native plan / call / probe / call / post split.

The two nested `studio run` subprocesses of `generate_pages_fanout` become two
native `call: wiki-pages` stages; each Python stage re-runs the deterministic
walk and only the map outputs flow between them. Every test is LLM-free — the
map outputs are synthesized, no subprocess.
"""

import json

import scripts.generate_wiki_pages as gwp
from scripts.generate_wiki_pages import (
    _item_key,
    plan_generation,
    post_generation,
    probe_generation,
    wiki_pages_map_item,
)
from wiki_creator.paths import BookPaths


ENTITY = {"canonical_name": "Lucy", "type": "PERSON", "importance": "principal"}

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


def _book(tmp_path):
    """Minimal on-disk book: one batch, an epub_data.json for the title."""
    processing = tmp_path / "processing"
    wiki_inputs = tmp_path / "wiki_inputs"
    processing.mkdir()
    wiki_inputs.mkdir()
    (processing / "epub_data.json").write_text(
        json.dumps({"title": "Narnia", "chapters": []}), encoding="utf-8"
    )
    batch = {
        "batch_id": "b1",
        "entities": [dict(ENTITY, context_by_chapter={"1": ["Lucy opens the wardrobe."]})],
    }
    (wiki_inputs / "batch_0.json").write_text(json.dumps(batch), encoding="utf-8")
    paths = BookPaths(
        epub=tmp_path / "book.epub",
        processing=processing,
        wiki_inputs=wiki_inputs,
        output=tmp_path / "output",
    )
    return {"file_path": str(tmp_path / "book.epub")}, paths


def _map_output(items):
    payload = {**PAGE_PAYLOAD, "content": "## Biographie\n\nGenerated once."}
    return {
        "total": len(items), "succeeded": len(items), "failed": 0, "resumed": 0,
        "results": [
            {"index": i, "status": "success", "output": dict(payload), "run_id": f"r-{i}"}
            for i in range(len(items))
        ],
    }


def test_plan_enumerates_items_as_attempt_1(tmp_path):
    book_cfg, paths = _book(tmp_path)
    out = plan_generation(book_cfg, paths)
    assert out["needs_verdict"] is True
    assert out["items"] and all(item["attempt"] == 1 for item in out["items"])
    assert out["prompt_fingerprint"]


def test_post_commits_pages_from_the_map_output(tmp_path):
    book_cfg, paths = _book(tmp_path)
    items = plan_generation(book_cfg, paths)["items"]
    pages = post_generation(book_cfg, paths, _map_output(items), None)

    assert any("Generated once" in p.get("content", "") for p in pages)
    written = json.loads((paths.processing / "wiki_pages.json").read_text(encoding="utf-8"))
    assert written  # final walk wrote the real file


def test_probe_collects_no_retry_without_forbidden_hits(tmp_path):
    book_cfg, paths = _book(tmp_path)
    items = plan_generation(book_cfg, paths)["items"]
    out = probe_generation(book_cfg, paths, _map_output(items))
    assert out["needs_retry"] is False
    assert out["items"] == []


def test_probe_collects_attempt_2_on_a_forbidden_hit(tmp_path):
    book_cfg, paths = _book(tmp_path)
    book_cfg = {**book_cfg, "validation": {"forbidden_names": ["armoire"]}}
    items = plan_generation(book_cfg, paths)["items"]
    # The map output content carries a forbidden name → the replay walk
    # re-requests the item, which the probe records as an attempt-2 retry.
    forbidden = {
        "total": len(items), "succeeded": len(items), "failed": 0, "resumed": 0,
        "results": [
            {"index": i, "status": "success", "output": dict(PAGE_PAYLOAD), "run_id": f"r-{i}"}
            for i in range(len(items))
        ],
    }
    out = probe_generation(book_cfg, paths, forbidden)
    assert out["needs_retry"] is True
    assert out["items"] and all(item["attempt"] == 2 for item in out["items"])


def test_no_batches_needs_no_verdict(tmp_path):
    processing = tmp_path / "processing"
    wiki_inputs = tmp_path / "wiki_inputs"
    processing.mkdir()
    wiki_inputs.mkdir()
    (processing / "epub_data.json").write_text(json.dumps({"title": "Empty"}), encoding="utf-8")
    paths = BookPaths(
        epub=tmp_path / "b.epub", processing=processing,
        wiki_inputs=wiki_inputs, output=tmp_path / "output",
    )
    out = plan_generation({"file_path": str(tmp_path / "b.epub")}, paths)
    assert out["needs_verdict"] is False
    # The unfiltered no-batches case wrote the empty artifact.
    assert json.loads((processing / "wiki_pages.json").read_text()) == {"pages": []}
