"""The worktree import guard fails loud on a foreign checkout (STU-569)."""
from pathlib import Path

import pytest

from wiki_creator import _assert_imported_from_cwd

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_passes_from_the_real_checkout(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    _assert_imported_from_cwd()  # imported package IS cwd/wiki_creator


def test_passes_when_cwd_has_no_wiki_creator(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _assert_imported_from_cwd()  # nothing to conflict with


def test_raises_on_a_foreign_checkout(tmp_path, monkeypatch):
    (tmp_path / "wiki_creator").mkdir()  # a *different* checkout under cwd
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ImportError, match="STU-569"):
        _assert_imported_from_cwd()


def test_opt_out_silences_the_guard(tmp_path, monkeypatch):
    (tmp_path / "wiki_creator").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WIKI_CREATOR_ALLOW_FOREIGN_CHECKOUT", "1")
    _assert_imported_from_cwd()
