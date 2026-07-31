"""wiki cost <run-id> -- per-stage cost aggregation over run JSONL (STU-758)."""
from __future__ import annotations

from pathlib import Path

from wiki_creator import cost

FIXTURES = Path(__file__).parent / "fixtures" / "stu758"


def test_aggregate_events_splits_by_stage_and_model():
    events = [
        {
            "event": "stage_complete", "stage": "chapter-summary",
            "tokens": {
                "prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200,
                "by_model": {"claude-haiku-4-5": {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}},
            },
        },
        {
            "event": "map_item_complete", "map": "wiki-pages", "status": "success",
            "tokens": {
                "prompt_tokens": 2000, "completion_tokens": 500, "total_tokens": 2500,
                "by_model": {"claude-sonnet-5": {"prompt_tokens": 2000, "completion_tokens": 500, "total_tokens": 2500}},
            },
        },
    ]
    totals = cost.aggregate_events(events)
    assert set(totals) == {("chapter-summary", "claude-haiku-4-5"), ("wiki-pages", "claude-sonnet-5")}
    assert totals[("chapter-summary", "claude-haiku-4-5")].prompt_tokens == 1000
    assert totals[("wiki-pages", "claude-sonnet-5")].completion_tokens == 500


def test_events_without_tokens_field_are_skipped():
    events = [{"event": "map_item_complete", "map": "wiki-pages", "status": "failed"}]
    assert cost.aggregate_events(events) == {}


def test_events_of_other_types_are_ignored():
    events = [{"event": "stage_start", "stage": "chapter-summary"}]
    assert cost.aggregate_events(events) == {}


def test_legacy_shape_normalizes_to_unknown_model():
    events = [{"event": "stage_complete", "stage": "chapter-summary", "tokens": {"prompt": 500, "completion": 100, "total": 600}}]
    totals = cost.aggregate_events(events)
    usage = totals[("chapter-summary", cost.UNKNOWN_MODEL)]
    assert usage.prompt_tokens == 500 and usage.completion_tokens == 100


def test_cache_hit_pct():
    usage = cost.ModelUsage(prompt_tokens=100, cached_input_tokens=900)
    assert usage.cache_hit_pct == 90.0


def test_cache_hit_pct_no_input_is_zero():
    assert cost.ModelUsage().cache_hit_pct == 0.0


def test_cost_usd_known_model():
    usage = cost.ModelUsage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost.cost_usd("claude-haiku-4-5", usage) == 1.00 + 5.00


def test_cost_usd_applies_cache_multipliers():
    usage = cost.ModelUsage(cache_creation_tokens=1_000_000, cached_input_tokens=1_000_000)
    got = cost.cost_usd("claude-haiku-4-5", usage)
    assert got == 1.00 * cost.CACHE_WRITE_MULTIPLIER + 1.00 * cost.CACHE_READ_MULTIPLIER


def test_cost_usd_unpriced_model_is_none():
    assert cost.cost_usd("mistral:7b-instruct", cost.ModelUsage(prompt_tokens=100)) is None


def test_find_run_files_matches_short_id_prefix():
    files = cost.find_run_files(["bc15740a"], FIXTURES)
    assert [f.name for f in files] == ["2026-07-30T10h00m-wiki-full-bc15740a.jsonl"]


def test_find_run_files_merges_multiple_ids_in_order():
    files = cost.find_run_files(["bc15740a", "b348bad8"], FIXTURES)
    assert [f.name for f in files] == [
        "2026-07-30T10h00m-wiki-full-bc15740a.jsonl",
        "2026-07-30T10h05m-wiki-full-b348bad8.jsonl",
    ]


def test_find_run_files_unknown_id_returns_nothing():
    assert cost.find_run_files(["deadbeef"], FIXTURES) == []


def test_build_report_reads_from_project_root_studio_runs(tmp_path):
    # bc15740a + b348bad8: the issue's own example -- a failed run plus the
    # resume that completed it is one logical run, so their usage sums.
    runs_dir = tmp_path / ".studio" / "runs"
    runs_dir.mkdir(parents=True)
    for f in FIXTURES.iterdir():
        (runs_dir / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

    report = cost.build_report(["bc15740a", "b348bad8"], tmp_path)
    assert "chapter-summary" in report
    assert "wiki-pages" in report


def test_build_report_no_matching_run_files(tmp_path):
    report = cost.build_report(["nope"], tmp_path)
    assert "no run files found" in report


def test_aggregate_over_both_fixture_files_sums_across_the_resume():
    files = cost.find_run_files(["bc15740a", "b348bad8"], FIXTURES)
    totals = cost.aggregate_events(cost.read_events(files))

    haiku = totals[("chapter-summary", "claude-haiku-4-5")]
    assert haiku.prompt_tokens == 1000 and haiku.completion_tokens == 200

    legacy = totals[("chapter-summary", cost.UNKNOWN_MODEL)]
    assert legacy.prompt_tokens == 500 and legacy.completion_tokens == 100

    sonnet = totals[("wiki-pages", "claude-sonnet-5")]
    assert sonnet.prompt_tokens == 2000 and sonnet.completion_tokens == 500

    # The failed map_item (no tokens) contributes no row.
    assert len(totals) == 3


def test_format_table_reports_cost_and_flags_unpriced_rows():
    files = cost.find_run_files(["bc15740a", "b348bad8"], FIXTURES)
    table = cost.format_table(cost.aggregate_events(cost.read_events(files)))
    assert "chapter-summary" in table
    assert "wiki-pages" in table
    assert "claude-haiku-4-5" in table
    assert "claude-sonnet-5" in table
    assert "n/a" in table  # the legacy/unknown-model row has no pricing entry


def test_format_table_empty_totals():
    assert cost.format_table({}) == "no usage events found"
