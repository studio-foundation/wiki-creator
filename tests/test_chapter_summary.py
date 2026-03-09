"""Tests for scripts/chapter_summary.py."""

from scripts.chapter_summary import (
    _epub_output_from_payload,
    summarize_chapter,
    summarize_chapters,
)


def test_summarize_chapter_returns_max_three_bullets():
    chapter = {
        "id": "ch01",
        "title": "Chapter 1",
        "content": (
            "Dorian arrived at the glass castle and met Chaol in the hall. "
            "They discussed the King's orders in detail. "
            "Celaena watched them from a balcony and stayed silent. "
            "Later, Dorian returned to the council chamber to speak with his father."
        ),
    }

    result = summarize_chapter(chapter)

    assert result["chapter_id"] == "ch01"
    assert result["chapter_title"] == "Chapter 1"
    assert len(result["summary_bullets"]) <= 3
    assert len(result["summary_bullets"]) > 0


def test_summarize_chapters_uses_title_as_chapter_key():
    chapters = [
        {
            "id": "x01",
            "title": "Chapter 1",
            "content": "Dorian met Chaol in the courtyard. Celaena observed them closely.",
        },
        {
            "id": "x02",
            "title": "",
            "content": "Nehemia visited the library and spoke with Celaena.",
        },
    ]

    summaries = summarize_chapters(chapters)

    assert "Chapter 1" in summaries
    assert "x02" in summaries


def test_summarize_chapter_ignores_empty_or_noise_only_content():
    chapter = {
        "id": "ch02",
        "title": "Chapter 2",
        "content": " \n\n  \n",
    }

    result = summarize_chapter(chapter)

    assert result["summary_bullets"] == ["No reliable summary available for this chapter."]


def test_summarize_chapters_is_deterministic():
    chapters = [
        {
            "id": "ch03",
            "title": "Chapter 3",
            "content": (
                "Chaol entered the room quietly. "
                "Dorian asked about the latest tournament results. "
                "Celaena refused to answer and left."
            ),
        }
    ]

    a = summarize_chapters(chapters)
    b = summarize_chapters(chapters)

    assert a == b


def test_epub_output_from_payload_prefers_all_stage_outputs():
    payload = {
        "all_stage_outputs": {"epub-parse": {"chapters": [{"id": "ch01", "content": "x"}]}},
        "previous_outputs": {"epub-parse": {"chapters": [{"id": "ch02", "content": "y"}]}},
    }
    out = _epub_output_from_payload(payload)
    assert out["chapters"][0]["id"] == "ch01"
