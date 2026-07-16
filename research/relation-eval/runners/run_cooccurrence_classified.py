#!/usr/bin/env python3
"""Arm: co-occurrence discovery + the per-pair classifier — production, end to end.

The bake-off's `fixed` arm stops at discovery, and that is not what ships. In
production a co-occurrence pair goes on to `relationship-classifier-item`, which
may return no usable type — and STU-501 omits an untyped relation from every
reader-facing surface. So the pipeline already has a precision stage after the
window, and scoring raw co-occurrence against a schema-guided LLM compares half a
pipeline to a whole one: it charges the window for pairs the classifier would have
dropped anyway.

This arm closes that gap. Same discovery as `fixed`, then the real classifier, then
STU-501's own filter. What survives is what a reader would actually have seen.

It is the arm that decides STU-540. If the classifier drops co-occurrence's false
pairs, schema-guided discovery buys precision the pipeline already had, at 1.85x.
If it keeps them, the 0.941-vs-0.733 gap the human adjudication measured is real
and reaches the page.

Usage:
    python runners/run_cooccurrence_classified.py \\
        --book ../../library/christopher_paolini/inheritance/books/01_eragon.yaml
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, _ROOT)

from wiki_creator.paths import book_paths_from_yaml  # noqa: E402
from wiki_creator.registry import Registry  # noqa: E402
from wiki_creator.relationship_types import usable_relationship_type  # noqa: E402
from scripts.classify_relationships import _entity_role_contexts  # noqa: E402
from scripts.relationship_extraction import _run_studio_classifier_item  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--pairs", default="predictions.cooccurrence_fixed.json")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="predictions.cooccurrence_classified.json")
    args = ap.parse_args()

    with open(args.pairs, encoding="utf-8") as f:
        pairs = json.load(f)
    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f)
    summary = book_cfg.get("novel_summary") or ""

    paths = book_paths_from_yaml(args.book)
    with open(paths.processing / "registry.json", encoding="utf-8") as f:
        roles = _entity_role_contexts(Registry.from_dict(json.load(f)))

    done, lock = [0], threading.Lock()

    def run(pair: dict) -> dict | None:
        result = _run_studio_classifier_item(
            pair,
            novel_summary=summary,
            additional_context="",
            role_contexts_a=roles.get(pair["entity_a"], []),
            role_contexts_b=roles.get(pair["entity_b"], []),
        )
        rel_type = usable_relationship_type(result.get("relationship_type"))
        with lock:
            done[0] += 1
            verdict = rel_type or f"DROPPED ({result.get('error', 'no usable type')})"
            print(f"  [{done[0]}/{len(pairs)}] {pair['entity_a']} | {pair['entity_b']}: {verdict}",
                  file=sys.stderr)
        if not rel_type:
            return None
        return {"entity_a": pair["entity_a"], "entity_b": pair["entity_b"],
                "relationship_type": rel_type, "direction": result.get("direction"),
                "chapters": pair.get("chapters", [])}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        classified = [r for r in pool.map(run, pairs) if r]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(classified, f, ensure_ascii=False, indent=2)
    print(f"\n{len(pairs)} pairs -> {len(classified)} survive the classifier "
          f"({len(pairs) - len(classified)} dropped as untyped) -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
