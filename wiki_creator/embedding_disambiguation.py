# wiki_creator/embedding_disambiguation.py
"""Semantic entity disambiguation via mention-context embeddings (STU-468).

Pure logic + a lazily-loaded sentence-transformers backend. Importing this
module pulls numpy only (always present via spaCy); sentence-transformers is
imported inside EmbeddingBackend.__init__ so the rest of the module — and its
unit tests — run without the optional `embeddings` extra.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_PROPOSE_THRESHOLD = 0.86
DEFAULT_VETO_THRESHOLD = 0.80


@dataclass(frozen=True)
class Verdict:
    decision: str  # "merge" | "abstain"
    score: float
    method: str = "embedding_disambiguation"
    confidence: str = "medium"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _mean_pool_normalize(vecs: np.ndarray) -> np.ndarray:
    centroid = vecs.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    return centroid / norm if norm else centroid


def entity_centroid(contexts: list[str], backend) -> np.ndarray | None:
    if not contexts:
        return None
    return _mean_pool_normalize(backend.encode(contexts))


def _confidence_for(score: float, propose_threshold: float) -> str:
    if score >= 0.90:
        return "high"
    if score >= propose_threshold:
        return "medium"
    return "low"


class EmbeddingJudge:
    def __init__(self, backend, propose_threshold: float, veto_threshold: float):
        self.backend = backend
        self.propose_threshold = propose_threshold
        self.veto_threshold = veto_threshold

    def build_centroids(self, contexts_by_key: dict) -> dict:
        """Encode every context in a single batch, then mean-pool per key."""
        flat: list[str] = []
        spans: dict = {}
        for key, contexts in contexts_by_key.items():
            start = len(flat)
            flat.extend(contexts)
            spans[key] = (start, len(flat))
        if not flat:
            return {key: None for key in contexts_by_key}
        vecs = self.backend.encode(flat)
        out: dict = {}
        for key, (start, end) in spans.items():
            out[key] = None if end == start else _mean_pool_normalize(vecs[start:end])
        return out

    def propose(self, key_a, key_b, centroids) -> Verdict:
        ca, cb = centroids.get(key_a), centroids.get(key_b)
        if ca is None or cb is None:
            return Verdict("abstain", 0.0, confidence="low")
        score = cosine(ca, cb)
        if score >= self.propose_threshold:
            return Verdict("merge", score, confidence=_confidence_for(score, self.propose_threshold))
        return Verdict("abstain", score, confidence="low")

    def veto(self, key_a, key_b, centroids) -> bool:
        ca, cb = centroids.get(key_a), centroids.get(key_b)
        if ca is None or cb is None:
            return False  # no evidence → cannot veto
        return cosine(ca, cb) < self.veto_threshold


class EmbeddingBackend:
    """sentence-transformers wrapper. Lazily imports the heavy deps so the
    rest of this module stays importable without the `embeddings` extra."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str | None = None):
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]  # lazy: may ImportError

        self.device = self.resolve_device(device)
        self.model = SentenceTransformer(model_name, device=self.device)

    def resolve_device(self, explicit: str | None) -> str:
        if explicit:
            return explicit
        try:
            import torch  # type: ignore[import-not-found]  # optional (via embeddings/coref extra)

            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def _embedding_dim(self) -> int:
        # Renamed in sentence-transformers 5.x; keep the >=3 floor working.
        getter = getattr(self.model, "get_embedding_dimension", None) or (
            self.model.get_sentence_embedding_dimension
        )
        return int(getter())

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self._embedding_dim()), dtype=np.float32)
        return self.model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
