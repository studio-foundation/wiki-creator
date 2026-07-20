"""STU-490 spike: does a mention-window embedding separate same/different-person
pairs where the full sentence-context did not (STU-468 baseline: nul separation,
cosine band 0.906-0.949, dominated by scene topic)?

Hermetic: reuses the committed fixture `tests/fixtures/embedding_golden_pairs.json`.
Each entity's name/alias occurs verbatim in every one of its baked contexts, so a
tight window centred on the located name is sliced without needing the run's
STU-489 offsets (those matter for production wiring, not this research question).

Arms scored on the 8 golden pairs:
  - full        : STU-468 baseline (whole context, cosine)
  - window±K    : narrow char window around the name (sweeps K)
  - +meanrm     : subtract the corpus mean vector before cosine (remove the
                  dominant shared-topic direction; the cheap contrastive proxy)

Separation margin = min(cosine over `same` pairs) - max(cosine over `different`).
Positive => a single threshold cleanly separates. STU-468 margin is negative.

Usage: python research/embedding-eval/measure.py
Requires the `embeddings` extra (`pip install -e '.[embeddings]'`).
"""
import json
from pathlib import Path

import numpy as np

from backend import EmbeddingBackend, cosine, _mean_pool_normalize

FIXTURE = Path("tests/fixtures/embedding_golden_pairs.json")
WINDOWS = [None, 80, 60, 40, 25, 15]  # None = full context (baseline)


def locate(name: str, ctx: str) -> int:
    """Char index of the name (or its longest token) in the context, else -1."""
    low = ctx.lower()
    i = low.find(name.lower())
    if i >= 0:
        return i + len(name) // 2
    for tok in sorted(name.split(), key=len, reverse=True):
        if len(tok) <= 3:
            continue
        i = low.find(tok.lower())
        if i >= 0:
            return i + len(tok) // 2
    return -1


def window(name: str, ctx: str, k: int | None) -> str:
    if k is None:
        return ctx
    c = locate(name, ctx)
    if c < 0:
        return ctx
    return ctx[max(0, c - k): c + k]


def centroids(entities, k, backend, mean_removal):
    flat, spans = [], {}
    for name, ctxs in entities.items():
        start = len(flat)
        flat.extend(window(name, c, k) for c in ctxs)
        spans[name] = (start, len(flat))
    vecs = backend.encode(flat)
    if mean_removal:
        vecs = vecs - vecs.mean(axis=0, keepdims=True)
    return {n: _mean_pool_normalize(vecs[s:e]) for n, (s, e) in spans.items()}


def score_arm(entities, pairs, k, backend, mean_removal):
    cen = centroids(entities, k, backend, mean_removal)
    same, diff, rows = [], [], []
    for p in pairs:
        s = cosine(cen[p["a"]], cen[p["b"]])
        (same if p["label"] == "same" else diff).append(s)
        rows.append((s, p["label"], p["a"], p["b"]))
    margin = min(same) - max(diff)
    wins = sum(s > d for s in same for d in diff)
    auroc = wins / (len(same) * len(diff))
    return margin, min(same), max(diff), auroc, rows


def main():
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entities, pairs = spec["entities"], spec["pairs"]
    backend = EmbeddingBackend()

    print(f"{'arm':16s}  margin   min(same)  max(diff)  auroc  separates")
    best = None
    for k in WINDOWS:
        for mr in (False, True):
            label = ("full" if k is None else f"win±{k}") + ("+meanrm" if mr else "")
            margin, mn, mx, auroc, rows = score_arm(entities, pairs, k, backend, mr)
            sep = "YES" if margin > 0 else "no"
            print(f"{label:16s}  {margin:+.3f}   {mn:.3f}      {mx:.3f}      {auroc:.2f}   {sep}")
            if best is None or margin > best[0]:
                best = (margin, label, rows)

    print(f"\nbest arm by margin: {best[1]}  (margin {best[0]:+.3f})")
    print(f"\n{'cosine':7s} {'label':10s} pair  [best arm]")
    for s, lbl, a, b in sorted(best[2], reverse=True):
        print(f"{s:.3f}  {lbl:9s}  {a} / {b}")


if __name__ == "__main__":
    main()
