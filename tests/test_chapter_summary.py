"""Tests for scripts/chapter_summary.py."""

import json
from types import SimpleNamespace

import pytest

from scripts.chapter_summary import (
    ChapterSummaryConfig,
    _FALLBACK_BULLET,
    _chapter_summary_config_from_payload,
    _detect_temporal_context,
    _parse_llm_summary_response_text,
    _read_epub_data,
    _score_sentence,
    summarize_chapters_incrementally,
    summarize_chapter,
    summarize_chapter_from_item_result,
    summarize_chapters,
)
from wiki_creator.studio_io import extract_stage_output_from_run_payload


def test_score_sentence_accepts_action_cues_kwarg():
    score = _score_sentence("Dorian found the letter.", 0, 5, action_cues=("found",))
    assert isinstance(score, float)


def test_score_sentence_action_cue_increases_score():
    base = _score_sentence("Dorian walked into the room.", 0, 5, action_cues=())
    boosted = _score_sentence("Dorian found the letter.", 0, 5, action_cues=("found",))
    assert boosted > base


def test_summarize_chapter_accepts_action_cues_kwarg():
    chapter = {
        "id": "ch01",
        "title": "Chapter 1",
        "content": "Celaena arrived at the castle. She found the hidden door.",
    }
    result = summarize_chapter(chapter, action_cues=("arrived", "found"))
    assert len(result["summary_bullets"]) > 0


def test_summarize_chapters_accepts_action_cues_kwarg():
    chapters = [{"id": "ch01", "title": "Chapter 1", "content": "Dorian met Chaol."}]
    result = summarize_chapters(chapters, action_cues=("met",))
    assert "Chapter 1" in result


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


def test_summarize_chapters_excludes_tagged_frontmatter_entries():
    chapters = [
        {"id": "sinopsis.xhtml", "title": "sinopsis.xhtml", "frontmatter": True, "content": "Synopsis content."},
        {"id": "info.xhtml", "title": "info.xhtml", "frontmatter": True, "content": "Metadata content."},
        {"id": "dedicatoria.xhtml", "title": "dedicatoria.xhtml", "frontmatter": True, "content": "Dedication content."},
        {"id": "acknowledgements.xhtml", "title": "Acknowledgements", "frontmatter": True, "content": "Thanks to many people."},
        {"id": "autor.xhtml", "title": "Author", "frontmatter": True, "content": "Author bio."},
        {"id": "ch01", "title": "Chapter 1", "content": "Celaena enters the castle and meets Dorian."},
    ]

    summaries = summarize_chapters(chapters)

    assert "sinopsis.xhtml" not in summaries
    assert "info.xhtml" not in summaries
    assert "dedicatoria.xhtml" not in summaries
    assert "Acknowledgements" not in summaries
    assert "Author" not in summaries
    assert "Chapter 1" in summaries


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


