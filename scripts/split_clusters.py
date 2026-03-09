#!/usr/bin/env python3
"""
Stage: split-clusters (script executor, no LLM)

Partitions entity-clustering output into:
- singles_resolved: entity_count==1, pre-resolved (no LLM needed)
- PERSON/PLACE/ORG/EVENT/OTHER: multi-clusters for parallel LLM resolution

Input (Studio stdin):
  previous_outputs["entity-clustering"]["clusters"]

Output (stdout):
  {
    "singles_resolved": [{canonical_name, type, aliases, source_ids, relevant}],
    "PERSON": [...multi-clusters],
    "PLACE":  [...multi-clusters],
    "ORG":    [...multi-clusters],
    "EVENT":  [...multi-clusters],
    "OTHER":  [...multi-clusters],
    "stats":  {singles, multi_PERSON, multi_PLACE, ...}
  }
"""

import json
import os
import sys
from pathlib import Path
import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_epub, BookPaths


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)

ENTITY_TYPES = ("PERSON", "PLACE", "ORG", "EVENT", "OTHER")


def split_clusters(clusters: list[dict]) -> dict:
    singles_resolved = []
    multi_by_type: dict[str, list] = {t: [] for t in ENTITY_TYPES}

    for cluster in clusters:
        entity_type = cluster.get("type", "OTHER")
        if entity_type not in multi_by_type:
            entity_type = "OTHER"

        if cluster.get("entity_count", 1) == 1:
            singles_resolved.append({
                "canonical_name": cluster.get("canonical_candidate", ""),
                "type": entity_type,
                "aliases": cluster.get("all_mentions", [cluster.get("canonical_candidate", "")]),
                "source_ids": cluster.get("entity_ids", []),
                "relevant": True,
            })
        else:
            multi_by_type[entity_type].append(cluster)

    stats = {"singles": len(singles_resolved)}
    for t in ENTITY_TYPES:
        stats[f"multi_{t}"] = len(multi_by_type[t])

    return {"singles_resolved": singles_resolved, **multi_by_type, "stats": stats}


def main() -> None:
    payload = json.load(sys.stdin)
    prev = payload.get("previous_outputs", {})
    # verify-entity-types (if present) sits between entity-clustering and split-clusters
    # and emits the same clusters shape — prefer it as the source of truth.
    clusters = (
        prev.get("verify-entity-types", {}).get("clusters")
        or prev.get("entity-clustering", {}).get("clusters", [])
    )

    if not clusters:
        print("Warning: no clusters in entity-clustering output", file=sys.stderr)

    result = split_clusters(clusters)
    empty_names = [s for s in result["singles_resolved"] if not s["canonical_name"]]
    if empty_names:
        print(f"Warning: {len(empty_names)} singles have empty canonical_name", file=sys.stderr)

    # Pass through pov_detection from epub-parse so entity-resolution-PERSON
    # can detect narrator without needing a named stage reference (which doesn't
    # work inside group stages in Studio).
    pov_detection = prev.get("epub-parse", {}).get("pov_detection")
    if pov_detection is not None:
        result["pov_detection"] = pov_detection

    paths = _paths_from_payload(payload)
    paths.processing.mkdir(parents=True, exist_ok=True)
    with open(paths.processing / "splits.json", "w", encoding="utf-8") as _f:
        json.dump(result, _f, ensure_ascii=False)

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
