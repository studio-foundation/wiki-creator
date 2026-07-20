#!/usr/bin/env python3
"""STU-576 step 2: train a contrastive head over frozen e5-small mention windows.

STU-468/490 falsified *untrained* cosine (and mean-removal, an untrained contrastive
proxy). This is the inverse: a real discriminative objective (supervised InfoNCE over
entity labels) on a projection above the frozen backbone.

Protocol — the eval is **leave-one-book-out**, never a split of one book. Held-out
identities in held-out prose is the only question production asks; a within-book split
lets the head memorise a cast.

Each entity's windows are split into two halves **by chapter**, giving two centroids
of one person from disjoint scenes. That is the fixture's shape (two surface clusters
of one character) built at scale, and it is what makes a `same` pair exist at all:
one entity id yields one centroid.

    margin = min(cosine over same) - max(cosine over different)   # >0 separates
    auroc  = fraction of (same, different) pairs correctly ordered

Arms: `raw` (frozen backbone, no head — the STU-468 baseline under this protocol) and
`head` (trained). Both are also scored on the committed 8-pair fixture, masked the
same way, which is the acceptance criterion the issue names.

    PYTHONPATH=$(pwd) python research/embedding-eval/train_head.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

from pairs import half_centroids, mask_name, normalize, score
from wiki_creator.embedding_disambiguation import EmbeddingBackend

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
CACHE = HERE / "corpus" / "encoded"
FIXTURE = Path("tests/fixtures/embedding_golden_pairs.json")
PROJECTION_DIM = 128
EPOCHS = 120
BATCH = 256
TEMPERATURE = 0.07
SEEDS = (0, 1, 2)


def encode_book(slug: str, backend: EmbeddingBackend) -> tuple[np.ndarray, list[str], list[str]]:
    """(vectors, entity id per window, chapter id per window), cached on disk."""
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{slug}.npz"
    rows = json.loads((CORPUS / f"{slug}.json").read_text(encoding="utf-8"))
    labels = [r["entity"] for r in rows for _ in r["windows"]]
    chapters = [w["chapter"] for r in rows for w in r["windows"]]
    if cached.exists():
        return np.load(cached)["vectors"], labels, chapters
    vectors = backend.encode([w["text"] for r in rows for w in r["windows"]])
    np.savez_compressed(cached, vectors=vectors)
    return vectors, labels, chapters


class Head(nn.Module):
    def __init__(self, dim: int):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(dim, dim), nn.ReLU(), nn.Linear(dim, PROJECTION_DIM))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return F.normalize(self.net(x), dim=-1)


def supcon(z: torch.Tensor, labels: torch.Tensor) -> torch.Tensor:
    """Supervised InfoNCE: every same-entity window in the batch is a positive."""
    sim = z @ z.T / TEMPERATURE
    eye = torch.eye(len(z), dtype=torch.bool, device=z.device)
    sim = sim.masked_fill(eye, float("-inf"))
    positive = (labels[:, None] == labels[None, :]) & ~eye
    log_prob = sim - torch.logsumexp(sim, dim=1, keepdim=True)
    counts = positive.sum(1)
    usable = counts > 0
    if not usable.any():
        return torch.zeros((), device=z.device, requires_grad=True)
    # masked_fill, not a multiply: the -inf self-similarity times a 0 mask is NaN.
    summed = log_prob.masked_fill(~positive, 0.0).sum(1)
    return -(summed[usable] / counts[usable]).mean()


def train(vectors: np.ndarray, labels: list[str], device: str, seed: int) -> tuple[Head, float]:
    torch.manual_seed(seed)
    x = torch.tensor(vectors, dtype=torch.float32, device=device)
    index = {name: i for i, name in enumerate(sorted(set(labels)))}
    y = torch.tensor([index[name] for name in labels], device=device)
    head = Head(x.shape[1]).to(device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    final = 0.0
    for _ in range(EPOCHS):
        order = torch.randperm(len(x), generator=generator).to(device)
        total, batches = 0.0, 0
        for start in range(0, len(order), BATCH):
            batch = order[start:start + BATCH]
            loss = supcon(head(x[batch]), y[batch])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += float(loss.detach())
            batches += 1
        final = total / max(1, batches)
    return head, final


def apply_head(head: Head | None, vectors: np.ndarray, device: str) -> np.ndarray:
    if head is None:
        return vectors
    with torch.no_grad():
        return head(torch.tensor(vectors, dtype=torch.float32, device=device)).cpu().numpy()


def fixture_arm(head: Head | None, backend: EmbeddingBackend, device: str) -> tuple[float, float]:
    """The issue's acceptance criterion: the committed 8 pairs, name-masked."""
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    flat, spans = [], {}
    for name, contexts in spec["entities"].items():
        start = len(flat)
        flat.extend(mask_name(name, c) for c in contexts)
        spans[name] = (start, len(flat))
    vectors = apply_head(head, backend.encode(flat), device)
    centroids = {n: normalize(vectors[s:e].mean(axis=0)) for n, (s, e) in spans.items()}
    same, diff = [], []
    for pair in spec["pairs"]:
        value = float(centroids[pair["a"]] @ centroids[pair["b"]])
        (same if pair["label"] == "same" else diff).append(value)
    wins = sum(s > d for s in same for d in diff)
    return min(same) - max(diff), wins / (len(same) * len(diff))


def main() -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    backend = EmbeddingBackend()
    slugs = sorted(p.stem for p in CORPUS.glob("*.json"))
    books = {}
    for slug in slugs:
        vectors, labels, chapters = encode_book(slug, backend)
        if len(set(labels)) < 4:
            print(f"skip {slug}: {len(set(labels))} entities (subset cache, not a book)")
            continue
        books[slug] = (vectors, labels, chapters)

    def report(label: str, models: list[Head | None], held_out: str) -> None:
        vectors, labels, chapters = books[held_out]
        scored = [score(half_centroids(apply_head(m, vectors, device), labels, chapters)) for m in models]
        fixtures = [fixture_arm(m, backend, device) for m in models]
        margins = [s[0] for s in scored]
        aurocs = [s[1] for s in scored]
        fixture_margins = [f[0] for f in fixtures]
        n_same, n_diff = scored[0][2], scored[0][3]
        print(
            f"{label:34s} {np.mean(margins):+.3f} ±{np.std(margins):.3f}"
            f"   {np.mean(aurocs):.3f} ±{np.std(aurocs):.3f}"
            f"   {np.mean(fixture_margins):+.3f}   {n_same}/{n_diff}"
        )

    print(f"\n{'arm':34s} {'margin':16s} {'auroc':15s} {'fixture':8s} same/diff")
    for held_out in books:
        others = [s for s in books if s != held_out]
        print(f"\n-- held out: {held_out}  ({len(set(books[held_out][1]))} entities)")
        report("raw (no head)", [None], held_out)

        own_vectors, own_labels, _ = books[held_out]
        in_domain = [train(own_vectors, own_labels, device, seed)[0] for seed in SEEDS]
        report("head, in-domain (leak control)", in_domain, held_out)

        train_vectors = np.concatenate([books[s][0] for s in others])
        train_labels = [l for s in others for l in books[s][1]]
        transfer = [train(train_vectors, train_labels, device, seed)[0] for seed in SEEDS]
        report(f"head, trained on {len(set(train_labels))} held-in ids", transfer, held_out)


if __name__ == "__main__":
    main()
