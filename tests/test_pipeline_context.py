"""Guard: a pipeline may only declare context keys the Studio engine populates.

STU-593: three pipeline YAMLs declared ``all_stage_outputs`` under
``context.include`` and four scripts read it, but the engine only ever populates
``input`` + ``previous_stage_output`` (``group_feedback`` inside iteration
groups). A run confirmed it by hand:

    {"event": "stage_context", "stage": "build-character-graph",
     "context_keys": {"input": 1674, "previous_stage_output": 85354}}

So the YAML declared one propagation graph and the engine delivered another, and
nothing errored — ``build-character-graph`` emitted an empty graph in silence for
15 runs (STU-587). The golden harness hides it by feeding *both* keys to every
stage, so any read order looks correct under test.

This test is the missing load-time gate: a ``context.include`` entry outside the
engine-populated set fails here instead of in a JSONL nobody reads.
"""
from __future__ import annotations

from pathlib import Path

import yaml

PIPELINES_DIR = Path(__file__).resolve().parents[1] / ".studio" / "pipelines"

# The context keys the Studio engine actually populates on a stage's payload.
# `group_feedback` is the RALPH validation-loop feedback, populated only inside
# an iteration group. `all_stage_outputs` is deliberately absent — it is the key
# the engine never populates (STU-593).
ENGINE_POPULATED_CONTEXT_KEYS = frozenset({
    "input",
    "previous_stage_output",
    "group_feedback",
})


def _iter_stage_includes(stages: list | None):
    """Yield (stage_name, include_list) over a pipeline's stages, recursing into
    stage groups (e.g. the generation/validation RALPH group)."""
    for stage in stages or []:
        if "stages" in stage:
            yield from _iter_stage_includes(stage["stages"])
        include = (stage.get("context") or {}).get("include")
        if include:
            yield stage.get("name", "<group>"), include


def test_no_pipeline_declares_an_unpopulated_context_key():
    offenders = []
    for path in sorted(PIPELINES_DIR.glob("*.pipeline.yaml")):
        doc = yaml.safe_load(path.read_text())
        for stage_name, include in _iter_stage_includes(doc.get("stages")):
            for key in include:
                if key not in ENGINE_POPULATED_CONTEXT_KEYS:
                    offenders.append(f"{path.name}::{stage_name} declares '{key}'")

    assert not offenders, (
        "context.include declares keys the Studio engine never populates "
        "(STU-593) — the YAML lies about propagation:\n  "
        + "\n  ".join(offenders)
        + f"\nEngine populates only: {sorted(ENGINE_POPULATED_CONTEXT_KEYS)}"
    )
