#!/usr/bin/env python3
"""Annotate the eval corpus with an LLM to produce gold.jsonl.

The annotator names entity *surfaces*; offsets are computed here. Asking a model
for character offsets is its own failure mode — scripts/ner_dataset_generation.py
had to validate `text[start:end] == ent_text` and drop whole chunks when the
arithmetic drifted. Surfaces are a thing the model is reliably good at.

Consequence: an entity surface is gold at every occurrence in the chunk, so a
word that is a name in one sentence and a common noun in the next is annotated
as a name in both. Accepted: it is per-mention recall we are measuring, and the
alternative failure mode is worse.

Usage (from research/ner-eval/, needs an API key):
    python build_gold.py --corpus corpus.jsonl --out gold.jsonl
"""
import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import anthropic
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from wiki_creator.entity_taxonomy import ner_types  # noqa: E402

MODEL = "claude-opus-4-8"
LABELS = list(ner_types())

PROMPT = f"""You are annotating named entities in a passage of fantasy fiction, to
build the reference set for a NER benchmark. Accuracy matters more than coverage
of edge cases.

Valid types: {", ".join(LABELS)}

Rules:
- List each distinct entity SURFACE exactly once, spelled exactly as it appears
  in the passage. Do not list character offsets.
- Copy the surface verbatim, including capitalisation and internal punctuation.
  It must appear literally in the passage.
- Do not annotate pronouns, determiners, or the leading article ("the Varden" ->
  "Varden").
- FACTION = a people, order, race, or informal group (the Varden, Urgals, Riders).
- ORG = a formal body: a kingdom, an army, an institution (the Empire).
- EVENT = a named or clearly-delimited happening (the Battle of Farthen Dur).
- Annotate what the passage shows. Do not add entities from your own knowledge of
  the book that this passage does not name.
- A passage with no named entities gets an empty list.

Passage:
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "label": {"type": "string", "enum": LABELS},
                },
                "required": ["text", "label"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["entities"],
    "additionalProperties": False,
}


def spans_for(text: str, entities: list[dict]) -> tuple[list[dict], list[str]]:
    """Expand annotated surfaces to every occurrence. Returns (spans, unfound)."""
    spans, unfound = [], []
    for ent in entities:
        surface = ent["text"].strip()
        if not surface:
            continue
        hits = list(re.finditer(rf"(?<!\w){re.escape(surface)}(?!\w)", text))
        if not hits:
            unfound.append(surface)
            continue
        spans.extend(
            {"start": m.start(), "end": m.end(), "label": ent["label"]} for m in hits
        )
    spans.sort(key=lambda s: (s["start"], s["end"]))
    return spans, unfound


def annotate(client: anthropic.Anthropic, case: dict) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        thinking={"type": "adaptive"},
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": PROMPT + case["text"]}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"{case['id']}: refused")
    raw = next(b.text for b in response.content if b.type == "text")
    spans, unfound = spans_for(case["text"], json.loads(raw)["entities"])
    return {"id": case["id"], "text": case["text"], "spans": spans, "unfound": unfound}


def api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".studio", "config.yaml",
    )
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["providers"]["anthropic"]["apiKey"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--out", default="gold.jsonl")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    with open(args.corpus, encoding="utf-8") as f:
        corpus = [json.loads(line) for line in f if line.strip()]

    client = anthropic.Anthropic(api_key=api_key())
    done = [0]
    lock = threading.Lock()

    def run(case: dict) -> dict:
        record = annotate(client, case)
        with lock:
            done[0] += 1
            print(f"  [{done[0]}/{len(corpus)}] {case['id']}: {len(record['spans'])} spans",
                  file=sys.stderr)
        return record

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(run, corpus))

    with open(args.out, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    counts: dict[str, int] = {}
    for r in records:
        for s in r["spans"]:
            counts[s["label"]] = counts.get(s["label"], 0) + 1
    unfound = [s for r in records for s in r["unfound"]]

    print(f"\n{len(records)} cases, {sum(counts.values())} gold spans -> {args.out}")
    print(f"per type: {dict(sorted(counts.items(), key=lambda kv: -kv[1]))}")
    print(f"surfaces the annotator invented (not found in the passage): {len(unfound)}")
    if unfound:
        print(f"  {unfound[:10]}")


if __name__ == "__main__":
    main()
