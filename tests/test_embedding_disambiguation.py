# tests/test_embedding_disambiguation.py
import json
from pathlib import Path

import numpy as np
import pytest

from wiki_creator.embedding_disambiguation import (
    Verdict,
    cosine,
    entity_centroid,
    EmbeddingJudge,
    DEFAULT_PROPOSE_THRESHOLD,
    DEFAULT_VETO_THRESHOLD,
)


class FakeBackend:
    """Maps each exact context string to a fixed unit vector."""
    def __init__(self, table):
        self.table = table  # str -> list[float]
    def encode(self, texts):
        rows = []
        for t in texts:
            vec = np.asarray(self.table[t], dtype=np.float32)
            vec = vec / (np.linalg.norm(vec) or 1.0)
            rows.append(vec)
        return np.vstack(rows) if rows else np.zeros((0, 3), dtype=np.float32)


def test_cosine_identical_is_one():
    v = np.array([1.0, 2.0, 3.0])
    assert cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert cosine(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(0.0)


def test_entity_centroid_none_on_empty():
    assert entity_centroid([], FakeBackend({})) is None


def test_entity_centroid_mean_pooled_and_normalized():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    c = entity_centroid(["a", "b"], backend)
    assert c is not None
    assert np.linalg.norm(c) == pytest.approx(1.0)          # normalized
    assert c[0] == pytest.approx(c[1])                       # symmetric mean


def test_build_centroids_single_batch_and_none_keys():
    backend = FakeBackend({"x": [1.0, 0.0, 0.0], "y": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, DEFAULT_PROPOSE_THRESHOLD, DEFAULT_VETO_THRESHOLD)
    centroids = judge.build_centroids({0: ["x", "y"], 1: []})
    assert centroids[1] is None
    assert np.linalg.norm(centroids[0]) == pytest.approx(1.0)


def test_propose_merges_above_threshold():
    backend = FakeBackend({"same1": [1.0, 0.0, 0.0], "same2": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["same1"], 1: ["same2"]})
    v = judge.propose(0, 1, centroids)
    assert isinstance(v, Verdict)
    assert v.decision == "merge"
    assert v.method == "embedding_disambiguation"


def test_propose_abstains_below_threshold():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: ["b"]})
    assert judge.propose(0, 1, centroids).decision == "abstain"


def test_propose_abstains_when_centroid_missing():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: []})
    assert judge.propose(0, 1, centroids).decision == "abstain"


def test_veto_blocks_dissimilar():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: ["b"]})
    assert judge.veto(0, 1, centroids) is True


def test_veto_allows_similar():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0], "b": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: ["b"]})
    assert judge.veto(0, 1, centroids) is False


def test_veto_false_when_centroid_missing():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: []})
    assert judge.veto(0, 1, centroids) is False


# tests/test_embedding_disambiguation.py  (append)
from wiki_creator.embedding_disambiguation import EmbeddingBackend
from tests._markers import requires_embeddings


def test_resolve_device_honors_explicit():
    # Constructing the model is heavy; test resolve_device without __init__.
    assert EmbeddingBackend.resolve_device(object.__new__(EmbeddingBackend), "cpu") == "cpu"


@requires_embeddings
def test_backend_encodes_normalized_vectors():
    backend = EmbeddingBackend(device="cpu")
    vecs = backend.encode(["Celaena drew her blade.", "The assassin moved silently."])
    assert vecs.shape[0] == 2
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)


@requires_embeddings
def test_backend_empty_returns_empty():
    backend = EmbeddingBackend(device="cpu")
    vecs = backend.encode([])
    assert vecs.shape[0] == 0


# --- Golden-pairs eval (STU-468) ---------------------------------------------
# The self-contained fixture bakes real throne-of-glass mention contexts
# (processing_output/ is gitignored). The eval FALSIFIED the centroid-cosine
# approach: on single-book data, same-person and different-person pairs are not
# separable because topic/setting dominates the sentence embedding. See
# docs/superpowers/specs/2026-07-12-embedding-disambiguation-EVAL-RESULTS.md.
# The two tests below are characterization guards, not success gates — the
# feature ships opt-in and defaults OFF. `test_golden_fixture_is_self_contained`
# runs in normal CI and locks hermeticity. `test_golden_pairs_are_not_separable`
# only runs locally under `.[embeddings]` (it needs the real model) — it is NOT
# a CI gate; treat it as a reproducible local check that documents the negative
# result, which flips if a future representation makes the pairs separable.

_FIXTURE = Path(__file__).parent / "fixtures" / "embedding_golden_pairs.json"


def _golden_scores():
    from wiki_creator.embedding_disambiguation import EmbeddingBackend, entity_centroid, cosine

    spec = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    backend = EmbeddingBackend(device="cpu")
    centroids = {name: entity_centroid(ctxs, backend) for name, ctxs in spec["entities"].items()}
    scores = []
    for pair in spec["pairs"]:
        ca, cb = centroids[pair["a"]], centroids[pair["b"]]
        scores.append((cosine(ca, cb), pair["label"]))
    return scores


def test_golden_fixture_is_self_contained():
    # Runs without the extra: every pair must reference entities that carry
    # baked contexts, so the eval never depends on the gitignored run output.
    spec = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    entities = spec["entities"]
    assert spec["pairs"], "fixture has no pairs"
    for pair in spec["pairs"]:
        assert len(entities.get(pair["a"], [])) >= 2
        assert len(entities.get(pair["b"], [])) >= 2
        assert pair["label"] in ("same", "different")


@requires_embeddings
def test_golden_pairs_are_not_separable():
    # Characterization of the negative eval result: the max different-pair
    # cosine is >= the min same-pair cosine, i.e. no threshold separates them.
    scores = _golden_scores()
    assert all(-1.0 <= s <= 1.0 for s, _ in scores)
    same = [s for s, label in scores if label == "same"]
    diff = [s for s, label in scores if label == "different"]
    assert same and diff
    assert max(diff) >= min(same), (
        "golden pairs are now separable — revisit whether embedding "
        "disambiguation should be enabled (see EVAL-RESULTS doc)"
    )
