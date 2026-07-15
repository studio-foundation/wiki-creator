#!/usr/bin/env python3
"""Joint label sweep for GLiNER, by coordinate ascent on macro typing F1.

STU-470's sweep (`runners/run_gliner.py`) asked each candidate label *alone* and
scored it on detection recall for its own type. That cannot see the thing that
decides the deployed score: at inference all labels are asked together and they
compete for the same spans. `person` and `people, race, or order` both want
"the Urgals"; `location` and `formal organization or kingdom` both want
"Carvahall". A label that wins alone can lose spans to a sibling when asked
alongside it — which is the most likely reason FACTION (0.726) and ORG (0.792)
are the weakest typing rows despite winning their isolated sweeps.

So: every candidate is scored in a full run, with the other types' current labels
present, on typing F1 (span found AND typed correctly) rather than detection.

Coordinate ascent instead of the full grid: the grid is
3*3*|ORG|*|FACTION|*3 runs (~5.5h at 17.5s each). Ascent revisits each type in
turn until a full round changes nothing — the interactions that matter here are
pairwise and few, and it converges in 2-3 rounds (~6 min each).

Selection metric is macro F1 over MEASURED_TYPES, not micro: PERSON is 74% of the
gold spans, so micro F1 would let a label that helps PERSON by a point wash out a
FACTION regression of ten. EVENT is excluded — n=2 is noise, per STU-470.

Usage (from research/ner-eval/):
    python sweep_labels.py --labels gliner_labels.yaml --out gliner_labels_selected.json
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
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "runners"))

from corpus_io import read_corpus  # noqa: E402
from mapping import map_gliner  # noqa: E402
from score import gold_support, load_jsonl, score  # noqa: E402

THRESHOLD = 0.5

# EVENT has n=2 gold spans in 182k chars; any EVENT number is noise, and tuning
# against it would be fitting the sweep to two sentences (STU-470).
MEASURED_TYPES = ("PERSON", "FACTION", "PLACE", "ORG")


def predict(model, corpus: list[dict], label_to_type: dict[str, str]) -> dict:
    labels = list(label_to_type)
    out = {}
    for case in corpus:
        ents = model.predict_entities(case["text"], labels, threshold=THRESHOLD)
        out[case["id"]] = {"id": case["id"], "spans": map_gliner(ents, label_to_type)}
    return out


def evaluate(model, corpus: list[dict], gold: dict, assignment: dict[str, str],
             cache: dict) -> dict:
    """Full run with every type's current label asked together."""
    key = tuple(sorted(assignment.items()))
    if key in cache:
        return cache[key]

    label_to_type = {label: t for t, label in assignment.items()}
    if len(label_to_type) != len(assignment):
        raise SystemExit(f"two types share a label, cannot map back: {assignment}")

    scores = score(gold, predict(model, corpus, label_to_type))
    per_type = scores["typing_overlap"]["per_type"]
    result = {
        "macro": round(
            sum(per_type.get(t, {}).get("f1", 0.0) for t in MEASURED_TYPES)
            / len(MEASURED_TYPES), 4),
        "micro": scores["typing_overlap"]["global"]["f1"],
        "per_type": {t: per_type.get(t, {}).get("f1", 0.0) for t in MEASURED_TYPES},
    }
    cache[key] = result
    return result


def ascend(model, corpus, gold, candidates, start, max_rounds) -> tuple[dict, list]:
    cache: dict = {}
    current = dict(start)
    best = evaluate(model, corpus, gold, current, cache)
    print(f"start  macro={best['macro']} micro={best['micro']} {current}\n")
    trace = [{"round": 0, "assignment": dict(current), **best}]

    for rnd in range(1, max_rounds + 1):
        improved = False
        for entity_type in candidates:
            if entity_type not in MEASURED_TYPES:
                continue
            for label in candidates[entity_type]:
                if label == current[entity_type]:
                    continue
                trial = {**current, entity_type: label}
                if len(set(trial.values())) != len(trial):
                    continue  # label already taken by another type
                got = evaluate(model, corpus, gold, trial, cache)
                mark = ""
                if got["macro"] > best["macro"]:
                    current, best, improved, mark = trial, got, True, "  <- take"
                print(f"  r{rnd} {entity_type:8} {label!r:38} "
                      f"macro={got['macro']} micro={got['micro']} "
                      f"{entity_type}_f1={got['per_type'][entity_type]}{mark}")
            trace.append({"round": rnd, "assignment": dict(current), **best})
        print(f"\nround {rnd}: macro={best['macro']} {current}\n")
        if not improved:
            print(f"converged after round {rnd}\n")
            break

    return current, trace


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="urchade/gliner_large-v2.1")
    ap.add_argument("--corpus", default="corpus.jsonl")
    ap.add_argument("--gold", default="gold.jsonl")
    ap.add_argument("--labels", default="gliner_labels.yaml")
    ap.add_argument("--out", default="gliner_labels_selected.json")
    ap.add_argument("--max-rounds", type=int, default=4)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = GLiNER.from_pretrained(args.model).to(device)

    corpus = read_corpus(args.corpus)
    gold = load_jsonl(args.gold)
    with open(args.labels, encoding="utf-8") as f:
        candidates = yaml.safe_load(f)

    print(f"{args.model} on {device} | {len(corpus)} chunks | gold {gold_support(gold)}\n")

    start = {t: labels[0] for t, labels in candidates.items()}
    started = time.perf_counter()
    winners, trace = ascend(model, corpus, gold, candidates, start, args.max_rounds)
    elapsed = time.perf_counter() - started

    final = evaluate(model, corpus, gold, winners, {})
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"selected": winners, "scores": final, "trace": trace}, f, indent=1)
    print(f"selected {winners}\nmacro={final['macro']} micro={final['micro']} "
          f"per_type={final['per_type']}\nsweep took {elapsed / 60:.1f} min -> {args.out}")


if __name__ == "__main__":
    main()
