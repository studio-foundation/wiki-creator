"""STU-576: the eval's own load-bearing logic.

    HF_HUB_OFFLINE=1 PYTHONPATH=../.. python -m pytest research/embedding-eval/tests -q

Not collected by the repo suite (`testpaths = ["tests"]`) — it needs torch.
"""
import importlib.util
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

_spec = importlib.util.spec_from_file_location(
    "train_head", Path(__file__).resolve().parents[1] / "train_head.py"
)
train_head = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(train_head)


def test_supcon_is_finite_when_a_row_has_no_positive():
    """The -inf self-similarity times a 0 mask is NaN; masked_fill is why it isn't."""
    z = torch.nn.functional.normalize(torch.randn(8, 16), dim=-1)
    labels = torch.tensor([0, 0, 1, 2, 3, 4, 5, 6])  # rows 2..7 have no positive
    assert torch.isfinite(train_head.supcon(z, labels))


def test_supcon_falls_back_when_no_row_has_a_positive():
    z = torch.nn.functional.normalize(torch.randn(4, 16), dim=-1)
    assert torch.isfinite(train_head.supcon(z, torch.tensor([0, 1, 2, 3])))


def test_half_centroids_split_on_disjoint_chapters():
    """A `same` pair must come from different scenes, or it measures scene identity."""
    vectors = np.eye(4, dtype=np.float32)
    labels = ["e", "e", "e", "e"]
    centroids = train_head.half_centroids(vectors, labels, ["c1", "c1", "c2", "c2"])
    left, right = centroids["e"]
    assert float(left @ right) == pytest.approx(0.0)


def test_half_centroids_drop_an_entity_confined_to_one_chapter():
    vectors = np.eye(2, dtype=np.float32)
    assert train_head.half_centroids(vectors, ["e", "e"], ["c1", "c1"]) == {}


def test_mask_name_removes_the_name_and_keeps_the_context():
    masked = train_head.mask_name("Celaena", "Then Celaena faced the room.")
    assert "Celaena" not in masked
    assert masked == "Then [NAME] faced the room."


def test_mask_name_falls_back_to_the_longest_token():
    masked = train_head.mask_name("Captain Westfall", "she asked Westfall again")
    assert masked == "she asked [NAME] again"