def test_summarize_chapters_incrementally_resumes_from_existing_file(tmp_path) -> None:
    output_file = tmp_path / "chapter_summaries.json"
    output_file.write_text(
        json.dumps(
            {
                "chapter_summaries": {
                    "Chapter 1": {
                        "chapter_id": "ch01",
                        "chapter_title": "Chapter 1",
                        "summary_bullets": ["Existing summary."],
                        "summary_method": "llm",
                        "quality_flags": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Old content should be skipped."},
        {"id": "ch02", "title": "Chapter 2", "content": "Celaena follows Chaol into the castle vault."},
    ]

    summaries = summarize_chapters_incrementally(chapters, output_file=output_file)

    assert summaries["Chapter 1"]["summary_bullets"] == ["Existing summary."]
    assert "Chapter 2" in summaries


def test_summarize_chapters_incrementally_retries_failed_llm_on_resume(tmp_path, monkeypatch) -> None:
    output_file = tmp_path / "chapter_summaries.json"
    output_file.write_text(
        json.dumps(
            {
                "chapter_summaries": {
                    "Chapter 1": {
                        "chapter_id": "ch01", "chapter_title": "Chapter 1",
                        "summary_bullets": ["Extractive stand-in."],
                        "summary_method": "extractive_fallback",
                        "quality_flags": ["studio_run_timeout", "fallback_used"],
                    },
                    "Chapter 2": {
                        "chapter_id": "ch02", "chapter_title": "Chapter 2",
                        "summary_bullets": [_FALLBACK_BULLET],
                        "summary_method": "llm", "quality_flags": ["studio_run_failed"],
                    },
                    "Chapter 3": {
                        "chapter_id": "ch03", "chapter_title": "Chapter 3",
                        "summary_bullets": ["A real LLM summary."],
                        "summary_method": "llm", "quality_flags": [],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Celaena enters the vault."},
        {"id": "ch02", "title": "Chapter 2", "content": "Chaol warns the king."},
        {"id": "ch03", "title": "Chapter 3", "content": "Dorian reads the letter."},
    ]
    retried: list[str] = []

    def fake_runner(*, chapter, config):
        retried.append(chapter["title"])
        return {"summary_bullets": [f"Recovered {chapter['title']}."]}

    monkeypatch.setattr("scripts.chapter_summary._run_chapter_summary_item", fake_runner)

    summaries = summarize_chapters_incrementally(
        chapters, output_file=output_file,
        config=ChapterSummaryConfig(mode="llm", max_bullets=3, llm_fallback_to_extractive=True),
    )

    assert sorted(retried) == ["Chapter 1", "Chapter 2"]  # both failures retried
    assert summaries["Chapter 1"]["summary_bullets"] == ["Recovered Chapter 1."]
    assert summaries["Chapter 2"]["summary_bullets"] == ["Recovered Chapter 2."]
    assert summaries["Chapter 3"]["summary_bullets"] == ["A real LLM summary."]  # success untouched


def test_summarize_chapters_incrementally_saves_after_each_new_chapter(tmp_path, monkeypatch) -> None:
    output_file = tmp_path / "chapter_summaries.json"
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Celaena enters the hall and meets Dorian."},
        {"id": "ch02", "title": "Chapter 2", "content": "Chaol warns Celaena that the king is watching her."},
    ]
    save_sizes: list[int] = []

    def fake_save(chapter_summaries, path):
        assert path == output_file
        save_sizes.append(len(chapter_summaries))

    monkeypatch.setattr("scripts.chapter_summary._save_chapter_summaries", fake_save)

    summarize_chapters_incrementally(chapters, output_file=output_file)

    assert save_sizes == [1, 2]


def test_summarize_chapters_incrementally_logs_llm_error_details(tmp_path, monkeypatch) -> None:
    output_file = tmp_path / "chapter_summaries.json"
    debug_dir = tmp_path / "chapter_summary_llm_debug"
    chapters = [
        {"id": "ch07.xhtml", "title": "Chapter 7", "content": "Celaena studies the map and finds nothing."},
    ]

    monkeypatch.setattr(
        "scripts.chapter_summary._run_chapter_summary_item",
        lambda **_: {
            "summary_bullets": [],
            "error": "llm_json_parse_error",
            "raw_response": "not json at all",
        },
    )

    summarize_chapters_incrementally(
        chapters,
        output_file=output_file,
        debug_dir=debug_dir,
        config=ChapterSummaryConfig(mode="llm", max_bullets=3, llm_fallback_to_extractive=True),
    )

    debug_files = sorted(debug_dir.glob("*.json"))
    assert len(debug_files) == 1
    payload = json.loads(debug_files[0].read_text(encoding="utf-8"))
    assert payload["error"] == "llm_json_parse_error"
    assert payload["chapter_id"] == "ch07.xhtml"
    assert payload["chapter_title"] == "Chapter 7"
    assert payload["raw_response"] == "not json at all"


def test_summarize_chapters_incrementally_uses_item_runner_in_llm_mode(tmp_path, monkeypatch) -> None:
    output_file = tmp_path / "chapter_summaries.json"
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Ignored by fake runner."},
    ]
    calls: list[tuple[str, str]] = []

    def fake_runner(*, chapter, config):
        calls.append((chapter["id"], config.mode))
        return {
            "chapter_id": chapter["id"],
            "chapter_title": chapter["title"],
            "summary_bullets": ["Studio-generated summary."],
        }

    monkeypatch.setattr("scripts.chapter_summary._run_chapter_summary_item", fake_runner)

    summaries = summarize_chapters_incrementally(
        chapters,
        output_file=output_file,
        config=ChapterSummaryConfig(mode="llm"),
    )

    assert calls == [("ch01", "llm")]
    assert summaries["Chapter 1"]["summary_method"] == "llm"
    assert summaries["Chapter 1"]["summary_bullets"] == ["Studio-generated summary."]


def test_summarize_chapters_incrementally_item_runner_failure_falls_back_and_logs(tmp_path, monkeypatch) -> None:
    output_file = tmp_path / "chapter_summaries.json"
    debug_dir = tmp_path / "chapter_summary_llm_debug"
    chapters = [
        {
            "id": "ch07.xhtml",
            "title": "Chapter 7",
            "content": "At dawn, Celaena studied the map. By noon, she found the hidden door.",
        },
    ]

    monkeypatch.setattr(
        "scripts.chapter_summary._run_chapter_summary_item",
        lambda **_: {
            "error": "studio_run_failed",
            "raw_response": "plain string response",
            "run_metadata": {"pipeline": "chapter-summary-item", "attempts": 3},
        },
    )

    summaries = summarize_chapters_incrementally(
        chapters,
        output_file=output_file,
        debug_dir=debug_dir,
        config=ChapterSummaryConfig(mode="llm", llm_fallback_to_extractive=True),
    )

    assert summaries["Chapter 7"]["summary_method"] == "extractive_fallback"
    assert "studio_run_failed" in summaries["Chapter 7"]["quality_flags"]
    debug_files = sorted(debug_dir.glob("*.json"))
    assert len(debug_files) == 1
    payload = json.loads(debug_files[0].read_text(encoding="utf-8"))
    assert payload["error"] == "studio_run_failed"
    assert payload["run_metadata"] == {"pipeline": "chapter-summary-item", "attempts": 3}


def test_extract_stage_output_from_run_payload_reads_successful_stage_output() -> None:
    run_payload = {
        "id": "26ea6f7e-274e-4ec8-8b21-d422199982ba",
        "pipeline_name": "chapter-summary-item",
        "status": "success",
        "stages": [
            {
                "stage_name": "chapter-summary-item",
                "status": "success",
                "output": {
                    "chapter_id": "C07.xhtml",
                    "chapter_title": "Chapter 7",
                    "summary_bullets": ["One bullet."],
                },
            }
        ],
    }

    output = extract_stage_output_from_run_payload(run_payload, "chapter-summary-item")

    assert output == {
        "chapter_id": "C07.xhtml",
        "chapter_title": "Chapter 7",
        "summary_bullets": ["One bullet."],
    }


def test_read_epub_data_reads_the_artifact(tmp_path):
    processing = tmp_path / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "epub_data.json").write_text(
        json.dumps({"chapters": [{"id": "ch01", "content": "x"}]}), encoding="utf-8"
    )
    out = _read_epub_data(SimpleNamespace(processing=processing))
    assert out["chapters"][0]["id"] == "ch01"


def test_read_epub_data_exits_when_extraction_has_not_run(tmp_path):
    with pytest.raises(SystemExit):
        _read_epub_data(SimpleNamespace(processing=tmp_path))


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


def test_summarize_chapter_llm_mode_uses_llm_when_response_valid(monkeypatch) -> None:
    chapter = {
        "id": "ch06",
        "title": "Chapter 6",
        "content": "Celaena tracks a suspect through the castle and reports to Chaol.",
    }

    monkeypatch.setattr(
        "scripts.chapter_summary._call_llm_summary",
        lambda **_: ["Celaena tracks a suspect through the castle.", "She reports her findings to Chaol."],
    )
    cfg = ChapterSummaryConfig(mode="llm", max_bullets=3, llm_fallback_to_extractive=True)

    result = summarize_chapter(chapter, config=cfg)

    assert result["summary_method"] == "llm"
    assert result["quality_flags"] == []
    assert result["summary_bullets"] == [
        "Celaena tracks a suspect through the castle.",
        "She reports her findings to Chaol.",
    ]


def test_parse_llm_summary_response_text_accepts_wrapped_json() -> None:
    bullets, error = _parse_llm_summary_response_text(
        'Here is the JSON:\n{"summary_bullets":["Celaena finds a hidden door."]}\nDone.',
        max_bullets=3,
    )

    assert bullets == ["Celaena finds a hidden door."]
    assert error is None


def test_summarize_chapter_llm_mode_falls_back_to_extractive_with_specific_flag(monkeypatch) -> None:
    chapter = {
        "id": "ch07",
        "title": "Chapter 7",
        "content": (
            "At dawn, Celaena studied the map. "
            "By noon, she found a hidden stair near the council room. "
            "At night, she warned Nehemia that the chamber was compromised."
        ),
    }

    monkeypatch.setattr(
        "scripts.chapter_summary._call_llm_summary",
        lambda **_: {"summary_bullets": [], "error": "llm_json_parse_error"},
    )
    cfg = ChapterSummaryConfig(mode="llm", max_bullets=3, llm_fallback_to_extractive=True)

    result = summarize_chapter(chapter, config=cfg)

    assert result["summary_method"] == "extractive_fallback"
    assert "fallback_used" in result["quality_flags"]
    assert "llm_json_parse_error" in result["quality_flags"]
    assert len(result["summary_bullets"]) > 0


def test_summarize_chapter_llm_mode_without_fallback_returns_specific_flag(monkeypatch) -> None:
    chapter = {
        "id": "ch08",
        "title": "Chapter 8",
        "content": "Dorian questions Cain about the sabotage while guards watch the hall.",
    }

    monkeypatch.setattr(
        "scripts.chapter_summary._call_llm_summary",
        lambda **_: {"summary_bullets": [], "error": "llm_timeout"},
    )
    cfg = ChapterSummaryConfig(mode="llm", max_bullets=3, llm_fallback_to_extractive=False)

    result = summarize_chapter(chapter, config=cfg)

    assert result["summary_method"] == "llm"
    assert result["summary_bullets"] == ["No reliable summary available for this chapter."]
    assert "llm_timeout" in result["quality_flags"]


def test_detect_temporal_context_flashback_when_cue_matches():
    content = "Des années plus tôt, Celaena vivait encore à Rifthold."
    result = _detect_temporal_context(content, flashback_cues=("des années plus tôt",))
    assert result == "flashback"


def test_detect_temporal_context_present_when_no_cue():
    content = "Celaena entered the castle and met Dorian."
    result = _detect_temporal_context(content, flashback_cues=("years before", "she remembered"))
    assert result == "present"


def test_detect_temporal_context_unknown_when_no_cues_provided():
    content = "Celaena entered the castle and met Dorian."
    result = _detect_temporal_context(content, flashback_cues=())
    assert result == "unknown"


def test_detect_temporal_context_case_insensitive():
    content = "YEARS BEFORE she had trained under Arobynn."
    result = _detect_temporal_context(content, flashback_cues=("years before",))
    assert result == "flashback"


def test_summarize_chapter_extractive_sets_temporal_context_present():
    chapter = {
        "id": "ch01", "title": "Chapter 1",
        "content": "Celaena entered the castle and met Dorian.",
    }
    result = summarize_chapter(chapter, flashback_cues=("years before",))
    assert result["temporal_context"] == "present"
    assert result["flashback_anchor"] is None


def test_summarize_chapter_extractive_detects_flashback():
    chapter = {
        "id": "ch02", "title": "Chapter 2",
        "content": "Years before, she had trained under Arobynn in the Assassins Keep.",
    }
    result = summarize_chapter(chapter, flashback_cues=("years before",))
    assert result["temporal_context"] == "flashback"
    assert result["flashback_anchor"] is None


def test_summarize_chapter_no_cues_gives_unknown():
    chapter = {
        "id": "ch03", "title": "Chapter 3",
        "content": "Celaena studied the map and found nothing.",
    }
    result = summarize_chapter(chapter, flashback_cues=())
    assert result["temporal_context"] == "unknown"


def test_summarize_chapter_from_item_result_passes_through_temporal_context():
    chapter = {"id": "ch01", "title": "Chapter 1", "content": "..."}
    item_result = {
        "chapter_id": "ch01",
        "chapter_title": "Chapter 1",
        "summary_bullets": ["Celaena found a clue."],
        "temporal_context": "flashback",
        "flashback_anchor": "5 ans avant les événements du ch.01",
    }
    result = summarize_chapter_from_item_result(chapter, item_result)
    assert result["temporal_context"] == "flashback"
    assert result["flashback_anchor"] == "5 ans avant les événements du ch.01"


def test_summarize_chapter_from_item_result_defaults_unknown_when_missing():
    chapter = {"id": "ch01", "title": "Chapter 1", "content": "..."}
    item_result = {
        "summary_bullets": ["Celaena found a clue."],
    }
    result = summarize_chapter_from_item_result(chapter, item_result)
    assert result["temporal_context"] == "unknown"
    assert result["flashback_anchor"] is None


def test_summarize_chapter_from_item_result_detects_temporal_context_from_chapter_when_absent():
    """Studio pipeline doesn't return temporal_context — it should be inferred from chapter content."""
    chapter = {
        "id": "ch03",
        "title": "Chapter 3",
        "content": "Years before, she had trained in the Keep.",
    }
    item_result = {
        "summary_bullets": ["She trained hard."],
        # no temporal_context key — simulates Studio pipeline output
    }
    result = summarize_chapter_from_item_result(
        chapter, item_result, flashback_cues=("years before",)
    )
    assert result["temporal_context"] == "flashback"


def test_summarize_chapter_from_item_result_fallback_uses_heuristic():
    chapter = {
        "id": "ch02", "title": "Chapter 2",
        "content": "Years before, Celaena had trained in the Keep.",
    }
    item_result = {"summary_bullets": [], "error": "llm_timeout"}
    cfg = ChapterSummaryConfig(mode="llm", llm_fallback_to_extractive=True)
    result = summarize_chapter_from_item_result(
        chapter, item_result, config=cfg, flashback_cues=("years before",)
    )
    assert result["summary_method"] == "extractive_fallback"
    assert result["temporal_context"] == "flashback"


def test_main_from_book_reads_chapters_json(tmp_path, monkeypatch):
    """--book mode must read chapters from epub_data.json, not stdin."""
    import json
    from unittest.mock import patch, MagicMock

    # Minimal book YAML
    book_yaml = tmp_path / "book.yaml"
    book_yaml.write_text("title: Test\nspacy_model: en_core_web_sm\n")

    # Fake processing dir with epub_data.json
    processing = tmp_path / "processing_output" / "test"
    processing.mkdir(parents=True)
    chapters = [{"id": "ch01", "title": "Chapter 1", "content": "Celaena ran."}]
    (processing / "epub_data.json").write_text(json.dumps({"title": "Test", "chapters": chapters}))

    # Patch book_paths_from_yaml to return a fake BookPaths
    from wiki_creator.paths import BookPaths
    fake_paths = BookPaths(
        epub=tmp_path / "book.epub",
        processing=processing,
        wiki_inputs=tmp_path / "wiki_inputs",
        output=tmp_path / "output",
    )

    with patch("scripts.chapter_summary.book_paths_from_yaml", return_value=fake_paths), \
         patch("scripts.chapter_summary.summarize_chapters_incrementally", return_value={}) as mock_sum:
        from scripts.chapter_summary import _main_from_book
        _main_from_book(str(book_yaml))

    mock_sum.assert_called_once()
    call_chapters = mock_sum.call_args[0][0]
    assert call_chapters == chapters


from scripts.chapter_summary import _resolve_pov_fields, _summarize_chapter_extractive, ChapterSummaryConfig

_MARKERS = ("wondered", "felt", "realized", "thought")
_EXCLUDE = ("the", "and", "she", "he", "lord")


def test_resolve_pov_fields_deterministic_high():
    chapter = {
        "id": "c1",
        "content": "Chaol wondered. Chaol felt cold. Chaol realized the plan. Chaol thought hard.",
        "pov": "third_limited",
        "pov_confidence": "high",
    }
    out = _resolve_pov_fields(chapter, _MARKERS, _EXCLUDE)
    assert out["pov"] == "third_limited"
    assert out["pov_character"] == "Chaol"
    assert out["pov_character_source"] == "deterministic"


def test_resolve_pov_fields_omniscient_abstains():
    chapter = {"id": "c2", "content": "The court gathered.", "pov": "omniscient", "pov_confidence": "high"}
    out = _resolve_pov_fields(chapter, _MARKERS, _EXCLUDE)
    assert out["pov_character"] is None
    assert out["pov_character_source"] == "none"


def test_resolve_pov_fields_llm_fallback_when_uncertain():
    """Deterministic uncertain + LLM provided a name → source 'llm'."""
    chapter = {"id": "c3", "content": "A spoke. B answered.", "pov": "third_limited", "pov_confidence": "low"}
    llm = {"pov_character": "Celaena", "pov_character_confidence": "high"}
    out = _resolve_pov_fields(chapter, _MARKERS, _EXCLUDE, llm_item_result=llm)
    assert out["pov_character"] == "Celaena"
    assert out["pov_character_source"] == "llm"


def test_extractive_summary_carries_pov_fields():
    chapter = {"id": "c4", "content": "Chaol felt cold. Chaol felt tired. Chaol moved on.", "pov": "third_limited", "pov_confidence": "high"}
    out = _summarize_chapter_extractive(chapter, ChapterSummaryConfig(), thought_markers=_MARKERS, exclusion_words=_EXCLUDE)
    assert "pov" in out and "pov_character" in out and "pov_character_source" in out


# --- STU-433: weight extractive summaries by entity importance ---

from scripts.chapter_summary import (
    build_entity_importance_index,
    _load_classified_entities,
)


def test_build_entity_importance_index_weights_principal_over_secondary():
    entities = [
        {"canonical_name": "Celaena", "aliases": ["Celaena", "Sardothien"], "importance": "principal"},
        {"canonical_name": "Chaol", "aliases": [], "importance": "secondary"},
        {"canonical_name": "Guard", "aliases": [], "importance": "figurant"},
        {"canonical_name": "Rando", "aliases": [], "importance": "ignored"},
    ]
    index = build_entity_importance_index(entities)
    matched = {pat.pattern: w for pat, w in index}
    # principal + secondary present, figurant/ignored absent
    weights = sorted(set(matched.values()), reverse=True)
    assert len(weights) == 2
    assert weights[0] > weights[1]
    # figurant/ignored surfaces excluded
    joined = " ".join(matched.keys()).lower()
    assert "guard" not in joined
    assert "rando" not in joined


def test_score_sentence_accepts_entity_index_kwarg():
    score = _score_sentence("Celaena drew her blade.", 0, 5, entity_index=())
    assert isinstance(score, float)


def test_score_sentence_boosts_important_entity_mention():
    index = build_entity_importance_index(
        [{"canonical_name": "Celaena", "aliases": [], "importance": "principal"}]
    )
    base = _score_sentence("Celaena drew her blade.", 2, 5)
    boosted = _score_sentence("Celaena drew her blade.", 2, 5, entity_index=index)
    assert boosted > base


def test_score_sentence_matches_whole_word_only():
    index = build_entity_importance_index(
        [{"canonical_name": "Cel", "aliases": [], "importance": "principal"}]
    )
    # "Celaena" must not match the shorter important entity "Cel"
    base = _score_sentence("Celaena drew her blade.", 2, 5)
    boosted = _score_sentence("Celaena drew her blade.", 2, 5, entity_index=index)
    assert boosted == base


def test_summarize_chapter_prioritizes_important_entities():
    # Two comparable candidate sentences; only one mentions the principal entity.
    content = (
        "The morning fog rolled across the stony courtyard below. "
        "Celaena crossed the courtyard toward the northern tower. "
    )
    index = build_entity_importance_index(
        [{"canonical_name": "Celaena", "aliases": [], "importance": "principal"}]
    )
    cfg = ChapterSummaryConfig(max_bullets=1)
    without = summarize_chapter({"id": "c1", "title": "T", "content": content}, config=cfg)
    with_idx = summarize_chapter(
        {"id": "c1", "title": "T", "content": content}, config=cfg, entity_index=index
    )
    assert "Celaena" in with_idx["summary_bullets"][0]
    # Degradation: empty index leaves behavior unchanged.
    same = summarize_chapter({"id": "c1", "title": "T", "content": content}, config=cfg, entity_index=())
    assert same["summary_bullets"] == without["summary_bullets"]


def test_load_classified_entities_reads_file(tmp_path):
    p = tmp_path / "entities_classified.json"
    entity = {
        "canonical_name": "X",
        "type": "PERSON",
        "total_mentions": 5,
        "chapters_present": 2,
        "importance": "principal",
    }
    p.write_text(json.dumps({"entities": [entity], "relationships": [], "stats": {}, "narrator": None}))
    ents = _load_classified_entities(p)
    assert ents == [
        {**entity, "source_ids": [], "aliases": [], "relevant": True, "alias_resolution": None}
    ]


def test_load_classified_entities_missing_file_returns_empty(tmp_path):
    assert _load_classified_entities(tmp_path / "nope.json") == []


def test_save_chapter_summaries_accepts_mixed_temporal_context(tmp_path):
    """LLM mode emits temporal_context "mixed" — the validated save path must not raise."""
    from scripts.chapter_summary import _save_chapter_summaries

    out_file = tmp_path / "chapter_summaries.json"
    _save_chapter_summaries(
        {
            "Chapter 1": {
                "chapter_id": "C1.xhtml",
                "chapter_title": "Chapter 1",
                "summary_bullets": ["Celaena remembers the salt mines."],
                "temporal_context": "mixed",
            }
        },
        out_file,
    )
    saved = json.loads(out_file.read_text(encoding="utf-8"))
    assert saved["chapter_summaries"]["Chapter 1"]["temporal_context"] == "mixed"
