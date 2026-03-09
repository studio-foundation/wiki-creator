#!/usr/bin/env python3
"""
Stage: merge-entities (script executor, no LLM)

Passes through the output of resolve-clusters.
resolve-clusters already includes all entity types (singles + multi-clusters).

Input (Studio stdin):
  all_stage_outputs: {
    "resolve-clusters": { "entities": [...], "narrator": null },
    ...
  }

Output (stdout):
  { "entities": [...], "narrator": null }
"""

import json
import sys


def merge_entities(all_stage_outputs: dict) -> dict:
    resolve_out = all_stage_outputs.get("resolve-clusters", {})
    if resolve_out:
        entities = resolve_out.get("entities", [])
        narrator = resolve_out.get("narrator", None)
        if not isinstance(entities, list):
            print("Warning: resolve-clusters returned non-list entities", file=sys.stderr)
            entities = []
        return {"entities": entities, "narrator": narrator}

    entities: list[dict] = []
    split_out = all_stage_outputs.get("split-clusters", {})
    singles = split_out.get("singles_resolved", [])
    if isinstance(singles, list):
        entities.extend(singles)

    narrator = None
    for stage_name, stage_output in all_stage_outputs.items():
        if not stage_name.startswith("entity-resolution-"):
            continue
        stage_entities = stage_output.get("entities", [])
        if isinstance(stage_entities, list):
            entities.extend(stage_entities)
        if stage_name == "entity-resolution-PERSON":
            narrator = stage_output.get("narrator", None)

    return {"entities": entities, "narrator": narrator}


def main() -> None:
    payload = json.load(sys.stdin)
    all_stage_outputs = payload.get("previous_outputs", payload.get("all_stage_outputs", {}))

    if not all_stage_outputs:
        print("Warning: all_stage_outputs is empty", file=sys.stderr)

    result = merge_entities(all_stage_outputs)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
