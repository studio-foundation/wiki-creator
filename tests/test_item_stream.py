"""Live map-item stream rendering for the `wiki` front door (STU-626)."""
from __future__ import annotations

import sys

from wiki_creator import item_stream
from wiki_creator.item_stream import MAP_ITEM_STREAM_TAG, parse_item_line, render_map_item


def _line(payload: dict) -> str:
    import json

    return f"{MAP_ITEM_STREAM_TAG} {json.dumps(payload)}"


def test_parse_item_line_reads_tagged_payload():
    assert parse_item_line(_line({"map": "discover", "index": 0})) == {"map": "discover", "index": 0}


def test_parse_item_line_ignores_untagged_and_malformed():
    assert parse_item_line("[discover-relationships] 45 chunks | 0 failed") is None
    assert parse_item_line(f"{MAP_ITEM_STREAM_TAG} not json") is None


def test_render_discover_lists_each_pair(capsys):
    render_map_item(
        {
            "map": "discover",
            "label": "Chapter 4",
            "status": "success",
            "output": {"relations": [{"entity_a": "Alice", "entity_b": "Dodo", "relationship_type": "allies"}]},
        },
        out=sys.stderr,
    )
    err = capsys.readouterr().err
    assert "Chapter 4" in err
    assert "Alice <=> Dodo — allies" in err


def test_render_discover_skips_non_dict_relations(capsys):
    # An off-schema child can ship a bare string in `relations`; the cosmetic
    # stream must not crash the run over it.
    render_map_item(
        {
            "map": "discover",
            "label": "Chapter 4",
            "status": "success",
            "output": {"relations": ["Alice and the Dodo are allies", {"entity_a": "Alice", "entity_b": "Dodo"}]},
        },
        out=sys.stderr,
    )
    err = capsys.readouterr().err
    assert "Alice <=> Dodo" in err


def test_render_classify_names_the_pair_from_its_label(capsys):
    render_map_item(
        {
            "map": "classify",
            "label": "Alice <=> Hatter",
            "status": "success",
            "output": {"relationship_type": "enemy", "confidence": "explicit"},
        },
        out=sys.stderr,
    )
    assert "Alice <=> Hatter — enemy (explicit)" in capsys.readouterr().err


def test_render_failed_item_is_marked(capsys):
    render_map_item({"map": "generate", "label": "Lucy", "status": "failed"}, out=sys.stderr)
    assert "Lucy — FAILED" in capsys.readouterr().err


def test_render_cached_item_uses_the_resume_tick(capsys):
    render_map_item({"map": "summarize", "label": "Ch 1", "status": "success", "cached": True, "output": {"summary_bullets": [1, 2]}}, out=sys.stderr)
    out = capsys.readouterr().err
    assert out.startswith("•")
    assert "Ch 1 — 2 bullets" in out


def test_run_studio_with_stream_renders_tagged_passes_through_rest(capsys):
    # A stand-in `studio`: emits one tagged item + one ordinary log line to stderr.
    script = (
        "import sys;"
        f"sys.stderr.write('{MAP_ITEM_STREAM_TAG} ' + '{{\"map\":\"discover\",\"label\":\"Ch 1\",\"status\":\"success\",\"output\":{{\"relations\":[{{\"entity_a\":\"A\",\"entity_b\":\"B\",\"relationship_type\":\"allies\"}}]}}}}' + '\\n');"
        "sys.stderr.write('[discover] 1 chunk\\n')"
    )
    rc = item_stream.run_studio_with_stream([sys.executable, "-c", script])
    err = capsys.readouterr().err
    assert rc == 0
    assert "A <=> B — allies" in err          # tagged → rendered
    assert "[discover] 1 chunk" in err          # untagged → passed through
    assert MAP_ITEM_STREAM_TAG not in err       # raw tag never leaks
