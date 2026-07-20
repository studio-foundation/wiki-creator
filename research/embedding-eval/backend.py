"""Embedding backend + cosine helpers for the STU-468/490/577/576 evals.

Moved out of `wiki_creator/` by STU-601: the production judge these served was
excised after four measured negatives, and this harness is the only consumer
left. Requires the `embeddings` extra (`pip install -e '.[embeddings]'`).
"""
from __future__ import annotations

import numpy as np

DEFAULT_MODEL = "intfloat/multilingual-e5-small"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _mean_pool_normalize(vecs: np.ndarray) -> np.ndarray:
    centroid = vecs.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    return centroid / norm if norm else centroid


class EmbeddingBackend:
    """sentence-transformers wrapper, lazily importing the heavy deps."""

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
