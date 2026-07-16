#!/usr/bin/env python3
"""Measure what the shipped co-occurrence window is actually adjacent in.

What it describes is the pre-STU-536 mechanism, and STU-536 fixed it. The first
half reads the pooled list back out of the artifacts, so it still reports what
that list was; the shuffle at the end calls the stage, so it now reads 0%.

Run before reading any bake-off number: it decides what the bake-off is even
comparing. STU-467 charges co-occurrence with "proximity is not relation". This
script tests the prior question — whether the mechanism measures proximity at all.

build_cooccurrence_graph slides a 5-sentence window over `chapter_sentences`, and
admits a pair as a *direct interaction* when its two names fall within
_MAX_DIRECT_INTERACTION_GAP (1) sentences of each other in that window. The name
and the constant both promise textual adjacency.

`chapter_sentences` is not the chapter. It is built (relationship_extraction.py
:208-221) by iterating `mentions_by_entity` — a dict keyed by entity — and
appending each entity's context sentences for that chapter. Two facts follow:

  - Each entity contributes at most 3 sentences per chapter (the extraction-side
    context cap), so the list is a sparse sample, not the text.
  - The list is ordered by ENTITY, then by position. Entity 1's three sentences,
    then entity 2's three, and so on. Position in the chapter orders sentences
    only within one entity's block.

So sentence i and sentence i+1 routinely belong to different entities and sit
pages apart in the book, while the window reads them as adjacent and scores the
pair as a direct interaction. This script quantifies the gap between the two
readings of "adjacent" by locating every unified sentence back in its chapter.

Only cross-entity adjacencies are measured: an entity's own block is in text
order, so it is not where the mechanism can mislead.

The second measurement follows from the first. If the list is ordered by entity,
then the ENTITY order decides which sentences are adjacent, and the entity order
is dict insertion order — an artifact of how the roster was assembled, carrying no
information about the book. Shuffling the roster and re-running the real
build_cooccurrence_graph on the same text with the same parameters shows how much
of the relationship graph that artifact decides.

Usage:
    python diagnose_baseline.py \\
        --processing-output ../../library/christopher_paolini/inheritance/processing_output/01_eragon
"""
import argparse
import json
import os
import random
import statistics
import sys

# The pipeline stores a bounded prefix of each sentence; matching on a prefix is
# enough to locate it and avoids a miss when the stored text was trimmed.
_LOCATE_PREFIX = 70


def unified_sentences(persons_full: dict, roster: list[dict], chapter_id: str) -> list[tuple[str, str]]:
    """Rebuild build_cooccurrence_graph's per-chapter list. Returns [(owner, sentence)]."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for entity in roster:
        for eid in entity.get("source_ids", []):
            for sentence in persons_full.get(eid, {}).get("mentions_by_chapter", {}).get(chapter_id, []):
                if sentence not in seen:
                    seen.add(sentence)
                    out.append((entity["canonical_name"], sentence))
    return out


def cross_entity_distances(unified: list[tuple[str, str]], text: str) -> list[int]:
    """Real character distance between sentences the window calls adjacent."""
    located = [(owner, text.find(s[:_LOCATE_PREFIX])) for owner, s in unified]
    distances = []
    for (owner_a, pos_a), (owner_b, pos_b) in zip(located, located[1:]):
        if pos_a < 0 or pos_b < 0 or owner_a == owner_b:
            continue
        distances.append(abs(pos_b - pos_a))
    return distances


def pairs_for_order(roster: list[dict], texts: dict) -> set:
    """Run the real build_cooccurrence_graph over this roster order."""
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
    from relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": e["canonical_name"], "type": "PERSON",
         "aliases": e.get("aliases") or [], "relevant": True}
        for e in roster
    ]
    relationships, _ = build_cooccurrence_graph(entities, texts)
    return {tuple(sorted((r["entity_a"], r["entity_b"]))) for r in relationships}


def report_order_sensitivity(roster: list[dict], texts: dict, seeds: list[int]) -> None:
    base = pairs_for_order(roster, texts)
    print(f"roster in its own order: {len(base)} pairs")
    for seed in seeds:
        shuffled = roster[:]
        random.Random(seed).shuffle(shuffled)
        got = pairs_for_order(shuffled, texts)
        drift = len(base ^ got)
        print(f"  shuffled (seed {seed}): {len(got):4} pairs, {drift:4} differ "
              f"= {drift / max(len(base), 1):.0%} of the graph")
    print()
    print("Same entities, same text, same parameters. Since STU-536, the window")
    print("slides over the chapter, so the roster order decides nothing: 0% is the")
    print("expected reading, and anything else is a regression.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--processing-output", required=True)
    ap.add_argument("--near-chars", type=int, default=300,
                    help="what a genuinely adjacent pair of sentences looks like")
    ap.add_argument("--shuffle-seeds", type=int, nargs="*", default=[1, 2, 3])
    args = ap.parse_args()

    root = args.processing_output
    with open(os.path.join(root, "persons_full.json"), encoding="utf-8") as f:
        persons_full = json.load(f)["persons_full"]
    with open(os.path.join(root, "chapters.json"), encoding="utf-8") as f:
        texts = json.load(f)["chapters"]
    with open(os.path.join(root, "relationships.json"), encoding="utf-8") as f:
        bundle = json.load(f)

    roster = [e for e in bundle["entities"]
              if e.get("type") == "PERSON" and e.get("relevant", True)]

    distances: list[int] = []
    for chapter_id, text in texts.items():
        unified = unified_sentences(persons_full, roster, chapter_id)
        distances.extend(cross_entity_distances(unified, text))

    if not distances:
        sys.exit("no cross-entity adjacencies found — check the artifacts")

    distances.sort()
    near = sum(1 for d in distances if d < args.near_chars)
    print(f"{len(roster)} PERSON entities, {len(texts)} chapters")
    print(f"{len(distances)} sentence pairs the 5-sentence window reads as adjacent, "
          f"across two different entities")
    print()
    print("their real distance in the chapter text, in characters:")
    for q in (10, 25, 50, 75, 90):
        print(f"  p{q:<3} {distances[int(len(distances) * q / 100)]:8}")
    print(f"  mean {statistics.mean(distances):8.0f}")
    print(f"  max  {max(distances):8}")
    print()
    print(f"within {args.near_chars} chars (actually adjacent prose): "
          f"{near}/{len(distances)} = {near / len(distances):.0%}")
    print()
    print("_MAX_DIRECT_INTERACTION_GAP admits these pairs as direct interactions.")
    print()
    print("=== how much of the graph does the entity order decide? ===")
    report_order_sensitivity(roster, texts, args.shuffle_seeds)


if __name__ == "__main__":
    main()
