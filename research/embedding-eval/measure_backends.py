"""STU-577 spike: is the *backend* what fails, not the representation?

STU-468 and STU-490 both tested representation shape (sentence context, mention
window, mean-removal) on one backend, `intfloat/multilingual-e5-small`, and both
came back negative: every English prose passage of one book sits at ~0.9 cosine
whoever is named. This script keeps the fixture, the pairs and the metric fixed
and sweeps the **backend** axis instead.

Two families:
  - bi-encoder : centroid per entity, cosine between centroids (the STU-468 shape)
  - cross      : a reranker scores each (context_a, context_b) pair directly and
                 the pair score is aggregated (mean / max) — no centroid, so the
                 topic direction is not baked into a single vector

Representation is pinned to the two arms STU-490 measured as extremes: `full`
(whole context) and `win±15` (its best margin). Mean-removal is dropped — STU-490
measured it unusable on every window.

Metric is STU-490's, unchanged: margin = min(score over `same`) - max(score over
`different`); positive => one threshold separates. AUROC = fraction of
(same, different) pairs correctly ordered. Scores are not comparable in scale
across families; margin sign and AUROC are.

Usage (downloads ~9 GB of models on first run):
    PYTHONPATH=$(pwd) python research/embedding-eval/measure_backends.py
    PYTHONPATH=$(pwd) python research/embedding-eval/measure_backends.py --only e5-large
Requires the `embeddings` extra (`pip install -e '.[embeddings]'`).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

from wiki_creator.embedding_disambiguation import cosine, _mean_pool_normalize

from measure import window  # same directory; run with PYTHONPATH=$(pwd)

FIXTURE = Path("tests/fixtures/embedding_golden_pairs.json")
WINDOWS = [None, 15]

# An instruction-tuned model is only worth testing if the instruction names the
# task; a generic "represent this passage" reproduces the plain model.
E5_INSTRUCT_TASK = (
    "Given a passage of a novel, represent which character it is about, "
    "ignoring the scene, setting and narrative style"
)

BI_ENCODERS = {
    "e5-small": ("intfloat/multilingual-e5-small", "passage: "),
    "e5-base": ("intfloat/multilingual-e5-base", "passage: "),
    "e5-large": ("intfloat/multilingual-e5-large", "passage: "),
    "e5-large-instruct": (
        "intfloat/multilingual-e5-large-instruct",
        f"Instruct: {E5_INSTRUCT_TASK}\nQuery: ",
    ),
    "bge-m3": ("BAAI/bge-m3", ""),
    "gte-multilingual": ("Alibaba-NLP/gte-multilingual-base", ""),
}

CROSS_ENCODERS = {
    "bge-reranker-v2-m3": "BAAI/bge-reranker-v2-m3",
    "ms-marco-MiniLM": "cross-encoder/ms-marco-MiniLM-L-6-v2",
}


DEVICE = os.environ.get("WIKI_EMBEDDING_DEVICE", "cuda")


def load_bi(model_name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(model_name, device=DEVICE, trust_remote_code=True)


def load_cross(model_name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, device=DEVICE, trust_remote_code=True)


def release() -> None:
    """Call after `del model`: dropping the ref alone leaves the weights on a
    6 GB GPU until the allocator feels like it, and the next model then OOMs."""
    import gc

    import torch

    gc.collect()
    torch.cuda.empty_cache()


def bi_scores(model, prefix, entities, pairs, k) -> dict:
    flat, spans = [], {}
    for name, ctxs in entities.items():
        start = len(flat)
        flat.extend(prefix + window(name, c, k) for c in ctxs)
        spans[name] = (start, len(flat))
    vecs = model.encode(flat, normalize_embeddings=True, convert_to_numpy=True)
    cen = {n: _mean_pool_normalize(vecs[s:e]) for n, (s, e) in spans.items()}
    return {(p["a"], p["b"]): cosine(cen[p["a"]], cen[p["b"]]) for p in pairs}


def cross_scores(model, entities, pairs, k, agg) -> dict:
    out = {}
    for p in pairs:
        a = [window(p["a"], c, k) for c in entities[p["a"]]]
        b = [window(p["b"], c, k) for c in entities[p["b"]]]
        grid = [(x, y) for x in a for y in b]
        s = np.asarray(model.predict(grid), dtype=float)
        out[(p["a"], p["b"])] = float(s.mean() if agg == "mean" else s.max())
    return out


def report(label, pairs, scores, table):
    same = [scores[(p["a"], p["b"])] for p in pairs if p["label"] == "same"]
    diff = [(scores[(p["a"], p["b"])], f'{p["a"]}/{p["b"]}') for p in pairs if p["label"] != "same"]
    top_diff, top_name = max(diff)
    margin = min(same) - top_diff
    auroc = sum(s > d for s in same for d, _ in diff) / (len(same) * len(diff))
    sep = "YES" if margin > 0 else "no"
    print(
        f"{label:28s}  {margin:+.3f}   {min(same):+.3f}     {top_diff:+.3f}     "
        f"{auroc:.2f}   {sep:3s}  {top_name}"
    )
    table.append((label, margin, min(same), top_diff, auroc, sep, top_name))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="backend keys to run (default: all)")
    args = ap.parse_args()

    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    entities, pairs = spec["entities"], spec["pairs"]
    wanted = set(args.only) if args.only else None

    print(f"{'arm':28s}  margin   min(same)  max(diff)  auroc  sep  top `different` pair")
    table = []
    for key, (model_name, prefix) in BI_ENCODERS.items():
        if wanted and key not in wanted:
            continue
        model = load_bi(model_name)
        for k in WINDOWS:
            arm = f"{key}/" + ("full" if k is None else f"win±{k}")
            report(arm, pairs, bi_scores(model, prefix, entities, pairs, k), table)
        del model
        release()

    for key, model_name in CROSS_ENCODERS.items():
        if wanted and key not in wanted:
            continue
        model = load_cross(model_name)
        for k in WINDOWS:
            for agg in ("mean", "max"):
                arm = f"{key}/" + ("full" if k is None else f"win±{k}") + f"/{agg}"
                report(arm, pairs, cross_scores(model, entities, pairs, k, agg), table)
        del model
        release()

    if table:
        best = max(table, key=lambda r: r[1])
        print(f"\nbest arm by margin: {best[0]}  (margin {best[1]:+.3f}, auroc {best[4]:.2f})")


if __name__ == "__main__":
    main()
