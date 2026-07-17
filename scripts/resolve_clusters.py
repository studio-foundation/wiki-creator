#!/usr/bin/env python3
"""
Stage: resolve-clusters (script executor, no LLM)

Converts clustered entities from split-clusters output into resolved entities.
Each cluster is already a group of co-referent mentions (produced by fuzzy matching
in the extraction pipeline). This script just maps them to the resolved entity format.

Singles (entity_count == 1) come pre-resolved in singles_resolved and are included as-is.
Multi-clusters: each cluster → one entity. No splitting, no inventing. Pure mapping.

Input: splits.json on disk, written by the split-clusters stage of the
wiki-extraction pipeline. It is a different `studio run`, so its stage output
never reaches this pipeline's context.

Output (stdout):
  { "entities": [...all resolved...], "narrator": null }
"""

import json
import sys
from pathlib import Path

import yaml


from wiki_creator import studio_io
from wiki_creator.entity_taxonomy import resolution_types
from wiki_creator.lang import load_lang_config
from wiki_creator.types import Splits


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
    by_type = splits.get("by_type") or {}
    for entity_type in resolution_types():
        clusters = by_type.get(entity_type, [])
        if not isinstance(clusters, list):
            print(f"Warning: {entity_type} is not a list, skipping", file=sys.stderr)
            continue
        for cluster in clusters:
            entities.append(cluster_to_entity(cluster, noise_words))

    return {"entities": entities, "narrator": None}


def main() -> None:
    payload = studio_io.read_payload()
    paths = studio_io.paths_from_payload(payload)
    splits_path = paths.processing / "splits.json"
    if not splits_path.exists():
        print(
            f"[ERROR] {splits_path} not found. Run wiki-extraction first:\n"
            "  studio run wiki-extraction --input-file <book.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)
    splits = studio_io.to_dict(studio_io.load_artifact(splits_path, Splits))

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
