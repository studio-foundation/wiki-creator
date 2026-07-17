#!/usr/bin/env python3
"""Score the collected alias-adjudication verdicts against the ground-truth corpora.

    PYTHONPATH=../.. python score.py

Three books ship a hand-written gold (`library/<author>/<series>/books/ground-truth/`),
each entry naming one character, every name book 1 calls it
(`canonical_aliases_book1`), and the identity confusions a page must never make
(`identity_confusion_forbidden`, e.g. `"alias: Daughter of Eve"` under Lucy). That is
exactly the question adjudication answers, so it judges a merge without an oracle:

* both names are aliases of the SAME gold character            -> true positive
* they are aliases of DIFFERENT gold characters                -> false positive
* the gold forbids this very confusion for one of them         -> false positive
* one of them is not in the gold at all                        -> unjudged, for a human

The gold covers a handful of characters per book, never a whole roster, so `unjudged`
is the normal case and is reported, never scored as a pass. Recall is reported only
where the gold can see it: two roster rows that are aliases of one gold character
and that no merge joined.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERDICTS = Path(__file__).parent / "verdicts"

_ARTICLE_RE = re.compile(r"^(the|a|an|la|le|les)\s+", re.IGNORECASE)
_FORBIDDEN_ALIAS_RE = re.compile(r"^alias\s*:\s*(.+)$", re.IGNORECASE)


def _key(name: str) -> str:
    return _ARTICLE_RE.sub("", name.strip()).casefold()


def _entries(data: object):
    """Every gold character in a file — top-level, or one per nested sub-object."""
    if not isinstance(data, dict):
        return
    if data.get("canonical_aliases_book1"):
        yield data.get("entity"), data
    for key, value in data.items():
        if isinstance(value, dict) and value.get("canonical_aliases_book1"):
            yield value.get("entity") or key, value


class Gold:
    """One book's gold: who each name is, and the confusions it forbids."""

    def __init__(self) -> None:
        self.who: dict[str, str] = {}
        self.forbidden: set[tuple[str, str]] = set()

    def add(self, name: str, entry: dict) -> None:
        for alias in [name, *entry["canonical_aliases_book1"]]:
            self.who[_key(alias)] = name
        for line in entry.get("identity_confusion_forbidden", []):
            match = _FORBIDDEN_ALIAS_RE.match(str(line).strip())
            if match:
                self.forbidden.add((_key(name), _key(match.group(1))))

    def judge(self, name_a: str, name_b: str) -> str:
        key_a, key_b = _key(name_a), _key(name_b)
        who_a, who_b = self.who.get(key_a), self.who.get(key_b)
        for owner, forbidden in ((who_a, key_b), (who_b, key_a)):
            if owner and (_key(owner), forbidden) in self.forbidden:
                return "false_positive"
        if who_a is None or who_b is None:
            return "unjudged"
        return "true_positive" if who_a == who_b else "false_positive"


def gold_by_series() -> dict[str, Gold]:
    golds: dict[str, Gold] = {}
    for path in sorted(REPO_ROOT.glob("library/*/*/books/ground-truth/*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for name, entry in _entries(data):
            if name:
                golds.setdefault(path.parents[2].name, Gold()).add(name, entry)
    return golds


def missed_merges(roster: list[dict], merges: list[dict], gold: Gold) -> list[tuple]:
    """Roster rows the gold says are one character, that no merge joined."""
    merged = {frozenset((m["a"], m["b"])) for m in merges}
    by_character: dict[str, list[str]] = {}
    for row in roster:
        who = gold.who.get(_key(row["name"]))
        if who:
            by_character.setdefault(who, []).append(row["name"])
    return [
        (who, name_a, name_b)
        for who, names in by_character.items()
        for i, name_a in enumerate(names)
        for name_b in names[i + 1:]
        if frozenset((name_a, name_b)) not in merged
    ]


def main() -> None:
    golds = gold_by_series()
    totals = {"true_positive": 0, "false_positive": 0, "unjudged": 0}
    all_missed = 0

    for path in sorted(VERDICTS.glob("*.json")):
        series, _, book = path.stem.partition("__")
        data = json.loads(path.read_text(encoding="utf-8"))
        roster, merges = data["roster"], data["merge"]
        gold = golds.get(series, Gold())
        covered = sum(1 for row in roster if _key(row["name"]) in gold.who)

        print(f"\n## {series}/{book}")
        print(f"roster {len(roster)} ({covered} in gold) — {len(merges)} merge(s)")
        for merge in merges:
            verdict = gold.judge(merge["a"], merge["b"])
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
          f"({judged} judged by gold, {totals['unjudged']} need a human)")
    if judged:
        print(f"precision on the judged: {totals['true_positive']}/{judged}")
    print(f"missed merges the gold can see: {all_missed}")


if __name__ == "__main__":
    main()
