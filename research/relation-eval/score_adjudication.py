#!/usr/bin/env python3
"""Score the human votes from adjudicate.py. Pure, stdlib-only.

This is not the bake-off scorer. It answers a narrower question the bake-off
cannot: on the pairs where the two arms disagree, **who is right** — with a human
as the gold, so neither arm grades itself.

Three numbers, and mixing them was the mistake this file exists to avoid:

  JUNK — the share of an arm's pairs that no relation-discovery mechanism could get
  right, because the entity layer handed it a bad pair: one naming a roster entry
  the human says is not a character (`Rider`, a role), or one whose two names are
  the same person under two names (`Brom | Neal`, `aliases.yaml`). Both are entity
  defects, not discovery defects, and the two arms do not meet them on equal terms —
  the LLM's prompt tells it the roster holds non-people, and it knows Neal is Brom;
  co-occurrence has no notion of type or identity and matches both by regex.
  Reported, never folded into precision, because folding it charges the window
  mechanism for GLiNER's `Rider` and alias-resolution's `Neal`.

  Aliases are folded before anything is scored, so `Neal | Arya` and `Brom | Arya`
  are one claim and not two. That is what the pipeline's own `relationship_fold`
  (STU-435) does downstream; doing it here keeps the arms comparable rather than
  rewarding whichever one happened to emit the canonical surface.

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

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))

from wiki_creator.relationship_eval import pair_key  # noqa: E402

SELF_PAIR = "__self__"


def folder(aliases: dict[str, str]):
    """(a, b) -> canonical pair_key, or SELF_PAIR when both names are one person."""
    def fold(a: str, b: str):
        a, b = aliases.get(a, a), aliases.get(b, b)
        return SELF_PAIR if a == b else pair_key(a, b)
    return fold


def load_keys(path: str, fold) -> set:
    with open(path, encoding="utf-8") as f:
        return {fold(p["entity_a"], p["entity_b"]) for p in json.load(f)}


def yes_no(votes: dict) -> dict:
    return {k: v.strip().lower() for k, v in votes.items() if v.strip().lower() in ("o", "n")}


def rate(votes: dict, keys: set, fold) -> tuple[int, int]:
    """(true, total) over voted rows whose folded pair is in `keys`."""
    seen, true = set(), 0
    for row, verdict in votes.items():
        a, b = (s.strip() for s in row.split("|"))
        key = fold(a, b)
        if key not in keys or key in seen:  # two surfaces of one pair vote once
            continue
        seen.add(key)
        true += verdict == "o"
    return true, len(seen)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--votes", default="votes.json")
    ap.add_argument("--cooccurrence", default="predictions.cooccurrence_fixed.json")
    ap.add_argument("--llm", default="predictions.llm_schema.json")
    ap.add_argument("--aliases", default="aliases.yaml")
    args = ap.parse_args()

    with open(args.votes, encoding="utf-8") as f:
        votes = json.load(f)
    with open(args.aliases, encoding="utf-8") as f:
        aliases = yaml.safe_load(f) or {}
    fold = folder(aliases)
    cooc = load_keys(args.cooccurrence, fold)
    llm = load_keys(args.llm, fold)

    roster = yes_no(votes.get("roster", {}))
    if not roster:
        sys.exit("no roster verdicts in votes.json — run `python vote.py` first.\n"
                 "Without them a pair naming a role noun scores as a discovery error.")
    characters = {aliases.get(n, n) for n, v in roster.items() if v == "o"}
    junk = {n for n, v in roster.items() if v == "n"}

    def real(k) -> bool:
        return k is not SELF_PAIR and k[0] in characters and k[1] in characters

    print(f"ROSTER  {len(roster)} entries: {len(junk)} not characters "
          f"({', '.join(sorted(junk))}), {len(aliases)} aliases folded away\n")

    print("JUNK PAIRS — the entity layer's defects, which no window can fix\n")
    for name, keys in (("co-occurrence (fixed)", cooc), ("llm_schema", llm)):
        bad = [k for k in keys if not real(k)]
        selfs = sum(1 for k in keys if k is SELF_PAIR)
        print(f"  {name:24s} {len(bad):3d}/{len(keys):3d} = {len(bad)/len(keys):.3f}"
              f"   (non-character: {len(bad) - selfs}, one person twice: {selfs})")

    print("\nDETECTION, on character pairs exactly one arm found (human = gold)\n")
    detection = yes_no(votes.get("detection", {}))
    for name, keys in (("co-occurrence (fixed)", cooc - llm), ("llm_schema", llm - cooc)):
        true, total = rate(detection, {k for k in keys if real(k)}, fold)
        if not total:
            print(f"  {name:24s} no voted rows")
            continue
        print(f"  {name:24s} {true}/{total} unique pairs real "
              f"= {true/total:.3f} precision on its own claims")

    print("\nTYPING, on character pairs both arms found (llm_schema only emits types)\n")
    true, total = rate(yes_no(votes.get("typing", {})), {k for k in cooc & llm if real(k)}, fold)
    print(f"  type + direction correct  {true}/{total} = {true/total:.3f}" if total
          else "  no voted rows")


if __name__ == "__main__":
    main()
