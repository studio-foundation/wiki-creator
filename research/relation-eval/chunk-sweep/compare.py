#!/usr/bin/env python3
"""STU-611: compare discover-relationships pair sets across --chunk-chars sizes.

Reads discovered_<size>.json for each swept size, builds the undirected typed
pair set per size, and reports:
  * pair count per size and how many carry a usable type;
  * the pairs each size finds that the next-larger size drops (the recall cost);
  * each pair scored against the curated Narnia book-1 gold (below).

Gold is the interpersonal (PERSON-PERSON) relations in
library/.../books/ground-truth/*.json, mapped to the roster's canonical names.
It is embedded (not read) because ground-truth/ is gitignored — the committed
report must stand on its own. PLACE relations (Narnia, Cair Paravel) are excluded:
the discovery roster is PERSON-only, so they can never appear.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

SIZES = [4000, 6000, 12000]

# Curated from ground-truth/*.json known_relations_book1, mapped to the current
# roster's canonical names (registry of 2026-07-24: the Witch is canonically
# "White Witch" since the STU-543 adjudication merge). Pairs a human keeps as
# real book-1 bonds.
CHILDREN = ["Peter", "Susan", "Edmund", "LUCY"]
GOLD: set[frozenset[str]] = set()
def _g(a: str, b: str) -> None:
    GOLD.add(frozenset({a, b}))
# sibling quartet
for i, a in enumerate(CHILDREN):
    for b in CHILDREN[i + 1:]:
        _g(a, b)
# children <-> Aslan
for c in CHILDREN:
    _g(c, "Aslan")
_g("LUCY", "Mr Tumnus")
_g("Edmund", "White Witch")
_g("Peter", "MAUGRIM")
# Beavers
_g("Mr Beaver", "Mrs Beaver")
_g("Mr Beaver", "Mr Tumnus")
_g("Mr Beaver", "Aslan")
_g("Mr Beaver", "White Witch")
for c in CHILDREN:
    _g("Mr Beaver", c)
    _g("Mrs Beaver", c)
# Professor / Macready
_g("Professor", "LUCY")
_g("Professor", "Peter")
_g("Professor", "Susan")
_g("Professor", "Mrs Macready")
for c in CHILDREN:
    _g("Mrs Macready", c)


def load_pairs(path: Path) -> dict[frozenset[str], str]:
    """Return {pair: relationship_type} for one discovered_<size>.json."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[frozenset[str], str] = {}
    for rel in data.get("relationships", []):
        a, b = rel.get("entity_a"), rel.get("entity_b")
        if not a or not b or a == b:
            continue
        out[frozenset({a, b})] = rel.get("relationship_type") or "(none)"
    return out


def fmt(pair: frozenset[str]) -> str:
    return " — ".join(sorted(pair))


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent
    per_size = {s: load_pairs(base / f"discovered_{s}.json") for s in SIZES}

    print("## Pair counts per chunk size\n")
    print("| chunk_chars | pairs | gold-hit | non-gold |")
    print("|---:|---:|---:|---:|")
    for s in SIZES:
        pairs = set(per_size[s])
        hits = pairs & GOLD
        print(f"| {s} | {len(pairs)} | {len(hits)} | {len(pairs - GOLD)} |")
    print(f"\nGold PERSON-PERSON pairs total: {len(GOLD)}")

    print("\n## Gold recall per size\n")
    for s in SIZES:
        missed = GOLD - set(per_size[s])
        print(f"- {s}: {len(GOLD) - len(missed)}/{len(GOLD)} gold found; "
              f"missed: {', '.join(sorted(fmt(p) for p in missed)) or 'none'}")

    print("\n## Dropped going to a larger chunk (the recall cost)\n")
    for small, big in [(4000, 6000), (6000, 12000), (4000, 12000)]:
        dropped = set(per_size[small]) - set(per_size[big])
        print(f"### {small} → {big}: {len(dropped)} pairs dropped")
        for p in sorted(dropped, key=fmt):
            tag = "GOLD" if p in GOLD else "non-gold"
            print(f"  - [{tag}] {fmt(p)}  ({per_size[small][p]})")
        gained = set(per_size[big]) - set(per_size[small])
        gold_gained = sorted(fmt(p) for p in gained & GOLD)
        print(f"  (+{len(gained)} gained, {len(gained & GOLD)} gold: "
              f"{', '.join(gold_gained) or 'none'})")

    print("\n## Union / stability\n")
    union = set().union(*[set(per_size[s]) for s in SIZES])
    core = set(per_size[4000]) & set(per_size[6000]) & set(per_size[12000])
    print(f"union of all sizes: {len(union)} pairs; found at ALL three: {len(core)} "
          f"({len(core & GOLD)} gold)")


if __name__ == "__main__":
    main()
