"""STU-550: a chapter's number is its position, assigned once and read as a field."""

import pytest

from wiki_creator.chapters import (
    chapter_number_index,
    number_chapters,
    resolve_chapter_number,
)


def _library_chapters() -> list[dict]:
    """The shape section_filter hands over: spine order, front matter tagged."""
    return [
        {"id": "cop", "title": "Copyright", "frontmatter": True},
        {"id": "bookcontent2_0", "title": "CHAPTER ONE. LUCY LOOKS INTO A WARDROBE"},
        {"id": "bookcontent10_0", "title": "CHAPTER NINE. IN THE WITCH'S HOUSE"},
        {"id": "bookcontent18_0", "title": "CHAPTER SEVENTEEN. THE HUNTING OF THE WHITE STAG"},
    ]


def test_number_chapters_counts_narrative_position_not_id_digits():
    chapters = _library_chapters()
    number_chapters(chapters)
    assert [c.get("chapter_number") for c in chapters] == [None, 1, 2, 3]


def test_number_chapters_leaves_frontmatter_unnumbered_on_a_rerun():
    chapters = _library_chapters()
    number_chapters(chapters)
    chapters[1]["frontmatter"] = True
    number_chapters(chapters)
    assert "chapter_number" not in chapters[1]
    assert [c.get("chapter_number") for c in chapters] == [None, None, 1, 2]


def test_chapter_number_index_resolves_both_ids_and_titles():
    chapters = _library_chapters()
    number_chapters(chapters)
    index = chapter_number_index(chapters)
    assert index["bookcontent2_0"] == 1
    assert index["CHAPTER ONE. LUCY LOOKS INTO A WARDROBE"] == 1
    assert "cop" not in index


def test_resolve_chapter_number_never_falls_back_to_digits(capsys):
    index = {"bookcontent2_0": 1}
    assert resolve_chapter_number("bookcontent2_0", index) == 1
    assert resolve_chapter_number("bookcontent10_0", index) is None
    assert "bookcontent10_0" in capsys.readouterr().err


@pytest.mark.parametrize("ref", [7, 0])
def test_resolve_chapter_number_passes_numbers_through(ref):
    assert resolve_chapter_number(ref, {}) == ref
