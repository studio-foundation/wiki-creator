#!/usr/bin/env python3
"""Score the human votes from adjudicate.py. Pure, stdlib-only.

This is not the bake-off scorer. It answers a narrower question the bake-off
cannot: on the pairs where the two arms disagree, **who is right** — with a human
as the gold, so neither arm grades itself.

Precision on the disputed set is the number that decides, and it is not the same
as the report's precision: the denominator here is only an arm's *unique* claims.
An arm whose unique pairs are real is finding what the other misses; an arm whose
unique pairs are false is inventing. Recall is deliberately absent — a pair
neither arm found is invisible to this method, which is the price of not
annotating 60 chapters. Read it as "of what they disagree on, who wins", never
as an F1.

Usage:
    python score_adjudication.py --votes votes.json
"""
import argparse
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from wiki_creator.relationship_eval import pair_key  # noqa: E402


def load_keys(path: str) -> set:
    with open(path, encoding="utf-8") as f:
        return {pair_key(p["entity_a"], p["entity_b"]) for p in json.load(f)}


def rate(votes: dict, keys: set) -> tuple[int, int]:
    """(true, total) over the voted rows belonging to `keys`."""
    total = true = 0
    for row, verdict in votes.items():
        a, b = (s.strip() for s in row.split("|"))
        if pair_key(a, b) not in keys:
            continue
        v = verdict.strip().lower()
        if v not in ("o", "n"):
            continue
        total += 1
        true += v == "o"
    return true, total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--votes", default="votes.json")
    ap.add_argument("--cooccurrence", default="predictions.cooccurrence_fixed.json")
    ap.add_argument("--llm", default="predictions.llm_schema.json")
    args = ap.parse_args()

    with open(args.votes, encoding="utf-8") as f:
        votes = json.load(f)
    cooc, llm = load_keys(args.cooccurrence), load_keys(args.llm)

    unvoted = [k for k, v in votes["detection"].items() if v.strip().lower() not in ("o", "n")]
    if unvoted:
        print(f"[WARN] {len(unvoted)} detection rows unvoted — excluded", file=sys.stderr)

    print("DETECTION, on the pairs exactly one arm found (human = gold)\n")
    for name, keys in (("co-occurrence (fixed)", cooc - llm), ("llm_schema", llm - cooc)):
        true, total = rate(votes["detection"], keys)
        if not total:
            print(f"  {name:24s} no voted rows")
            continue
        print(f"  {name:24s} {true}/{total} unique pairs real "
              f"= {true/total:.3f} precision on its own claims")

    print("\nTYPING, on pairs both arms found (llm_schema only emits types)\n")
    true, total = rate(votes["typing"], cooc & llm)
    if total:
        print(f"  type + direction correct  {true}/{total} = {true/total:.3f}")
    else:
        print("  no voted rows")


if __name__ == "__main__":
    main()
