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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry
from wiki_creator.relationship_fold import fold_relationships
from scripts.relationship_extraction import (
    _run_studio_classifier_item,
    _should_classify_pair,
)


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
    out = {**base, "relationships": classified}
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


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

    data = json.loads(input_path.read_text(encoding="utf-8"))
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
    if registry_path.exists():
        registry = Registry.load(registry_path)
        before = len(relationships)
        relationships = fold_relationships(relationships, registry)
        # Registry types are refined (post entity-classification) — prefer them.
        entity_types = {rec.canonical_name: rec.entity_type for rec in registry.entities}
        print(
            f"[classify-relationships] Folded {before} surface edges into "
            f"{len(relationships)} canonical pairs via registry.alias_table()",
            file=sys.stderr,
        )
    else:
        print(
            f"[classify-relationships] registry.json not found ({registry_path}) — "
            "classifying unfolded surface edges",
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
                )
                if classification and not classification.get("error"):
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
