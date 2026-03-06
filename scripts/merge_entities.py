#!/usr/bin/env python3
"""
Stage: merge-entities (script executor, no LLM)

Concatenates resolved entities from:
- split-clusters singles_resolved (pre-resolved, no LLM)
- entity-resolution-PERSON / PLACE / ORG / EVENT / OTHER (parallel LLM outputs)

Narrator: taken from entity-resolution-PERSON (only one that can detect a narrator).

Input (Studio stdin):
  all_stage_outputs: {
    "split-clusters": { "singles_resolved": [...] },
    "entity-resolution-PERSON": { "entities": [...], "narrator": {...}|null },
    "entity-resolution-PLACE":  { "entities": [...], "narrator": null },
    ...
  }

Output (stdout):
  { "entities": [...all concatenated], "narrator": {...}|null }
"""

import json
import sys

RESOLVER_STAGES = (
    "entity-resolution-PERSON",
    "entity-resolution-PLACE",
    "entity-resolution-ORG",
    "entity-resolution-EVENT",
    "entity-resolution-OTHER",
)


def merge_entities(all_stage_outputs: dict) -> dict:
    entities: list[dict] = []
    narrator = None

    # Singles pre-resolved by split-clusters
    split_out = all_stage_outputs.get("split-clusters", {})
    entities.extend(split_out.get("singles_resolved", []))

    # LLM-resolved multi-clusters
    for stage_name in RESOLVER_STAGES:
        stage_out = all_stage_outputs.get(stage_name)
        if not stage_out:
            continue
        entities.extend(stage_out.get("entities", []))
        if narrator is None and stage_out.get("narrator"):
            narrator = stage_out["narrator"]

    return {"entities": entities, "narrator": narrator}


def main() -> None:
    payload = json.load(sys.stdin)
    all_stage_outputs = payload.get("all_stage_outputs", {})

    if not all_stage_outputs:
        print("Warning: all_stage_outputs is empty", file=sys.stderr)

    result = merge_entities(all_stage_outputs)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
