# tests/test_embedding_disambiguation.py
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
