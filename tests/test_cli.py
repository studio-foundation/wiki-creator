"""`wiki` CLI + library discovery/alias resolution (STU-597)."""
from __future__ import annotations

import pytest

from wiki_creator import cli, library


def _book(root, rel, aliases=None):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    body = "description: x\n"
    if aliases:
        body += "aliases: [" + ", ".join(aliases) + "]\n"
    p.write_text(body, encoding="utf-8")


@pytest.fixture
def fake_lib(tmp_path):
    _book(tmp_path, "library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml", ["tog"])
    _book(tmp_path, "library/c_w_lewis/narnia/books/01-the_lion.yaml")
    _book(tmp_path, "library/paolini/inheritance/books/01_eragon.yaml")
    _book(tmp_path, "library/paolini/inheritance/books/02_eldest.yaml")
    _book(tmp_path, "public_domain/carroll/alice/books/01-alice.yaml")
    return tmp_path


def test_discover_books_spans_both_roots(fake_lib):
    slugs = {b.slug for b in library.discover_books(fake_lib)}
    assert slugs == {
        "01-throne-of-glass", "01-the_lion", "01_eragon", "02_eldest", "01-alice",
    }


def test_resolve_alias_exact(fake_lib):
    assert library.resolve_book("tog", fake_lib).name == "01-throne-of-glass.yaml"


def test_resolve_by_series_substring(fake_lib):
    assert library.resolve_book("narnia", fake_lib).parts[-3] == "narnia"


def test_resolve_ambiguous_raises(fake_lib):
    with pytest.raises(library.ResolutionError, match="ambiguous"):
        library.resolve_book("inheritance", fake_lib)  # two tomes


def test_resolve_unknown_suggests(fake_lib):
    with pytest.raises(library.ResolutionError, match="no book matches"):
        library.resolve_book("zzz", fake_lib)


def test_resolve_series(fake_lib):
    assert library.resolve_series("inherit", fake_lib).name == "inheritance"


def test_ls_lists_books(fake_lib, monkeypatch, capsys):
    monkeypatch.setattr(library, "_PROJECT_ROOT", fake_lib)
    assert cli.main(["ls"]) == 0
    out = capsys.readouterr().out
    assert "01-throne-of-glass" in out and "(tog)" in out


def test_book_run_dry_run_builds_studio_command(fake_lib, monkeypatch, capsys):
    monkeypatch.setattr(library, "_PROJECT_ROOT", fake_lib)
    rc = cli.main(["--dry-run", "book", "run", "tog"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "studio run wiki-full --input-file" in out
    assert "01-throne-of-glass.yaml --live" in out


def test_book_extraction_adds_verbose(fake_lib, monkeypatch, capsys):
    monkeypatch.setattr(library, "_PROJECT_ROOT", fake_lib)
    cli.main(["--dry-run", "book", "extraction", "tog"])
    assert "studio run wiki-extraction" in capsys.readouterr().out


def test_book_max_chapters_sets_env(fake_lib, monkeypatch):
    import os
    monkeypatch.setattr(library, "_PROJECT_ROOT", fake_lib)
    # cli sets os.environ directly; give it a throwaway copy so the mutation
    # can't leak WIKI_MAX_CHAPTERS into later tests in this process.
    env = dict(os.environ)
    env.pop("WIKI_MAX_CHAPTERS", None)
    monkeypatch.setattr(cli.os, "environ", env)
    cli.main(["--dry-run", "book", "run", "tog", "--max-chapters", "3"])
    assert env["WIKI_MAX_CHAPTERS"] == "3"


def test_unknown_book_returns_2(fake_lib, monkeypatch, capsys):
    monkeypatch.setattr(library, "_PROJECT_ROOT", fake_lib)
    assert cli.main(["book", "run", "zzz"]) == 2
    assert "no book matches" in capsys.readouterr().err


def test_real_library_tog_alias_resolves():
    # sanity against the committed library — the shipped example
    assert library.resolve_book("tog").name == "01-throne-of-glass.yaml"


def test_book_pages_bare_runs_pages_export(fake_lib, monkeypatch, capsys):
    monkeypatch.setattr(library, "_PROJECT_ROOT", fake_lib)
    cli.main(["--dry-run", "book", "pages", "tog"])
    assert "studio run pages-export --input-file" in capsys.readouterr().out


def test_book_pages_entities_uses_generator_script(fake_lib, monkeypatch, capsys):
    monkeypatch.setattr(library, "_PROJECT_ROOT", fake_lib)
    cli.main(["--dry-run", "book", "pages", "tog", "--entities", "Lucy", "Peter", "--force"])
    out = capsys.readouterr().out
    assert "generate_wiki_pages.py --book" in out
    assert "--entities Lucy Peter" in out and "--force" in out
    # The slice re-exports so the .wiki files reflect the regenerated JSON.
    assert "export_pages.py --book" in out
    assert "studio run" not in out


def test_replay_plain(capsys):
    cli.main(["--dry-run", "replay", "abc123"])
    assert capsys.readouterr().out.strip() == "$ studio replay abc123"


def test_replay_restart_from_stage(capsys):
    cli.main(["--dry-run", "replay", "abc123", "--stage", "wiki-resolution"])
    out = capsys.readouterr().out
    assert "studio replay abc123 --restart --stage wiki-resolution" in out


def test_status_and_logs(capsys):
    cli.main(["--dry-run", "status"])
    cli.main(["--dry-run", "status", "abc123"])
    cli.main(["--dry-run", "logs", "abc123"])
    out = capsys.readouterr().out
    assert "$ studio status\n" in out
    assert "$ studio status abc123" in out
    assert "$ studio logs abc123" in out
