#!/usr/bin/env python3
"""Measure what the shipped co-occurrence window is actually adjacent in.

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

Usage:
    python diagnose_baseline.py \\
        --processing-output ../../library/christopher_paolini/inheritance/processing_output/01_eragon
"""
import argparse
import json
import os
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--processing-output", required=True)
    ap.add_argument("--near-chars", type=int, default=300,
                    help="what a genuinely adjacent pair of sentences looks like")
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


if __name__ == "__main__":
    main()
