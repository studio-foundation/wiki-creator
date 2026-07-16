#!/usr/bin/env python3
"""Score the human votes from adjudicate.py. Pure, stdlib-only.

This is not the bake-off scorer. It answers a narrower question the bake-off
cannot: on the pairs where the two arms disagree, **who is right** — with a human
as the gold, so neither arm grades itself.

Three numbers, and mixing them was the mistake this file exists to avoid:

  JUNK — the share of an arm's pairs that name a roster entry the human says is not
  a character. It is an NER defect, not a discovery defect, and the two arms do not
  meet it on equal terms: the LLM's prompt tells it the roster holds non-people, and
  co-occurrence has no notion of type and cannot decline. Reported, never folded
  into precision, because folding it charges the window mechanism for GLiNER's
  `Rider`.

  DETECTION — precision on each arm's *unique* claims, over character pairs only. An
  arm whose unique pairs are real is finding what the other misses; an arm whose
  unique pairs are false is inventing. Recall is deliberately absent — a pair
  neither arm found is invisible to this method, which is the price of not
  annotating 60 chapters. Read it as "of what they disagree on, who wins", never as
  an F1.

  TYPING — type and direction accuracy on pairs both arms found. The axis the ticket
  is actually buying.

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


def yes_no(votes: dict) -> dict:
    return {k: v.strip().lower() for k, v in votes.items() if v.strip().lower() in ("o", "n")}


def rate(votes: dict, keys: set) -> tuple[int, int]:
    """(true, total) over voted rows whose pair is in `keys`."""
    total = true = 0
    for row, verdict in votes.items():
        a, b = (s.strip() for s in row.split("|"))
        if pair_key(a, b) not in keys:
            continue
        total += 1
        true += verdict == "o"
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

    roster = yes_no(votes.get("roster", {}))
    if not roster:
        sys.exit("no roster verdicts in votes.json — run `python vote.py` first.\n"
                 "Without them a pair naming a role noun scores as a discovery error.")
    characters = {n for n, v in roster.items() if v == "o"}
    junk = {n for n, v in roster.items() if v == "n"}
    real = lambda k: k[0] in characters and k[1] in characters  # noqa: E731

    print(f"ROSTER  {len(characters)} characters, {len(junk)} not: {', '.join(sorted(junk))}\n")

    print("JUNK PAIRS, each arm's own output (an NER defect, not a discovery one)\n")
    for name, keys in (("co-occurrence (fixed)", cooc), ("llm_schema", llm)):
        bad = [k for k in keys if not real(k)]
        print(f"  {name:24s} {len(bad):3d}/{len(keys):3d} pairs name a non-character "
              f"= {len(bad)/len(keys):.3f}")

    print("\nDETECTION, on character pairs exactly one arm found (human = gold)\n")
    detection = yes_no(votes.get("detection", {}))
    for name, keys in (("co-occurrence (fixed)", cooc - llm), ("llm_schema", llm - cooc)):
        true, total = rate(detection, {k for k in keys if real(k)})
        if not total:
            print(f"  {name:24s} no voted rows")
            continue
        print(f"  {name:24s} {true}/{total} unique pairs real "
              f"= {true/total:.3f} precision on its own claims")

    print("\nTYPING, on character pairs both arms found (llm_schema only emits types)\n")
    true, total = rate(yes_no(votes.get("typing", {})), {k for k in cooc & llm if real(k)})
    print(f"  type + direction correct  {true}/{total} = {true/total:.3f}" if total
          else "  no voted rows")


if __name__ == "__main__":
    main()
