#!/usr/bin/env python3
"""Arm: schema-guided LLM extraction — type and direction at discovery, one pass.

READ THE CONFOUND FIRST. The gold is built by an LLM (build_gold.py). This arm is
an LLM. Its score is therefore partly a measure of how much two LLM runs agree,
not of how right either is, and it is biased upward by every convention the two
share. Nothing in this file removes that; two things only blunt it:

  - a different model from the gold's (default sonnet vs the gold's opus), so the
    arm is not literally its own grader, and
  - a production-shaped task: chunks, not whole chapters, because feeding 30k
    characters per chapter to a writer LLM is not what this pipeline would ship,
    and a benchmark that grants the arm an affordance production would not is
    measuring a system nobody can deploy.

The consequence is a rule for reading the report: this arm's number is an upper
bound on schema-guided extraction, not a measurement of it. The comparison that
survives the confound is GLiREL vs co-occurrence — neither is an LLM, so neither
is flattered by the gold's provenance.

Usage:
    python runners/run_llm_schema.py --roster roster_oracle.json --model claude-sonnet-5
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))

from aggregate import aggregate  # noqa: E402
from build_gold import valid_relations  # noqa: E402
from claude_cli import complete_json  # noqa: E402
from wiki_creator.page_templates import relationship_definitions  # noqa: E402

DEFAULT_CHUNK_CHARS = 6000


def chunks_of(chapter: dict, size: int) -> list[dict]:
    """Split on paragraph breaks, which STU-523 put in the text for exactly this."""
    parts, buf = [], ""
    for para in chapter["text"].split("\n\n"):
        if buf and len(buf) + len(para) > size:
            parts.append(buf)
            buf = para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        parts.append(buf)
    return [{"id": f"{chapter['id']}:{i}", "chapter_id": chapter["id"],
             "title": chapter["title"], "text": t} for i, t in enumerate(parts)]


def prompt_for(roster_names: list[str], passage: dict) -> str:
    types = "\n".join(f"- {d['name']}: {d['description']}" for d in relationship_definitions())
    names = "\n".join(f"- {n}" for n in roster_names)
    return f"""Extract the interpersonal relations this passage of a fantasy novel gives
evidence for, between two entities from this roster:

{names}

Relation types:

{types}

Rules:
- Use ONLY names from the roster, copied exactly. Never invent or respell a name.
- The roster contains some entries that are not people. They take part in no relation.
- Report a relation only where the passage shows something specific between the
  two. Being present in the same scene is not a relation.
- A relation counts even if the two are never named in the same sentence.
- direction: "symétrique" if it reads the same both ways; "A→B" if A holds the
  role over B (A mentors B); "B→A" for the converse.
- evidence: one short verbatim quote, under 200 characters.
- A passage evidencing no relation gets an empty list.

Passage (chapter: {passage['title']}):

{passage['text']}

Reply with ONLY a JSON object, no prose and no code fence:

{{"relations": [{{"entity_a": "...", "entity_b": "...", "relationship_type": "...", "direction": "symétrique" | "A→B" | "B→A", "evidence": "..."}}]}}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--roster", default="roster_oracle.json")
    ap.add_argument("--explicit-pairs", default="explicit_pairs_oracle.json")
    ap.add_argument("--model", default="claude-sonnet-5")
    ap.add_argument("--chunk-chars", type=int, default=DEFAULT_CHUNK_CHARS)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default="predictions.llm_schema.json")
    args = ap.parse_args()

    with open(args.corpus, encoding="utf-8") as f:
        corpus = [json.loads(line) for line in f if line.strip()]
    with open(args.roster, encoding="utf-8") as f:
        roster = json.load(f)
    with open(args.explicit_pairs, encoding="utf-8") as f:
        explicit = {(p["entity_a"], p["entity_b"]) for p in json.load(f)}
    names = [r["canonical_name"] for r in roster]

    passages = [c for chapter in corpus for c in chunks_of(chapter, args.chunk_chars)]
    done, lock = [0], threading.Lock()

    def run(passage: dict) -> dict:
        try:
            payload = complete_json(prompt_for(names, passage), model=args.model)
            kept, _ = valid_relations(payload.get("relations"), set(names))
        except Exception as e:  # one bad passage must not lose the run
            print(f"  [{passage['id']}] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            kept = []
        with lock:
            done[0] += 1
            print(f"  [{done[0]}/{len(passages)}] {passage['id']}: {len(kept)}", file=sys.stderr)
        return {"chapter_id": passage["chapter_id"], "relations": kept, "malformed": []}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        votes = list(pool.map(run, passages))

    # Same fold as the gold: a book-level pair is what the benchmark scores, and
    # aggregating the arm differently from the gold would score the fold.
    pairs, rejected = aggregate(votes, roster, explicit)
    predictions = [
        {"entity_a": p["entity_a"], "entity_b": p["entity_b"],
         "relationship_type": p["acceptable"][0], "direction": p["direction"],
         "chapters": p["chapters"], "evidence": p["evidence"]}
        for p in pairs
    ]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(predictions, f, ensure_ascii=False, indent=2)
    print(f"\n{len(passages)} passages -> {len(predictions)} pairs -> {args.out}", file=sys.stderr)
    print(f"votes naming an entity off-roster (dropped): {len(rejected)}", file=sys.stderr)


if __name__ == "__main__":
    main()
