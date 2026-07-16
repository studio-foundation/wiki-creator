#!/usr/bin/env python3
"""Two co-occurrence arms: the shipped mechanism, and the same idea over real text.

`shipped` does not re-run anything. It reads the pipeline's own
relationships.json, because that artifact IS the arm: production's actual output
on this book. Reimplementing it was tried and abandoned — a faithful-looking
rebuild landed 487 pairs against production's 501, differing on 144, purely
because it assembled the roster in a different order. An arm that reproduces its
target to within a third of the graph is not a baseline, it is a second opinion.
See diagnose_baseline.py: that order-sensitivity is the finding, not an obstacle
to be worked around here.

`fixed` keeps every one of the shipped mechanism's ideas — a sliding sentence
window, a count, a chapter floor, an adjacency gate — and changes one thing: the
sentences are the chapter's, in the chapter's order, instead of a per-entity
sample stitched together in dict order. See diagnose_baseline.py for why that is
not a nuance. STU-536 landed that change in the stage itself, so `fixed` is now
a plain call into production; `shipped` is the artifact a pre-STU-536 run left
behind, and re-running the pipeline overwrites it.

The pair exists so the bake-off can answer a question the ticket cannot ask of
itself: whether co-occurrence loses to GLiREL because proximity is a weak signal
for relations, or because the shipped code is not measuring proximity. Only one
of those is fixed by buying a model.

Neither arm types anything. build_cooccurrence_graph emits relationship_type=None
by construction and the LLM classifier is a separate stage, so both arms score
zero on typing by design and are read on detection. That is the honest comparison:
scoring them on type would score the classifier bolted after them.

Usage:
    python runners/run_cooccurrence.py --arm shipped --roster roster.json
    python runners/run_cooccurrence.py --arm fixed   --roster roster_oracle.json
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(_HERE))), "scripts"))

from relationship_extraction import (  # noqa: E402
    DEFAULT_MIN_CHAPTERS_TOGETHER, DEFAULT_THRESHOLD, DEFAULT_WINDOW,
    build_cooccurrence_graph,
)


def shipped_predictions(processing_output: str) -> list[dict]:
    with open(os.path.join(processing_output, "relationships.json"), encoding="utf-8") as f:
        return json.load(f)["relationships"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("shipped", "fixed"), required=True)
    ap.add_argument("--roster", default="roster.json")
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--processing-output")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD)
    ap.add_argument("--min-chapters", type=int, default=DEFAULT_MIN_CHAPTERS_TOGETHER)
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.arm == "shipped":
        if not args.processing_output:
            sys.exit("--processing-output is required for the shipped arm")
        relationships = shipped_predictions(args.processing_output)
        checked = "n/a (read from the pipeline's own artifact)"
    else:
        with open(args.roster, encoding="utf-8") as f:
            roster = json.load(f)
        with open(args.corpus, encoding="utf-8") as f:
            chapters = [json.loads(line) for line in f if line.strip()]
        entities = [
            {"canonical_name": e["canonical_name"], "type": "PERSON",
             "aliases": e["aliases"], "relevant": True}
            for e in roster
        ]
        relationships, stats = build_cooccurrence_graph(
            entities, {c["id"]: c["text"] for c in chapters}, args.window, args.threshold,
            min_chapters_together=args.min_chapters,
        )
        checked = str(stats["total_pairs_checked"])

    out = args.out or f"predictions.cooccurrence_{args.arm}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(relationships, f, ensure_ascii=False, indent=2)
    print(f"{args.arm}: {len(relationships)} pairs of {checked} checked -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
