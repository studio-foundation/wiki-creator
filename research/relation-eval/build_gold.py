#!/usr/bin/env python3
"""Annotate the corpus chapter by chapter, then aggregate to book-level gold.

Why per chapter and not per book: no annotator, model or human, holds a 60-chapter
novel in view well enough to enumerate its relations in one pass. Chapters are the
largest unit an annotator reads exhaustively. Aggregation is `aggregate.py`, which
is pure and tested; this file only owns the API call.

The annotator names entities from the frozen roster and nothing else. Free-naming
would fold entity resolution back into a relation benchmark: an arm would lose
points because the gold called him "Garrow" and it called him "Uncle Garrow".

The annotator is NOT asked whether a relation is implicit. That is a property of
the text — do these two surfaces ever share a sentence — so `aggregate.py` computes
it. Asking the model would make the benchmark's central axis a model judgment, and
one no arm could be checked against.

Runs through the Claude Code CLI, which has no schema enforcement, so every field
the schema used to guarantee is checked here instead. A vote that fails validation
is dropped and counted, never repaired: a gold quietly patched by its own builder
is not a reference.

Usage (from research/relation-eval/):
    python build_gold.py --corpus corpus.jsonl --roster roster.json --out gold.yaml
"""
import argparse
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from aggregate import SYMMETRIC, aggregate  # noqa: E402
from claude_cli import DEFAULT_MODEL, complete_json  # noqa: E402
from wiki_creator.page_templates import relationship_tokens  # noqa: E402
from wiki_creator.page_templates import relationship_definitions  # noqa: E402

DIRECTIONS = (SYMMETRIC, "A→B", "B→A")


def prompt_for(roster_names: list[str]) -> str:
    types = "\n".join(f"- {d['name']}: {d['description']}" for d in relationship_definitions())
    names = "\n".join(f"- {n}" for n in roster_names)
    return f"""You are building the reference set for a relation-extraction benchmark on a
fantasy novel. You are reading ONE chapter. Accuracy matters more than coverage.

List every interpersonal relation this chapter gives evidence for, between two
entities from this roster:

{names}

Relation types:

{types}

Rules:
- Use ONLY names from the roster above, copied exactly. Never invent a name, never
  use a variant spelling, never use a name the roster does not list.
- The roster is imperfect: it contains some entries that are not people (a valley,
  a kingdom). Do not invent an interpersonal relation for them. If a roster entry
  is not a person, it takes part in no relation.
- Report a relation if THIS chapter gives evidence for it, whether stated outright
  ("his uncle Garrow") or shown through what the two do and say. A relation the
  chapter merely permits, and does not evidence, is not a relation.
- Two characters being present in the same scene is NOT a relation. A crowd, a
  battle, or a council puts many names together and relates none of them. Report a
  relation only where the chapter shows something specific between the two.
- A relation counts even if the two are never named in the same sentence — a
  character discussed in absence ("my father", "the man who killed her") relates
  just as truly as one in the room.
- direction: "symétrique" if the relation reads the same both ways (friend, family
  of equals); "A→B" if A holds the role over B (A mentors B, A employs B); "B→A"
  for the converse. A is entity_a, B is entity_b, exactly as you name them.
- evidence: one short verbatim quote from the chapter, under 200 characters.
- A chapter evidencing no relation gets an empty list.

Reply with ONLY a JSON object, no prose and no code fence:

{{"relations": [{{"entity_a": "...", "entity_b": "...", "relationship_type": "<one of the types above>", "direction": "symétrique" | "A→B" | "B→A", "evidence": "..."}}]}}
"""


def valid_relations(raw, roster_names: set[str]) -> tuple[list[dict], list[str]]:
    """Split a chapter's relations into (well-formed, rejected-with-reason).

    The CLI enforces no schema, so everything the old json_schema guaranteed is
    checked here. Names are checked by `aggregate`, which owns the roster rule for
    every caller; this only rejects what would crash or silently mistype the fold.
    """
    types = set(relationship_tokens())
    kept, rejected = [], []
    if not isinstance(raw, list):
        return [], [f"relations is {type(raw).__name__}, not a list"]

    for rel in raw:
        if not isinstance(rel, dict):
            rejected.append(f"relation is {type(rel).__name__}, not an object")
            continue
        missing = [k for k in ("entity_a", "entity_b", "relationship_type", "direction")
                   if not isinstance(rel.get(k), str) or not rel[k].strip()]
        if missing:
            rejected.append(f"missing/blank {missing}")
            continue
        if rel["relationship_type"] not in types:
            rejected.append(f"type off-vocabulary: {rel['relationship_type']!r}")
            continue
        if rel["direction"] not in DIRECTIONS:
            rejected.append(f"direction off-vocabulary: {rel['direction']!r}")
            continue
        kept.append({
            "entity_a": rel["entity_a"].strip(),
            "entity_b": rel["entity_b"].strip(),
            "relationship_type": rel["relationship_type"],
            "direction": rel["direction"],
            "evidence": (rel.get("evidence") or "").strip()[:200],
        })
    return kept, rejected


def annotate(chapter: dict, roster_names: list[str], model: str) -> dict:
    payload = complete_json(
        f"{prompt_for(roster_names)}\nChapter: {chapter['title']}\n\n{chapter['text']}",
        model=model,
    )
    kept, rejected = valid_relations(payload.get("relations"), set(roster_names))
    return {"chapter_id": chapter["id"], "relations": kept, "malformed": rejected}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--roster", default="roster.json")
    ap.add_argument("--explicit-pairs", default="explicit_pairs.json")
    ap.add_argument("--out", default="gold.yaml")
    ap.add_argument("--votes-out", default="gold_votes.json")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    with open(args.corpus, encoding="utf-8") as f:
        corpus = [json.loads(line) for line in f if line.strip()]
    with open(args.roster, encoding="utf-8") as f:
        roster = json.load(f)
    with open(args.explicit_pairs, encoding="utf-8") as f:
        explicit = {(p["entity_a"], p["entity_b"]) for p in json.load(f)}
    roster_names = [r["canonical_name"] for r in roster]

    done = [0]
    lock = threading.Lock()

    def run(chapter: dict) -> dict:
        record = annotate(chapter, roster_names, args.model)
        with lock:
            done[0] += 1
            bad = f", {len(record['malformed'])} malformed" if record["malformed"] else ""
            print(f"  [{done[0]}/{len(corpus)}] {chapter['id']}: "
                  f"{len(record['relations'])} relations{bad}", file=sys.stderr)
        return record

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        votes = list(pool.map(run, corpus))

    with open(args.votes_out, "w", encoding="utf-8") as f:
        json.dump(votes, f, ensure_ascii=False, indent=2)

    pairs, rejected = aggregate(votes, roster, explicit)
    with open(args.out, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            {"book": "eragon", "tome": "01", "pairs": pairs},
            f, allow_unicode=True, sort_keys=False,
        )

    implicit = sum(1 for p in pairs if p["implicit"])
    malformed = [m for v in votes for m in v["malformed"]]
    print(f"\n{len(votes)} chapters, {sum(len(v['relations']) for v in votes)} chapter-level votes")
    print(f"-> {len(pairs)} book-level gold pairs ({implicit} implicit) -> {args.out}")
    print(f"votes dropped as malformed: {len(malformed)} {malformed[:5]}")
    print(f"votes naming an entity outside the roster (dropped): {len(rejected)}")
    if rejected:
        print(f"  {rejected[:10]}")


if __name__ == "__main__":
    main()
