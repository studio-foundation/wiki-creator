"""EPUB import + YAML scaffold (STU-597)."""
from __future__ import annotations

import pytest

from wiki_creator import book_import, cli


def _make_epub(path, title, author):
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_title(title)
    if author:
        book.add_author(author)
    c = epub.EpubHtml(title="C1", file_name="c1.xhtml", content="<p>hi</p>")
    book.add_item(c)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.toc = [c]
    book.spine = [c]
    epub.write_epub(str(path), book)
    return path


def test_read_metadata_roundtrip(tmp_path):
    p = _make_epub(tmp_path / "x.epub", "Throne of Glass", "Sarah J. Maas")
    assert book_import.read_metadata(p) == ("Throne of Glass", "Sarah J. Maas")


def test_plan_import_places_by_slug():
    plan = book_import.plan_import("x.epub", "Throne of Glass", "Sarah J. Maas")
    assert plan.dest_epub.as_posix() == "library/sarah_j_maas/throne_of_glass/books/01-throne_of_glass.epub"
    assert plan.dest_yaml.as_posix().endswith("01-throne_of_glass.yaml")


def test_render_yaml_minimal_no_summary():
    from pathlib import Path
    out = book_import.render_yaml(Path("library/a/b/books/01-b.epub"), "B", "A", None)
    assert "file_path: library/a/b/books/01-b.epub" in out
    assert "novel_summary" not in out
    assert "spacy_model: en_core_web_lg" in out


def test_render_yaml_with_summary_indents():
    from pathlib import Path
    out = book_import.render_yaml(Path("x.epub"), "T", None, "Line one.\nLine two.")
    assert "novel_summary: |\n  Line one.\n  Line two." in out


def test_generate_book_dry_run_writes_nothing(tmp_path, monkeypatch):
    p = _make_epub(tmp_path / "src.epub", "Alice in Wonderland", "Lewis Carroll")
    plan = book_import.generate_book(p, dry_run=True, base=tmp_path)
    assert not (tmp_path / plan.dest_epub).exists()
    assert not (tmp_path / plan.dest_yaml).exists()
    assert plan.dest_yaml.as_posix() == "library/lewis_carroll/alice_in_wonderland/books/01-alice_in_wonderland.yaml"


def test_generate_book_writes_epub_and_yaml(tmp_path):
    p = _make_epub(tmp_path / "src.epub", "Dracula", "Bram Stoker")
    plan = book_import.generate_book(p, base=tmp_path)
    assert (tmp_path / plan.dest_epub).is_file()
    assert (tmp_path / plan.dest_yaml).read_text().startswith("description: |")


def test_generate_book_refuses_overwrite(tmp_path):
    p = _make_epub(tmp_path / "src.epub", "Dracula", "Bram Stoker")
    book_import.generate_book(p, base=tmp_path)
    with pytest.raises(FileExistsError):
        book_import.generate_book(p, base=tmp_path)
    book_import.generate_book(p, base=tmp_path, force=True)  # ok


def test_generate_book_enrich_injects_summary(tmp_path):
    p = _make_epub(tmp_path / "src.epub", "Dracula", "Bram Stoker")
    plan = book_import.generate_book(
        p, base=tmp_path, dry_run=True,
        enrich=lambda title, author: f"Summary of {title}.",
    )
    assert "novel_summary: |\n  Summary of Dracula." in plan.yaml_text


def test_cli_generate_dry_run(tmp_path, monkeypatch, capsys):
    p = _make_epub(tmp_path / "src.epub", "Oz", "L. Frank Baum")
    monkeypatch.setattr(book_import, "_PROJECT_ROOT", tmp_path)
    assert cli.main(["generate-books", str(p), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would write library/l_frank_baum/oz/books/01-oz.epub" in out
    assert "file_path:" in out


def test_cli_generate_missing_epub_returns_2(capsys):
    assert cli.main(["generate-books", "/nope/x.epub"]) == 2
    assert "no such epub" in capsys.readouterr().err
