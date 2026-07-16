#!/usr/bin/env python3
"""Build the human adjudication sheet — the one thing that removes the LLM gold's confound.

`build_gold.py` is written by an LLM and `run_llm_schema.py` is an LLM, so that
arm partly grades itself (caveat 1 of the report). A hand-annotated gold over 60
chapters lifts it and will never be written. This does the same job for the
decision at a fraction of the reading: it asks a human only where the two arms
*disagree*, and makes those votes the gold on that set. Everything the arms agree
on needs no adjudication — agreement between an LLM and a regex is not the
confound.

Two sections, because the ticket's question has two halves:

  DETECTION — a stratified sample of the pairs exactly one arm found, equal
  numbers from each arm so neither is over-represented in the estimate. **Blind**:
  rows are sorted by name and never say which arm claimed the pair, so a vote
  cannot be a vote for an architecture. Evidence is the book's own text (the
  windows where both names appear), never an arm's output, for the same reason.

  Blindness is partial and cannot be total: co-occurrence cannot emit a pair whose
  names never share a window, so a row marked as having no shared window is
  necessarily the LLM's. On Eragon that is 4 of 102 disputed pairs. Every other row
  is genuinely unattributable.

  TYPING — a sample of pairs both arms found, where only the LLM has a type.
  Not blind and cannot be: only one arm emits types. It measures the axis the
  ticket is actually buying (type + direction at discovery), which detection
  alone cannot price.

Usage:
    python adjudicate.py --corpus corpus.jsonl --roster roster.json
    python vote.py            # answer o/n, writes votes.json
    python score_adjudication.py --votes votes.json
"""
import argparse
import json
import os
import random
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(_HERE)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(_HERE)), "scripts"))

from wiki_creator.relationship_eval import pair_key  # noqa: E402
from relationship_extraction import split_sentences  # noqa: E402

MAX_WINDOWS = 2
WINDOW_SENTENCES = 5


def names_of(roster: list[dict]) -> dict[str, list[str]]:
    return {e["canonical_name"]: [e["canonical_name"], *e.get("aliases", [])] for e in roster}


def windows_for(pair: tuple[str, str], chapters: list[dict], forms: dict) -> list[str]:
    """Verbatim passages of the book where both names land within one window.

    The evidence a human reads must come from the novel, not from an arm: quoting
    the LLM's own `evidence` field next to a pair only the LLM found would tell the
    annotator which arm to side with.
    """
    a_forms = [f.lower() for f in forms.get(pair[0], [])]
    b_forms = [f.lower() for f in forms.get(pair[1], [])]
    out = []
    for chapter in chapters:
        sentences = split_sentences(chapter["text"])
        for i in range(len(sentences)):
            window = sentences[i : i + WINDOW_SENTENCES]
            blob = " ".join(window).lower()
            if any(f in blob for f in a_forms) and any(f in blob for f in b_forms):
                out.append(f"[{chapter['title']}] " + " ".join(window).strip())
                break  # one window per chapter is enough to judge
        if len(out) >= MAX_WINDOWS:
            break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--roster", default="roster_oracle.json")
    ap.add_argument("--cooccurrence", default="predictions.cooccurrence_fixed.json")
    ap.add_argument("--llm", default="predictions.llm_schema.json")
    ap.add_argument("--detection-sample", type=int, default=20,
                    help="disputed pairs to adjudicate PER ARM (0 = all)")
    ap.add_argument("--typing-sample", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="adjudication.json")
    args = ap.parse_args()

    with open(args.corpus, encoding="utf-8") as f:
        chapters = [json.loads(line) for line in f if line.strip()]
    with open(args.roster, encoding="utf-8") as f:
        roster = json.load(f)
    with open(args.cooccurrence, encoding="utf-8") as f:
        cooc = {pair_key(p["entity_a"], p["entity_b"]) for p in json.load(f)}
    with open(args.llm, encoding="utf-8") as f:
        llm = {pair_key(p["entity_a"], p["entity_b"]): p for p in json.load(f)}

    forms = names_of(roster)
    rng = random.Random(args.seed)
    agreed = sorted(cooc & set(llm))

    # Sample per arm, not from the pooled disputed set: the arms disagree in very
    # unequal numbers (75 vs 27 on Eragon), and a pooled sample would spend the
    # human's votes on whichever arm is noisier and leave the other unmeasured.
    disputed = []
    for keys in (cooc - set(llm), set(llm) - cooc):
        pool = sorted(keys)
        n = len(pool) if args.detection_sample == 0 else min(args.detection_sample, len(pool))
        disputed += rng.sample(pool, n)
    disputed.sort()

    sheet = {"detection": [], "typing": []}
    for a, b in disputed:
        sheet["detection"].append({
            "key": f"{a} | {b}",
            "windows": windows_for((a, b), chapters, forms),
        })

    for a, b in sorted(rng.sample(agreed, min(args.typing_sample, len(agreed)))):
        pred = llm[(a, b)]
        sheet["typing"].append({
            "key": f"{a} | {b}",
            "relationship_type": pred["relationship_type"],
            "direction": pred["direction"],
            "evidence": pred.get("evidence", [])[:2],
        })

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(sheet, f, ensure_ascii=False, indent=2)

    print(f"{len(sheet['detection'])} disputed, {len(sheet['typing'])} typing rows -> {args.out}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
