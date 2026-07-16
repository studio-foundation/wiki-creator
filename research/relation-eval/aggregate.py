"""Fold per-chapter relation votes into book-level gold pairs. Pure, stdlib-only.

A pair's type is a set, not a scalar. Relations move inside one book — Eragon and
Murtagh are a wary_alliance for twenty chapters and friends by the end — so a gold
that forced one token would score a correct reading as an error. `acceptable` is
every type any chapter evidenced, ordered by how many chapters evidenced it, so
the primary is the book's dominant reading and the alternates are the arcs.

Ordering the pair is not cosmetic. `pair_key` sorts the two names, and `direction`
is stated relative to entity_a, so a vote naming (Brom, Eragon) and one naming
(Eragon, Brom) mean opposite things by the same token. Flipping is the only place
in this file where a bug would silently invert a result, so it has its own test.
"""
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from wiki_creator.relationship_eval import pair_key  # noqa: E402

SYMMETRIC = "symétrique"
_FLIP = {"A→B": "B→A", "B→A": "A→B", SYMMETRIC: SYMMETRIC}


def flip(direction: str) -> str:
    """Restate a direction against the opposite entity order."""
    return _FLIP.get(direction, direction)


def aggregate(
    votes: list[dict],
    roster: list[dict],
    explicit_pairs: set | None = None,
) -> tuple[list[dict], list[str]]:
    """Returns (gold_pairs, rejected) — rejected names an entity off the roster.

    explicit_pairs: pair_keys whose two entities share a sentence somewhere in the
    book. Absent, every pair is called explicit — which silently disarms the
    benchmark's central axis, so callers that mean it must pass the set.
    """
    known = {r["canonical_name"] for r in roster}
    explicit = explicit_pairs if explicit_pairs is not None else None

    acc: dict[tuple, dict] = {}
    rejected: list[str] = []

    for vote in votes:
        chapter_id = vote["chapter_id"]
        for rel in vote["relations"]:
            a, b = rel["entity_a"], rel["entity_b"]
            if a not in known or b not in known:
                rejected.append(f"{chapter_id}: {a} / {b}")
                continue
            if a == b:
                rejected.append(f"{chapter_id}: self-pair {a}")
                continue

            key = pair_key(a, b)
            slot = acc.setdefault(key, {
                "types": Counter(), "directions": Counter(),
                "chapters": set(), "evidence": [],
            })
            slot["types"][rel["relationship_type"]] += 1
            # The vote states direction against its own (a, b) order; the gold
            # states it against the sorted key. Same claim, opposite token.
            direction = rel["direction"] if (a, b) == key else flip(rel["direction"])
            slot["directions"][direction] += 1
            slot["chapters"].add(chapter_id)
            if rel.get("evidence"):
                slot["evidence"].append(f"{chapter_id}: {rel['evidence']}")

    pairs = []
    for key, slot in acc.items():
        pairs.append({
            "entity_a": key[0],
            "entity_b": key[1],
            "acceptable": [t for t, _ in slot["types"].most_common()],
            "direction": slot["directions"].most_common(1)[0][0],
            "chapters": sorted(slot["chapters"]),
            "implicit": key not in explicit if explicit is not None else False,
            "evidence": slot["evidence"][:3],
        })

    pairs.sort(key=lambda p: (-len(p["chapters"]), p["entity_a"], p["entity_b"]))
    return pairs, rejected
