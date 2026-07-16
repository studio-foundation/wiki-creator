#!/usr/bin/env python3
"""Which roster pairs are ever within reach of a proximity method.

This is the benchmark's load-bearing definition — it decides the implicit stratum,
which is where the ticket's charge against co-occurrence lives — so it is computed
from the text and from nothing else. Two alternatives were rejected:

  - Ask the annotator. The split would become a model judgment, on the one axis
    no arm can be checked against.
  - Reuse the baseline's own admission rule. build_cooccurrence_graph does not
    read the chapter; it reads the sentences that were already somebody's mention
    context, inside a 5-sentence window, and drops a pair whose tightest span has
    a gap above _MAX_DIRECT_INTERACTION_GAP. Scoring the baseline against a
    stratum its own selection machinery defined would answer the question with
    itself.

What is computed instead is plain textual proximity over raw chapter sentences:
a pair is explicit if its two surfaces ever land within `--max-sentence-gap`
sentences of each other, anywhere in the book. The default gap of 1 mirrors
_MAX_DIRECT_INTERACTION_GAP on purpose. That is not circularity, it is calibration:
it puts every pair co-occurrence could plausibly reach into the explicit stratum,
so the implicit stratum holds only pairs no proximity method reaches at any
threshold. The stratum is therefore a floor on the charge, never an inflation of
it — an arm that beats the baseline on implicit pairs has beaten it on relations
the mechanism cannot see, not on ones it happened to miss.

Segmentation is spaCy's rule-based sentencizer on a blank pipeline — no model, no
NER, nothing that could import an arm's opinion. Matching is the alias-and-word-
boundary rule build_cooccurrence_graph uses, minus its 4-character alias floor:
that floor protects a co-occurrence count from noise, and here it would quietly
move pairs into the implicit stratum for a reason unrelated to the text.

Usage:
    python explicit_pairs.py --corpus corpus.jsonl --roster roster.json
"""
import argparse
import json
import re
import sys
from itertools import combinations


def surface_pattern(aliases: list[str]) -> re.Pattern:
    ordered = sorted({a for a in aliases if a.strip()}, key=len, reverse=True)
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(a) for a in ordered) + r")(?!\w)")


def _within(a_idx: set[int], b_idx: set[int], gap: int) -> bool:
    return any(abs(i - j) <= gap for i in a_idx for j in b_idx)


def explicit_pairs(chapters: list[dict], roster: list[dict], gap: int = 1) -> dict[tuple, dict]:
    """{pair_key: {same_sentence, within_gap}} for every pair ever within `gap`."""
    import spacy

    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")

    patterns = {r["canonical_name"]: surface_pattern(r["aliases"]) for r in roster}
    found: dict[tuple, dict] = {}

    for chapter in chapters:
        sents = [s.text for s in nlp(chapter["text"]).sents]
        where: dict[str, set[int]] = {}
        for i, text in enumerate(sents):
            for name, pat in patterns.items():
                if pat.search(text):
                    where.setdefault(name, set()).add(i)

        for a, b in combinations(sorted(where), 2):
            if not _within(where[a], where[b], gap):
                continue
            slot = found.setdefault((a, b), {"same_sentence": 0, "within_gap": 0})
            slot["same_sentence"] += len(where[a] & where[b])
            slot["within_gap"] += 1

    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--roster", default="roster.json")
    ap.add_argument("--max-sentence-gap", type=int, default=1)
    ap.add_argument("--out", default="explicit_pairs.json")
    args = ap.parse_args()

    with open(args.corpus, encoding="utf-8") as f:
        chapters = [json.loads(line) for line in f if line.strip()]
    with open(args.roster, encoding="utf-8") as f:
        roster = json.load(f)

    found = explicit_pairs(chapters, roster, args.max_sentence_gap)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(
            [{"entity_a": a, "entity_b": b, **v}
             for (a, b), v in sorted(found.items(), key=lambda kv: -kv[1]["within_gap"])],
            f, ensure_ascii=False, indent=2,
        )

    total = len(roster) * (len(roster) - 1) // 2
    same = sum(1 for v in found.values() if v["same_sentence"])
    print(f"{len(roster)} entities, {total} possible pairs", file=sys.stderr)
    print(f"{len(found)} pairs within {args.max_sentence_gap} sentence(s) somewhere "
          f"({same} of them share a sentence) -> {args.out}", file=sys.stderr)
    print(f"{total - len(found)} pairs no proximity method can reach", file=sys.stderr)


if __name__ == "__main__":
    main()
