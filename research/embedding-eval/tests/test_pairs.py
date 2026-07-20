"""STU-576: the eval protocol. Runs everywhere — no torch, no models, no corpus.

    PYTHONPATH=../.. python -m pytest tests/ -q     (from research/embedding-eval)
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pairs import MASK, half_centroids, mask_name, score  # noqa: E402


def test_mask_name_removes_the_name_and_keeps_the_context():
    assert mask_name("Celaena", "Then Celaena faced the room.") == "Then [NAME] faced the room."


def test_mask_name_falls_back_to_the_longest_token():
    assert mask_name("Captain Westfall", "she asked Westfall again") == "she asked [NAME] again"


def test_mask_name_leaves_a_context_that_does_not_hold_the_name():
    """Better an unmasked window than a window masked at the wrong offset."""
    assert mask_name("Celaena", "the room was cold") == "the room was cold"


def test_half_centroids_split_on_disjoint_chapters():
    """A `same` pair from one chapter would measure scene identity, not identity."""
    left, right = half_centroids(np.eye(4, dtype=np.float32), ["e"] * 4, ["c1", "c1", "c2", "c2"])["e"]
    assert float(left @ right) == pytest.approx(0.0)


def test_half_centroids_drop_an_entity_confined_to_one_chapter():
    assert half_centroids(np.eye(2, dtype=np.float32), ["e", "e"], ["c1", "c1"]) == {}


def test_score_is_positive_only_when_a_single_threshold_separates():
    near = np.array([1.0, 0.0], dtype=np.float32)
    far = np.array([0.0, 1.0], dtype=np.float32)
    margin, auroc, n_same, n_diff = score({"a": (near, near), "b": (far, far)})
    assert margin > 0 and auroc == 1.0 and (n_same, n_diff) == (2, 2)


def test_score_is_negative_when_a_different_pair_outranks_a_same_pair():
    """The STU-468/490/576 shape: ranking can be fine while no threshold exists."""
    a, b = np.array([1.0, 0.0], dtype=np.float32), np.array([0.0, 1.0], dtype=np.float32)
    assert score({"x": (a, b), "y": (a, a)})[0] < 0


def test_the_mask_is_a_constant_so_it_carries_no_signal():
    assert MASK in mask_name("Chaol", "then Chaol left") and MASK in mask_name("Dorian", "Dorian sat")
