#!/usr/bin/env python3
"""Standalone relationship classifier: calls studio run relationship-classifier-item per pair.

Usage:
    python scripts/classify_relationships.py --book library/.../book.yaml
    python scripts/classify_relationships.py --book library/.../book.yaml --dry-run

Input:  processing_output/<slug>/relationships.json
Output: processing_output/<slug>/relationships_classified.json

Saves incrementally after each pair. Resumes if output file already exists.
Studio handles LLM calls, ralph retries, and validation.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml


from wiki_creator import studio_io
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry
from wiki_creator.relationship_fold import fold_relationships
from wiki_creator.types import Relationship, RelationshipBundle
from scripts.relationship_extraction import (
    _run_studio_classifier_item,
    _should_classify_pair,
)


# Fields the LLM classifier is allowed to contribute to a relationship dict
# (relationship-classifier-item.contract.yaml required_fields ∩ Relationship).
# Everything else the freeform LLM JSON might carry (reasoning, notes,
# evidence_kind, …) is dropped so {**pair, **classification} can only produce a
# valid Relationship.
_KNOWN_CLASSIFICATION_KEYS = frozenset(
    {"relationship_type", "direction", "evolution", "key_moments", "evidence"}
)

# STU-496: how many per-entity role/status excerpts to surface to the classifier.
_MAX_ROLE_CONTEXTS = 6


def _entity_role_contexts(
    registry: Registry, max_per_entity: int = _MAX_ROLE_CONTEXTS
) -> dict[str, list[str]]:
    """Per-entity context sentences that establish role/status/faction (STU-496).

    Structural pairs (rival Champions, institutional employer, mediated killer)
    never share a dyadic scene, so the classifier needs each entity's own
    role-establishing excerpts. The first mention usually introduces the
    character with their title/role, so the earliest context is always kept;
    the rest are sampled evenly across the entity's mentions.
    """
    out: dict[str, list[str]] = {}
    for rec in registry.entities:
        seen: set[str] = set()
        contexts: list[str] = []
        for mention in rec.mentions:
            sentence = (mention.context or "").strip()
            if sentence and sentence not in seen:
                seen.add(sentence)
                contexts.append(sentence)
        if len(contexts) <= max_per_entity:
            out[rec.canonical_name] = contexts
        else:
            step = len(contexts) / max_per_entity
            out[rec.canonical_name] = [contexts[int(i * step)] for i in range(max_per_entity)]
    return out


def _load_done_keys(output_path: Path) -> tuple[set[tuple[str, str]], list[dict]]:
    """Load already-classified pairs from output file. Returns (done_keys, pairs).

    Malformed pairs (missing entity_a/entity_b) are skipped individually — they do NOT
    cause a full reset of resume state.
    """
    if not output_path.exists():
        return set(), []
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        pairs = data.get("relationships", [])
        keys = {
            (p["entity_a"], p["entity_b"])
            for p in pairs
            if "entity_a" in p and "entity_b" in p
        }
        return keys, pairs
    except json.JSONDecodeError:
        return set(), []


def _save(output_path: Path, base: dict, classified: list[dict]) -> None:
    bundle = RelationshipBundle(
        entities=base.get("entities", []),
        relationships=[Relationship(**r) for r in classified],
        stats=base.get("stats", {}),
        narrator=base.get("narrator"),
    )
    studio_io.save_artifact(output_path, bundle, RelationshipBundle)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify relationships via Studio (relationship-classifier-item pipeline)."
    )
    parser.add_argument(
        "--book", required=True,
        help="Path to book YAML, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Studio calls, pass pairs through unchanged",
    )
    args = parser.parse_args()

    book_paths = book_paths_from_yaml(args.book)
    input_path = book_paths.processing / "relationships.json"
    output_path = book_paths.processing / "relationships_classified.json"

    if not input_path.exists():
        print(f"[ERROR] Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # dict-only boundary: the incremental per-pair classify/resume loop below
    # merges LLM classification dicts into relationship dicts (_load_done_keys/
    # _save stay dict-based for interrupted-run tolerance) — validated on load
    # here, converted back to plain dicts for that loop.
    bundle = studio_io.load_artifact(input_path, RelationshipBundle)
    data = studio_io.to_dict(bundle)
    relationships = data.get("relationships", [])
    entity_types = {e["canonical_name"]: e.get("type", "") for e in data.get("entities", [])}
    base = {k: v for k, v in data.items() if k != "relationships"}

    # STU-435: fold the co-occurrence graph onto canonical entities before
    # classifying. The graph is built at mention level (surface forms, pre
    # alias-resolution) so a single entity's edges are split across its aliases
    # (e.g. "Chaol Westfall" vs "Captain Westfall"). registry.alias_table()
    # collapses them so each canonical pair is classified exactly once, on the
    # summed cooccurrence signal instead of two weak fragments.
    registry_path = book_paths.processing / "registry.json"
    role_contexts: dict[str, list[str]] = {}
    if registry_path.exists():
        registry = Registry.load(registry_path)
        before = len(relationships)
        relationships = fold_relationships(relationships, registry)
        # Registry types are refined (post entity-classification) — prefer them.
        entity_types = {rec.canonical_name: rec.entity_type for rec in registry.entities}
        role_contexts = _entity_role_contexts(registry)
        print(
            f"[classify-relationships] Folded {before} surface edges into "
            f"{len(relationships)} canonical pairs via registry.alias_table()",
            file=sys.stderr,
        )
    else:
        print(
            f"[classify-relationships] registry.json not found ({registry_path}) — "
            "classifying unfolded surface edges, no role contexts (STU-496)",
            file=sys.stderr,
        )

    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}
    novel_summary = book_cfg.get("novel_summary") or ""

    done_keys, classified = _load_done_keys(output_path)
    if done_keys:
        print(
            f"[classify-relationships] Resuming — {len(done_keys)} pairs already done",
            file=sys.stderr,
        )

    to_classify = [r for r in relationships if (r.get("entity_a"), r.get("entity_b")) not in done_keys]
    skip_count = len(relationships) - len(to_classify)
    classifiable = sum(1 for r in to_classify if _should_classify_pair(r, entity_types))

    print(
        f"[classify-relationships] {len(relationships)} pairs total | "
        f"{skip_count} skipped (already done) | "
        f"{classifiable} to classify",
        file=sys.stderr,
    )

    try:
        for i, pair in enumerate(to_classify, 1):
            label = f"{pair.get('entity_a', '?')}↔{pair.get('entity_b', '?')}"
            if not _should_classify_pair(pair, entity_types):
                print(f"  [SKIP] {label} (non-interpersonal type)", file=sys.stderr)
                classified.append(pair)
            elif args.dry_run:
                print(f"  [DRY]  {label}", file=sys.stderr)
                classified.append(pair)
            else:
                print(f"  [CLF]  {label} ({i}/{len(to_classify)})", file=sys.stderr, end="", flush=True)
                classification = _run_studio_classifier_item(
                    pair,
                    novel_summary=novel_summary,
                    additional_context="",
                    role_contexts_a=role_contexts.get(pair.get("entity_a", ""), []),
                    role_contexts_b=role_contexts.get(pair.get("entity_b", ""), []),
                )
                if classification and not classification.get("error"):
                    classification = {
                        k: v for k, v in classification.items()
                        if k in _KNOWN_CLASSIFICATION_KEYS and v is not None
                    }
                    result = {**pair, **classification}
                else:
                    print(
                        f"\n  [WARN] Studio failed for {label}: "
                        f"{classification.get('error', 'unknown') if classification else 'no response'}",
                        file=sys.stderr,
                    )
                    result = pair
                classified.append(result)
                status = result.get("relationship_type") or "null"
                print(f" → {status}", file=sys.stderr)
            _save(output_path, base, classified)
    except KeyboardInterrupt:
        print(
            f"\n[classify-relationships] Interrupted — {len(classified)} pairs saved",
            file=sys.stderr,
        )

    succeeded = sum(1 for r in classified if r.get("relationship_type") is not None)
    print(
        f"\n[classify-relationships] Done — {len(classified)} total, {succeeded} classified",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
