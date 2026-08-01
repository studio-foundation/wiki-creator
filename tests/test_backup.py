"""Tests for wiki_creator.backup (STU-760)."""

from datetime import date

from wiki_creator.backup import snapshot_book_artifacts
from wiki_creator.paths import book_paths_from_epub

TODAY = date(2026, 7, 31)


def _paths(tmp_path):
    return book_paths_from_epub(tmp_path / "library" / "author" / "series" / "books" / "01-book.epub")


def test_cold_book_skips_silently(tmp_path):
    paths = _paths(tmp_path)
    assert snapshot_book_artifacts(paths, today=TODAY) is None
    assert not (paths.series_dir / "bak_31-07-26").exists()


def test_snapshots_existing_book_dirs_and_registry(tmp_path):
    paths = _paths(tmp_path)
    paths.processing.mkdir(parents=True)
    (paths.processing / "epub_data.json").write_text("{}")
    paths.output.mkdir(parents=True)
    (paths.output / "page.md").write_text("hello")
    paths.series_registry.write_text("{}")
    # wiki_inputs deliberately absent — a partially-warm book.

    bak_dir = snapshot_book_artifacts(paths, today=TODAY)

    assert bak_dir == paths.series_dir / "bak_31-07-26"
    assert (bak_dir / "processing_output" / "01-book" / "epub_data.json").read_text() == "{}"
    assert (bak_dir / "output" / "01-book" / "page.md").read_text() == "hello"
    assert (bak_dir / "registry.json").exists()
    assert not (bak_dir / "wiki_inputs").exists()


def test_same_day_rerun_does_not_clobber_existing_snapshot(tmp_path):
    paths = _paths(tmp_path)
    paths.processing.mkdir(parents=True)
    (paths.processing / "epub_data.json").write_text("first run")

    first = snapshot_book_artifacts(paths, today=TODAY)
    assert (first / "processing_output" / "01-book" / "epub_data.json").read_text() == "first run"

    # The run overwrites the live artifact...
    (paths.processing / "epub_data.json").write_text("second run")
    # ...but a same-day re-entry must not touch the existing snapshot.
    assert snapshot_book_artifacts(paths, today=TODAY) is None
    assert (first / "processing_output" / "01-book" / "epub_data.json").read_text() == "first run"


def test_different_day_creates_a_new_snapshot(tmp_path):
    paths = _paths(tmp_path)
    paths.processing.mkdir(parents=True)
    (paths.processing / "epub_data.json").write_text("day one")

    snapshot_book_artifacts(paths, today=TODAY)
    (paths.processing / "epub_data.json").write_text("day two")
    tomorrow = date(2026, 8, 1)
    second = snapshot_book_artifacts(paths, today=tomorrow)

    assert second == paths.series_dir / "bak_01-08-26"
    assert (second / "processing_output" / "01-book" / "epub_data.json").read_text() == "day two"
