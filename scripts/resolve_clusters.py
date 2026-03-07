#!/usr/bin/env python3
"""
Stage: resolve-clusters (script executor, no LLM)

Converts clustered entities from split-clusters output into resolved entities.
Each cluster is already a group of co-referent mentions (produced by fuzzy matching
in the extraction pipeline). This script just maps them to the resolved entity format.

Singles (entity_count == 1) come pre-resolved in singles_resolved and are included as-is.
Multi-clusters: each cluster → one entity. No splitting, no inventing. Pure mapping.

Input (Studio stdin):
  {
    "previous_outputs": {
      "split-clusters": {
        "singles_resolved": [...],
        "PERSON": [...clusters...],
        "PLACE": [...clusters...],
        "ORG": [...clusters...],
        "EVENT": [...clusters...],
        "OTHER": [...clusters...],
        "stats": {...}
      }
    }
  }

Output (stdout):
  { "entities": [...all resolved...], "narrator": null }
"""

import json
import sys

ENTITY_TYPES = ("PERSON", "PLACE", "ORG", "EVENT", "OTHER")

# Common non-proper-noun words that should be marked irrelevant
_NOISE_WORDS = frozenset({
    "oui", "non", "ah", "oh", "eh", "ok", "yes", "no",
    "the", "le", "la", "les", "un", "une", "des",
    "et", "ou", "mais", "donc", "or", "ni", "car",
    "here", "there", "ici", "là", "que", "qui", "quoi",
    "ça", "ce", "cet", "cette", "ces",
    "it", "he", "she", "they", "we",
})


def is_relevant(name: str) -> bool:
    """Heuristic: is this a real proper noun worth keeping?"""
    if not name:
        return False
    cleaned = name.strip()
    if len(cleaned) < 2:
        return False
    if cleaned.lower() in _NOISE_WORDS:
        return False
    # Proper nouns start with uppercase
    if cleaned[0].islower():
        return False
    return True


def cluster_to_entity(cluster: dict) -> dict:
    """Map a cluster directly to a resolved entity. No invention."""
    return {
        "canonical_name": cluster.get("canonical_candidate", ""),
        "type": cluster.get("type", "OTHER"),
        "aliases": cluster.get("all_mentions", []),
        "source_ids": cluster.get("entity_ids", []),
        "relevant": is_relevant(cluster.get("canonical_candidate", "")),
    }


def resolve(splits: dict) -> dict:
    entities: list[dict] = []

    # Singles: already in resolved format, include as-is
    entities.extend(splits.get("singles_resolved", []))

    # Multi-clusters: one cluster = one entity, no LLM needed
    for entity_type in ENTITY_TYPES:
        clusters = splits.get(entity_type, [])
        if not isinstance(clusters, list):
            print(f"Warning: {entity_type} is not a list, skipping", file=sys.stderr)
            continue
        for cluster in clusters:
            entities.append(cluster_to_entity(cluster))

    return {"entities": entities, "narrator": None}


def main() -> None:
    payload = json.load(sys.stdin)
    previous_outputs = payload.get("previous_outputs", {})
    splits = previous_outputs.get("split-clusters", {})

    if not splits:
        print("Warning: split-clusters output not found in previous_outputs", file=sys.stderr)

    result = resolve(splits)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
