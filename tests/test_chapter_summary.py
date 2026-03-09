"""Tests for scripts/chapter_summary.py."""

from scripts.chapter_summary import (
    _chapter_summary_config_from_payload,
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


def test_chapter_summary_config_defaults_when_missing() -> None:
    payload = {"additional_context": "file_path: library/book.epub"}

    cfg = _chapter_summary_config_from_payload(payload)

    assert cfg.mode == "extractive"
    assert cfg.max_bullets == 3
    assert cfg.llm_fallback_to_extractive is True
    assert cfg.llm_model == "qwen2.5"
    assert cfg.llm_timeout_seconds == 45


def test_chapter_summary_config_honors_explicit_values() -> None:
    payload = {
        "additional_context": (
            "file_path: library/book.epub\n"
            "generation:\n"
            "  chapter_summary:\n"
            "    mode: llm\n"
            "    max_bullets: 4\n"
            "    llm_fallback_to_extractive: false\n"
            "    llm_model: llama3:8b\n"
            "    llm_timeout_seconds: 20\n"
        )
    }

    cfg = _chapter_summary_config_from_payload(payload)

    assert cfg.mode == "llm"
    assert cfg.max_bullets == 4
    assert cfg.llm_fallback_to_extractive is False
    assert cfg.llm_model == "llama3:8b"
    assert cfg.llm_timeout_seconds == 20


def test_chapter_summary_config_sanitizes_invalid_values() -> None:
    payload = {
        "additional_context": (
            "file_path: library/book.epub\n"
            "generation:\n"
            "  chapter_summary:\n"
            "    mode: invalid\n"
            "    max_bullets: -2\n"
            "    llm_fallback_to_extractive: nope\n"
            "    llm_timeout_seconds: 0\n"
        )
    }

    cfg = _chapter_summary_config_from_payload(payload)

    assert cfg.mode == "extractive"
    assert cfg.max_bullets == 3
    assert cfg.llm_fallback_to_extractive is True
    assert cfg.llm_timeout_seconds == 45


def test_summarize_chapter_extractive_deprioritizes_dialogue_fragments() -> None:
    chapter = {
        "id": "ch04",
        "title": "Chapter 4",
        "content": (
            '"No," Dorian said with a shrug, glancing toward Chaol in the corridor. '
            '"You always say that," Chaol replied, his tone clipped and impatient. '
            "Celaena discovered a hidden passage behind the map room and followed the draft. "
            "She found chalk marks that linked Duke Perrington to the dead champion. "
            "By dusk, she reported the evidence to Nehemia and asked for discretion."
        ),
    }

    result = summarize_chapter(chapter)

    assert result["summary_method"] == "extractive"
    assert result["quality_flags"] == []
    assert all(not bullet.strip().startswith('"') for bullet in result["summary_bullets"])
    assert any("hidden passage" in bullet.lower() for bullet in result["summary_bullets"])


def test_summarize_chapter_extractive_spans_chapter_progression() -> None:
    chapter = {
        "id": "ch05",
        "title": "Chapter 5",
        "content": (
            "At dawn, Celaena met Chaol in the training yard to review the day's schedule. "
            "Before noon, she slipped into the library stacks to compare old maps. "
            "In the afternoon, she followed a servant through the west corridor to a locked archive. "
            "At sunset, she decoded a ledger that tied Cain to the sabotage. "
            "After nightfall, she warned Dorian that the final duel might be rigged."
        ),
    }

    result = summarize_chapter(chapter)
    bullets = result["summary_bullets"]

    assert len(bullets) == 3
    assert any("dawn" in b.lower() or "before noon" in b.lower() for b in bullets)
    assert any("afternoon" in b.lower() or "sunset" in b.lower() for b in bullets)
    assert any("nightfall" in b.lower() for b in bullets)
