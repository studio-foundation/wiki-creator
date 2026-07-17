#!/usr/bin/env python3
"""Score the collected alias-adjudication verdicts against the ground-truth corpora.

    PYTHONPATH=../.. python score.py

Three books ship a hand-written gold (`library/<author>/<series>/books/ground-truth/`),
each file naming one character and every name book 1 calls it. That is exactly the
question adjudication answers, so it judges a merge without an oracle:

* both names are aliases of the SAME gold character   -> true positive
* they are aliases of DIFFERENT gold characters       -> false positive
* one of them is not in the gold at all               -> unjudged, listed for a human

The gold covers a handful of characters per book, never the whole roster, so
`unjudged` is the normal case and is reported, never scored as a pass. Recall is
reported only where the gold can see it: two roster rows that are aliases of one
gold character and that no merge joined.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERDICTS = Path(__file__).parent / "verdicts"

_ARTICLE_RE = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)


def _key(name: str) -> str:
    return _ARTICLE_RE.sub("", name.strip()).casefold()


def gold_by_series() -> dict[str, dict[str, str]]:
    """series dir name -> {normalized alias: gold character}."""
    golds: dict[str, dict[str, str]] = {}
    for path in sorted(REPO_ROOT.glob("library/*/*/books/ground-truth/*.json")):
        series = path.parents[2].name
        data = json.loads(path.read_text(encoding="utf-8"))
        aliases = data.get("canonical_aliases_book1")
        if not data.get("entity") or not aliases:
            continue
        table = golds.setdefault(series, {})
        for alias in [data["entity"], *aliases]:
            table[_key(alias)] = data["entity"]
    return golds


def judge(merge: dict, gold: dict[str, str]) -> str:
    who_a = gold.get(_key(merge["a"]))
    who_b = gold.get(_key(merge["b"]))
    if who_a is None or who_b is None:
        return "unjudged"
    return "true_positive" if who_a == who_b else "false_positive"


def missed_merges(roster: list[dict], merges: list[dict], gold: dict[str, str]) -> list[tuple]:
    """Roster rows the gold says are one character, that no merge joined."""
    merged = {frozenset((m["a"], m["b"])) for m in merges}
    by_character: dict[str, list[str]] = {}
    for row in roster:
        who = gold.get(_key(row["name"]))
        if who:
            by_character.setdefault(who, []).append(row["name"])
    missed = []
    for who, names in by_character.items():
        if len(names) < 2:
            continue
        for i, name_a in enumerate(names):
            for name_b in names[i + 1:]:
                if frozenset((name_a, name_b)) not in merged:
                    missed.append((who, name_a, name_b))
    return missed


def main() -> None:
    golds = gold_by_series()
    totals = {"true_positive": 0, "false_positive": 0, "unjudged": 0}
    all_missed = 0

    for path in sorted(VERDICTS.glob("*.json")):
        series, _, book = path.stem.partition("__")
        data = json.loads(path.read_text(encoding="utf-8"))
        roster, merges = data["roster"], data["merge"]
        gold = golds.get(series, {})
        covered = sum(1 for row in roster if _key(row["name"]) in gold)

        print(f"\n## {series}/{book}")
        print(f"roster {len(roster)} ({covered} in gold) — {len(merges)} merge(s)")
        for merge in merges:
            verdict = judge(merge, gold)
            totals[verdict] += 1
            print(f"  [{verdict}] {merge['a']} = {merge['b']}")
            print(f"      quote: {merge['quote'][:160]}")
            print(f"      reason: {merge['reason'][:160]}")
        for who, name_a, name_b in missed_merges(roster, merges, gold):
            all_missed += 1
            print(f"  [missed] {name_a} / {name_b} — gold says both are {who}")

    judged = totals["true_positive"] + totals["false_positive"]
    print("\n## totals")
    print(f"merges: {judged + totals['unjudged']} "
          f"({judged} judgeable by gold, {totals['unjudged']} need a human)")
    if judged:
        print(f"precision on the judgeable: {totals['true_positive']}/{judged}")
    print(f"missed merges the gold can see: {all_missed}")


if __name__ == "__main__":
    main()
