"""Tests for series discovery (STU-487)."""
import pytest

from wiki_creator.series import discover_series_books


def _make_books(tmp_path, names):
    books = tmp_path / "books"
    books.mkdir()
    for name in names:
        (books / name).write_text("{}\n")
    return tmp_path


def test_orders_by_numeric_tome_prefix(tmp_path) -> None:
    _make_books(tmp_path, ["02_eldest.yaml", "01_eragon.yaml", "10_x.yaml"])
    got = [b.name for b in discover_series_books(tmp_path)]
    assert got == ["01_eragon.yaml", "02_eldest.yaml", "10_x.yaml"]


def test_handles_fractional_tome_number(tmp_path) -> None:
    _make_books(tmp_path, ["04_inheritance.yaml", "04.5_tales.yaml", "05_murtagh.yaml"])
    got = [b.name for b in discover_series_books(tmp_path)]
    assert got == ["04_inheritance.yaml", "04.5_tales.yaml", "05_murtagh.yaml"]


def test_non_numeric_prefix_sorts_last(tmp_path) -> None:
    _make_books(tmp_path, ["prelude.yaml", "01_eragon.yaml"])
    got = [b.name for b in discover_series_books(tmp_path)]
    assert got == ["01_eragon.yaml", "prelude.yaml"]


def test_raises_when_no_books(tmp_path) -> None:
    (tmp_path / "books").mkdir()
    with pytest.raises(FileNotFoundError):
        discover_series_books(tmp_path)
