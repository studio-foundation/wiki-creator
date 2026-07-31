"""Per-stage cost report from a Studio run's usage events (STU-758).

Studio 0.15.0 stamps a ``tokens`` field on ``stage_complete`` /
``map_item_complete`` run events (STU-750, `.studio/CLAUDE.md`). A fan-out
stage (``discover-relationships``, ``chapter-summaries``, ``wiki-pages``, ...)
never emits its own ``stage_complete`` -- its cost lives entirely in its
``map_item_complete`` events, keyed by ``map`` instead of ``stage`` -- so both
event types are scanned to get a complete per-stage table.

Pure aggregation over ``.studio/runs/*.jsonl``: no LLM calls, no network.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

# $ per million tokens, at full (uncached) rate. Cache write/read cost the
# input rate scaled by the multipliers below. Edit here as rates change --
# Sonnet 5 intro pricing ($2/$10) ends 2026-08-31 and reverts to $3/$15.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}
CACHE_WRITE_MULTIPLIER = 1.25  # 5-minute TTL premium over the input rate
CACHE_READ_MULTIPLIER = 0.10

_STAGE_KEY_BY_EVENT = {"stage_complete": "stage", "map_item_complete": "map"}
UNKNOWN_MODEL = "unknown"


@dataclass
class ModelUsage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_input_tokens: int = 0
    cache_creation_tokens: int = 0

    def add(self, other: "ModelUsage") -> None:
        self.calls += other.calls
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.cached_input_tokens += other.cached_input_tokens
        self.cache_creation_tokens += other.cache_creation_tokens

    @property
    def total_tokens(self) -> int:
        return (
            self.prompt_tokens + self.completion_tokens
            + self.cached_input_tokens + self.cache_creation_tokens
        )

    @property
    def cache_hit_pct(self) -> float:
        denom = self.cached_input_tokens + self.prompt_tokens
        return 100.0 * self.cached_input_tokens / denom if denom else 0.0


def cost_usd(model: str, usage: ModelUsage) -> float | None:
    """API-equivalent cost, or None when the model has no pricing entry."""
    rates = MODEL_PRICING.get(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    return (
        usage.prompt_tokens / 1_000_000 * input_rate
        + usage.completion_tokens / 1_000_000 * output_rate
        + usage.cache_creation_tokens / 1_000_000 * input_rate * CACHE_WRITE_MULTIPLIER
        + usage.cached_input_tokens / 1_000_000 * input_rate * CACHE_READ_MULTIPLIER
    )


def _one(counts: dict) -> ModelUsage:
    if "total" in counts and "total_tokens" not in counts:  # pre-STU-750 shape
        return ModelUsage(
            calls=1,
            prompt_tokens=counts.get("prompt", 0),
            completion_tokens=counts.get("completion", 0),
        )
    return ModelUsage(
        calls=1,
        prompt_tokens=counts.get("prompt_tokens", 0),
        completion_tokens=counts.get("completion_tokens", 0),
        cached_input_tokens=counts.get("cached_input_tokens", 0),
        cache_creation_tokens=counts.get("cache_creation_tokens", 0),
    )


def _by_model(tokens: dict) -> dict[str, ModelUsage]:
    by_model = tokens.get("by_model")
    if by_model:
        return {model: _one(counts) for model, counts in by_model.items()}
    return {UNKNOWN_MODEL: _one(tokens)}


def aggregate_events(events: Iterable[dict]) -> dict[tuple[str, str], ModelUsage]:
    """(stage_name, model) -> summed usage, over stage_complete + map_item_complete."""
    totals: dict[tuple[str, str], ModelUsage] = defaultdict(ModelUsage)
    for event in events:
        stage_key = _STAGE_KEY_BY_EVENT.get(event.get("event", ""))
        if stage_key is None:
            continue
        tokens = event.get("tokens")
        if not tokens:
            continue
        stage_name = event[stage_key]
        for model, usage in _by_model(tokens).items():
            totals[(stage_name, model)].add(usage)
    return totals


def _run_id_from_filename(path: Path) -> str:
    return path.stem.rsplit("-", 1)[-1]


def find_run_files(run_ids: Sequence[str], runs_dir: Path) -> list[Path]:
    """Every run JSONL whose filename run-id starts with one of run_ids.

    Accepts a full or short (prefix) id per Studio's own file-lookup convention
    (`replay.ts`/`status.ts`) and, unlike `replay`, collects every match instead
    of erroring on ambiguity -- so a failed run plus its completing resume
    (different run ids, same book) merge into one report.
    """
    if not runs_dir.is_dir():
        return []
    matched: list[Path] = []
    for run_id in run_ids:
        needle = run_id.replace("-", "")
        for f in sorted(runs_dir.glob("*.jsonl")):
            if f not in matched and _run_id_from_filename(f).startswith(needle):
                matched.append(f)
    return matched


def read_events(paths: Iterable[Path]) -> Iterator[dict]:
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)


def format_table(totals: dict[tuple[str, str], ModelUsage]) -> str:
    if not totals:
        return "no usage events found"

    costs = {key: cost_usd(key[1], usage) for key, usage in totals.items()}
    grand_tokens = sum(usage.total_tokens for usage in totals.values())
    grand_cost = sum(c for c in costs.values() if c is not None)

    header = (
        f"{'STAGE':<28} {'MODEL':<20} {'CALLS':>5} {'INPUT':>10} {'OUTPUT':>10} "
        f"{'CACHE_W':>9} {'CACHE_R':>9} {'HIT%':>6} {'COST':>10} {'%TOTAL':>7}"
    )
    lines = [header, "-" * len(header)]
    for key in sorted(totals, key=lambda k: (-totals[k].total_tokens, k)):
        stage, model = key
        usage = totals[key]
        cost = costs[key]
        cost_str = f"${cost:.4f}" if cost is not None else "n/a"
        pct = 100.0 * usage.total_tokens / grand_tokens if grand_tokens else 0.0
        lines.append(
            f"{stage:<28} {model:<20} {usage.calls:>5} {usage.prompt_tokens:>10} "
            f"{usage.completion_tokens:>10} {usage.cache_creation_tokens:>9} "
            f"{usage.cached_input_tokens:>9} {usage.cache_hit_pct:>5.1f}% "
            f"{cost_str:>10} {pct:>6.1f}%"
        )
    lines.append("-" * len(header))
    lines.append(f"{'TOTAL':<28} {'cost $' + format(grand_cost, '.4f'):>{len(header) - 28}}")
    return "\n".join(lines)


def build_report(run_ids: Sequence[str], project_root: Path) -> str:
    runs_dir = project_root / ".studio" / "runs"
    paths = find_run_files(run_ids, runs_dir)
    if not paths:
        return f"no run files found for {', '.join(run_ids)} under {runs_dir}"
    totals = aggregate_events(read_events(paths))
    return format_table(totals)
