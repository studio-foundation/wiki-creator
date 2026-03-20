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
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.lang import load_lang_config

ENTITY_TYPES = ("PERSON", "PLACE", "ORG", "EVENT", "OTHER")


def _default_noise_words() -> frozenset[str]:
    en = frozenset(load_lang_config("en").get("noise_words", []))
    fr = frozenset(load_lang_config("fr").get("noise_words", []))
    return en | fr


_NOISE_WORDS = _default_noise_words()


def is_relevant(name: str, noise_words: frozenset[str] = _NOISE_WORDS) -> bool:
    """Heuristic: is this a real proper noun worth keeping?"""
    if not name:
        return False
    cleaned = name.strip()
    if len(cleaned) < 2:
        return False
    if cleaned.lower() in noise_words:
        return False
    # Proper nouns start with uppercase
    if cleaned[0].islower():
        return False
    return True


def cluster_to_entity(cluster: dict, noise_words: frozenset[str] = _NOISE_WORDS) -> dict:
    """Map a cluster directly to a resolved entity. No invention."""
    return {
        "canonical_name": cluster.get("canonical_candidate", ""),
        "type": cluster.get("type", "OTHER"),
        "aliases": cluster.get("all_mentions", []),
        "source_ids": cluster.get("entity_ids", []),
        "relevant": is_relevant(cluster.get("canonical_candidate", ""), noise_words),
    }


def resolve(splits: dict, noise_words: frozenset[str] = _NOISE_WORDS) -> dict:
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
            entities.append(cluster_to_entity(cluster, noise_words))

    return {"entities": entities, "narrator": None}


def main() -> None:
    payload = json.load(sys.stdin)
    previous_outputs = payload.get("previous_outputs", {})
    splits = previous_outputs.get("split-clusters", {})

    if not splits:
        print("Warning: split-clusters output not found in previous_outputs", file=sys.stderr)

    noise_words = _NOISE_WORDS
    raw_context = payload.get("additional_context", "")
    if raw_context:
        try:
            ctx = yaml.safe_load(raw_context) or {}
            language = (
                ctx.get("export", {}).get("categories", {}).get("language")
                or ctx.get("language")
                or "en"
            )
            lang_noise = frozenset(load_lang_config(language).get("noise_words", []))
            if lang_noise:
                noise_words = lang_noise
        except Exception:
            pass

    result = resolve(splits, noise_words=noise_words)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
