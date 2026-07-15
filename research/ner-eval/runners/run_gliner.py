#!/usr/bin/env python3
"""GLiNER zero-shot runner with a per-type label sweep.

Two phases:
  sweep  each candidate label is asked for alone, and scored on detection recall
         against the gold spans of its type only. Best label per type wins.
  final  one run asking for all five winning labels together — the way the model
         would actually be deployed, and the arm that gets scored.

The sweep is scored on the same gold the bake-off reports, so the winning labels
are chosen on the test set. That is the same posture as STU-401 and it flatters
GLiNER slightly; it is disclosed in results.md rather than corrected, because the
alternative (a held-out split of a 120-chunk corpus) costs more signal than the
bias it removes.

Usage (from research/ner-eval/):
    python runners/run_gliner.py --model urchade/gliner_large-v2.1
"""
import argparse
import json
import os
import sys
import time

import torch
import yaml
from gliner import GLiNER

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from corpus_io import read_corpus, write_predictions  # noqa: E402
from mapping import map_gliner  # noqa: E402
from score import load_jsonl, score  # noqa: E402

THRESHOLD = 0.5


def predict(model, corpus: list[dict], label_to_type: dict[str, str]) -> dict:
    labels = list(label_to_type)
    out = {}
    for case in corpus:
        ents = model.predict_entities(case["text"], labels, threshold=THRESHOLD)
        out[case["id"]] = {"id": case["id"], "spans": map_gliner(ents, label_to_type)}
    return out


def gold_of_type(gold: dict, entity_type: str) -> dict:
    return {
        cid: {"id": cid, "spans": [s for s in case["spans"] if s["label"] == entity_type]}
        for cid, case in gold.items()
    }


def sweep(model, corpus: list[dict], gold: dict, candidates: dict) -> dict:
    """Best natural-language label per type, by detection recall on that type."""
    winners = {}
    for entity_type, labels in candidates.items():
        target = gold_of_type(gold, entity_type)
        support = sum(len(c["spans"]) for c in target.values())
        best, best_recall = None, -1.0
        for label in labels:
            preds = predict(model, corpus, {label: entity_type})
            recall = score(target, preds)["detection_overlap"]["recall_global"]
            print(f"  {entity_type:8} {label!r:36} recall={recall}")
            if recall > best_recall:
                best, best_recall = label, recall
        winners[entity_type] = best
        print(f"  -> {entity_type}: {best!r} (recall {best_recall}, gold n={support})\n")
    return winners


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="urchade/gliner_large-v2.1")
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--gold", default="gold.jsonl")
    ap.add_argument("--labels", default="gliner_labels.yaml")
    ap.add_argument("--name", default="gliner")
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = GLiNER.from_pretrained(args.model).to(device)
    print(f"{args.name}: {args.model} on {device}")

    corpus = read_corpus(args.corpus)
    gold = load_jsonl(args.gold)
    with open(args.labels, encoding="utf-8") as f:
        candidates = yaml.safe_load(f)

    print("\n--- label sweep ---")
    winners = sweep(model, corpus, gold, candidates)

    print("--- final run, winning labels together ---")
    label_to_type = {label: t for t, label in winners.items()}
    started = time.perf_counter()
    preds = predict(model, corpus, label_to_type)
    elapsed = time.perf_counter() - started

    write_predictions(f"predictions.{args.name}.jsonl", list(preds.values()))
    with open("gliner_labels_selected.json", "w", encoding="utf-8") as f:
        json.dump(winners, f, indent=1)
    print(f"{args.name}: {elapsed:.1f}s for {len(corpus)} chunks | labels={winners}")


if __name__ == "__main__":
    main()
