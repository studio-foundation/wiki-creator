"""STU-576: the eval protocol — how a same/different pair is built and scored.

Separate from `train_head.py` because none of this needs torch: the protocol is
what decides whether a number means anything, so it must stay testable on a
machine (and a CI runner) that cannot train.
"""
from __future__ import annotations

import itertools

import numpy as np

MASK = "[NAME]"


def mask_name(name: str, context: str) -> str:
    """Blank the mention. Leaving the name in makes the task string-matching."""
    low, target = context.lower(), name.lower()
    i = low.find(target)
    if i >= 0:
        return context[:i] + MASK + context[i + len(name):]
    for token in sorted(name.split(), key=len, reverse=True):
        if len(token) <= 3:
            continue
        i = low.find(token.lower())
        if i >= 0:
            return context[:i] + MASK + context[i + len(token):]
    return context


def normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1, norms)


def half_centroids(vectors, labels, chapters) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Two centroids per entity, from disjoint chapters.

    A `same` pair drawn from one chapter would measure scene identity, not
    person identity. An entity confined to a single chapter yields no pair.
    """
    by_entity: dict[str, dict[str, list[int]]] = {}
    for i, (entity, chapter) in enumerate(zip(labels, chapters)):
        by_entity.setdefault(entity, {}).setdefault(chapter, []).append(i)
    out = {}
    for entity, by_chapter in by_entity.items():
        keys = sorted(by_chapter)
        if len(keys) < 2:
            continue
        half = len(keys) // 2
        left = [i for k in keys[:half] for i in by_chapter[k]]
        right = [i for k in keys[half:] for i in by_chapter[k]]
        out[entity] = (
            normalize(vectors[left].mean(axis=0)),
            normalize(vectors[right].mean(axis=0)),
        )
    return out


def score(centroids: dict[str, tuple[np.ndarray, np.ndarray]]) -> tuple[float, float, int, int]:
    """(margin, auroc, n_same, n_diff). margin > 0 ⇒ one threshold separates."""
    same = [float(a @ b) for a, b in centroids.values()]
    diff = [
        float(centroids[x][0] @ centroids[y][1])
        for x, y in itertools.permutations(centroids, 2)
    ]
    sorted_diff = np.sort(diff)
    wins = sum(int(np.searchsorted(sorted_diff, s, side="left")) for s in same)
    return min(same) - max(diff), wins / (len(same) * len(diff)), len(same), len(diff)
