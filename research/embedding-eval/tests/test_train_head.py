"""STU-576: the trained head itself. Skipped where torch is absent (CI).

The protocol tests that must run everywhere live in `test_pairs.py`.
"""
import sys
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="module")
def train_head():
    return pytest.importorskip("train_head")


def test_supcon_is_finite_when_a_row_has_no_positive(train_head):
    """The -inf self-similarity times a 0 mask is NaN; masked_fill is why it isn't.

    The NaN version still trains and still reports plausible margins, so nothing
    but this assertion catches it.
    """
    z = torch.nn.functional.normalize(torch.randn(8, 16), dim=-1)
    labels = torch.tensor([0, 0, 1, 2, 3, 4, 5, 6])  # rows 2..7 have no positive
    assert torch.isfinite(train_head.supcon(z, labels))


def test_supcon_falls_back_when_no_row_has_a_positive(train_head):
    z = torch.nn.functional.normalize(torch.randn(4, 16), dim=-1)
    assert torch.isfinite(train_head.supcon(z, torch.tensor([0, 1, 2, 3])))
