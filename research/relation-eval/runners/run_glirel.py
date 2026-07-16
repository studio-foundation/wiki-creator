#!/usr/bin/env python3
"""Arm: GLiREL — zero-shot encoder relation extraction, type and direction at discovery.

The roster is handed in as NER spans, which is GLiREL's native interface: it types
relations between spans you give it and never proposes entities of its own. So the
"entities frozen across arms" rule costs this arm nothing, and its score is about
relation discovery alone.

Two things bound the number downward, and both are stated in the report rather
than tuned away:

  - The labels are guesses (glirel_labels.yaml). ner-eval learned that wording is
    load-bearing (macro F1 0.840 -> 0.866 from a sweep alone), and there is no
    sweep here. A loss is "not demonstrated", not "cannot".
  - GLiREL emits a directed head -> tail triple and has no notion of a symmetric
    relation, while most gold relations are symétrique. Direction is reported as
    A→B from head -> tail, so the direction axis measures a thing GLiREL was never
    built to express. That is a real limit of the arm for this task, not a rigged
    comparison — the pipeline needs direction, and an arm that cannot say
    "symmetric" cannot supply it.

Chapters exceed the encoder's window, so text is cut into sentence-aligned token
windows. Spans are recomputed per window: GLiREL indexes NER by token offset, so a
window that shifted them would silently type the wrong pair.

Usage:
    python runners/run_glirel.py --roster roster_oracle.json --device cuda
"""
import argparse
import json
import os
import re
import sys

import yaml

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(_HERE))))

from aggregate import aggregate  # noqa: E402

DEFAULT_MODEL = "jackboyla/glirel-large-v0"
DEFAULT_WINDOW_TOKENS = 384
DEFAULT_THRESHOLD = 0.5


def load_labels(path: str) -> tuple[list[str], dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        mapping = yaml.safe_load(f)
    return list(mapping.values()), {v: k for k, v in mapping.items()}


def windows(doc, size: int):
    """Sentence-aligned token windows, so a relation is never cut mid-clause."""
    buf: list = []
    for sent in doc.sents:
        tokens = [t for t in sent if not t.is_space]
        if buf and len(buf) + len(tokens) > size:
            yield buf
            buf = []
        buf.extend(tokens)
    if buf:
        yield buf


def spans_in(window: list, patterns: dict[str, re.Pattern]) -> list[list]:
    """[[start_tok, end_tok, canonical, surface]] — offsets are window-local."""
    text_by_tok = [t.text for t in window]
    out = []
    for i, tok in enumerate(text_by_tok):
        for canonical, pattern in patterns.items():
            if pattern.fullmatch(tok):
                out.append([i, i, canonical, tok])
                break
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--roster", default="roster_oracle.json")
    ap.add_argument("--explicit-pairs", default="explicit_pairs_oracle.json")
    ap.add_argument("--labels", default="glirel_labels.yaml")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--window-tokens", type=int, default=DEFAULT_WINDOW_TOKENS)
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--out", default="predictions.glirel.json")
    args = ap.parse_args()

    import spacy
    from glirel import GLiREL

    with open(args.corpus, encoding="utf-8") as f:
        corpus = [json.loads(line) for line in f if line.strip()]
    with open(args.roster, encoding="utf-8") as f:
        roster = json.load(f)
    with open(args.explicit_pairs, encoding="utf-8") as f:
        explicit = {(p["entity_a"], p["entity_b"]) for p in json.load(f)}

    labels, to_token = load_labels(args.labels)
    patterns = {
        e["canonical_name"]: re.compile(
            "|".join(re.escape(a) for a in sorted(set(e["aliases"]), key=len, reverse=True))
        )
        for e in roster
    }

    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    model = GLiREL.from_pretrained(args.model).to(args.device).eval()

    votes = []
    for n, chapter in enumerate(corpus, 1):
        relations = []
        doc = nlp(chapter["text"])
        for window in windows(doc, args.window_tokens):
            ner = spans_in(window, patterns)
            if len({s[2] for s in ner}) < 2:
                continue
            tokens = [t.text for t in window]
            for rel in model.predict_relations(tokens, labels, threshold=args.threshold,
                                               ner=ner, top_k=1):
                token = to_token.get(rel["label"])
                if not token:
                    continue
                head = " ".join(rel["head_text"])
                tail = " ".join(rel["tail_text"])
                a = next((s[2] for s in ner if s[3] == head), None)
                b = next((s[2] for s in ner if s[3] == tail), None)
                if not a or not b or a == b:
                    continue
                relations.append({
                    "entity_a": a, "entity_b": b, "relationship_type": token,
                    "direction": "A→B", "evidence": f"score={rel['score']:.3f}",
                })
        votes.append({"chapter_id": chapter["id"], "relations": relations, "malformed": []})
        print(f"  [{n}/{len(corpus)}] {chapter['id']}: {len(relations)} triples", file=sys.stderr)

    pairs, rejected = aggregate(votes, roster, explicit)
    predictions = [
        {"entity_a": p["entity_a"], "entity_b": p["entity_b"],
         "relationship_type": p["acceptable"][0], "direction": p["direction"],
         "chapters": p["chapters"]}
        for p in pairs
    ]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(predictions, f, ensure_ascii=False, indent=2)
    print(f"\n{sum(len(v['relations']) for v in votes)} triples -> {len(predictions)} pairs -> {args.out}",
          file=sys.stderr)
    print(f"off-roster (dropped): {len(rejected)}", file=sys.stderr)


if __name__ == "__main__":
    main()
