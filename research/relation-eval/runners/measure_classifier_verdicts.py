#!/usr/bin/env python3
"""Instrument what `relationship-classifier-item` actually returns (STU-554, piste 1).

The pipeline knows only that a pair ends up without a usable type: `usable_relationship_type`
folds four very different outcomes into one `None` — a real JSON `null` (the model declines),
the literal strings `"null"`/`"none"` (a contract/prompt defect), an empty string, and a Studio
failure that never reached the model at all. Which one dominates decides the fix, so it is
measured before any hypothesis.

Pairs come from the cached `relationships.json` (discovery output), filtered exactly as the
production stage filters them, so the rejection rate here is the pipeline's own.

Usage:
    python runners/measure_classifier_verdicts.py \\
        --book library/christopher_paolini/inheritance/books/01_eragon.yaml \\
        --out /tmp/verdicts.eragon.json
"""
import argparse
import collections
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
sys.path.insert(0, _ROOT)

from wiki_creator.paths import book_paths_from_yaml  # noqa: E402
from wiki_creator.registry import Registry  # noqa: E402
from scripts.classify_relationships import _entity_role_contexts  # noqa: E402
from scripts.relationship_extraction import (  # noqa: E402
    _run_studio_classifier_item,
    _should_classify_pair,
)


def bucket(result: dict) -> str:
    """Which of the outcomes `usable_relationship_type` flattens into one None."""
    if result.get("error"):
        return f"error:{result['error']}"
    raw = result.get("relationship_type")
    if raw is None:
        return "declined_null"
    text = str(raw).strip()
    if not text:
        return "empty_string"
    if text.lower() in ("null", "none"):
        return "sentinel_string"
    return "typed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0, help="classify only the first N pairs")
    ap.add_argument("--role-contexts", action="store_true",
                    help="pass STU-496 role contexts (the classify_relationships path)")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f)
    paths = book_paths_from_yaml(args.book)

    with open(paths.processing / "relationships.json", encoding="utf-8") as f:
        pairs = json.load(f)["relationships"]
    with open(paths.processing / "entities_classified.json", encoding="utf-8") as f:
        entities = json.load(f)["entities"]
    entity_types = {
        name: e["type"]
        for e in entities
        for name in [e["canonical_name"], *e.get("aliases", [])]
    }
    pairs = [p for p in pairs if _should_classify_pair(p, entity_types)]
    if args.limit:
        pairs = pairs[: args.limit]

    roles: dict[str, list[str]] = {}
    if args.role_contexts:
        with open(paths.processing / "registry.json", encoding="utf-8") as f:
            roles = _entity_role_contexts(Registry.from_dict(json.load(f)))

    done, lock = [0], threading.Lock()

    def run(pair: dict) -> dict:
        result = _run_studio_classifier_item(
            pair,
            novel_summary=book_cfg.get("novel_summary") or "",
            additional_context="",
            role_contexts_a=roles.get(pair["entity_a"], []),
            role_contexts_b=roles.get(pair["entity_b"], []),
            book_config=book_cfg,
        )
        verdict = {
            "entity_a": pair["entity_a"],
            "entity_b": pair["entity_b"],
            "cooccurrence_count": pair.get("cooccurrence_count", 0),
            "sample_contexts_count": len(pair.get("sample_contexts", [])),
            "bucket": bucket(result),
            "relationship_type_raw": result.get("relationship_type"),
            "confidence": result.get("confidence"),
            "evidence": result.get("evidence"),
            "evidence_kind": result.get("evidence_kind"),
        }
        with lock:
            done[0] += 1
            print(f"  [{done[0]}/{len(pairs)}] {pair['entity_a']} | {pair['entity_b']}: "
                  f"{verdict['bucket']} ({verdict['relationship_type_raw']!r})", file=sys.stderr)
        return verdict

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        verdicts = list(pool.map(run, pairs))

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(verdicts, f, ensure_ascii=False, indent=2)

    counts = collections.Counter(v["bucket"] for v in verdicts)
    print(f"\n{len(verdicts)} pairs classified -> {args.out}", file=sys.stderr)
    for name, n in counts.most_common():
        print(f"  {name:<32} {n:>4}  ({n / len(verdicts):.0%})", file=sys.stderr)


if __name__ == "__main__":
    main()
