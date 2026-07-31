"""STU-753: the book-search-search_book tool executor's confinement gate."""
import json

from scripts.book_search_tool import build_response, resolve_book_dir


def _book_dir(root, corpus="library"):
    d = root / corpus / "some_author" / "some_series" / "processing_output" / "some-book"
    d.mkdir(parents=True)
    return d


def test_accepts_a_library_book_dir(tmp_path):
    book_dir = _book_dir(tmp_path)
    resolved = resolve_book_dir(
        "library/some_author/some_series/processing_output/some-book", root=tmp_path
    )
    assert resolved == book_dir


def test_accepts_a_public_domain_book_dir(tmp_path):
    book_dir = _book_dir(tmp_path, corpus="public_domain")
    resolved = resolve_book_dir(
        "public_domain/some_author/some_series/processing_output/some-book", root=tmp_path
    )
    assert resolved == book_dir


def test_rejects_a_dir_outside_the_two_corpus_roots(tmp_path):
    (tmp_path / "scripts").mkdir()
    assert resolve_book_dir("scripts", root=tmp_path) is None


def test_rejects_path_traversal_out_of_the_repo(tmp_path):
    assert resolve_book_dir(
        "library/a/b/processing_output/../../../../../etc", root=tmp_path
    ) is None


def test_rejects_an_absolute_path_outside_the_repo(tmp_path):
    assert resolve_book_dir("/etc/passwd", root=tmp_path) is None


def test_rejects_garbage(tmp_path):
    assert resolve_book_dir("", root=tmp_path) is None
    assert resolve_book_dir("not a path at all", root=tmp_path) is None


def test_build_response_searches_the_books_chapters(tmp_path):
    book_dir = _book_dir(tmp_path)
    (book_dir / "chapters.json").write_text(
        json.dumps({"chapters": {"c1": "Brom rode north with Eragon."}}), encoding="utf-8"
    )
    response = build_response(
        "library/some_author/some_series/processing_output/some-book", "Eragon", root=tmp_path
    )
    assert response["count"] == 1
    assert response["results"][0]["chapter_id"] == "c1"


def test_build_response_reports_an_invalid_book_dir(tmp_path):
    response = build_response("not/a/book/dir", "Eragon", root=tmp_path)
    assert "error" in response


def test_build_response_reports_a_missing_chapters_artifact(tmp_path):
    _book_dir(tmp_path)
    response = build_response(
        "library/some_author/some_series/processing_output/some-book", "Eragon", root=tmp_path
    )
    assert "error" in response
