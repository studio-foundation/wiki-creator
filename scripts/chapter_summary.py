#!/usr/bin/env python3
"""
Stage: chapter-summary (script executor, no LLM)

Build deterministic, extractive chapter summaries from epub-parse output.

Input (Studio stdin):
  previous_outputs["epub-parse"]["chapters"]: [{id, title, content}, ...]

Output (stdout):
  {
    "chapter_summaries": {
      "<chapter_key>": {
        "chapter_id": "...",
        "chapter_title": "...",
        "summary_bullets": ["...", "...", "..."]
      }
    }
  }

Side effects:
  Writes processing_output/chapter_summaries.json.
"""

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import BookPaths, book_paths_from_epub

_FALLBACK_BULLET = "No reliable summary available for this chapter."
_MIN_SENTENCE_CHARS = 25
_MAX_SENTENCE_CHARS = 320
_DEFAULT_MAX_BULLETS = 3
_DEFAULT_LLM_MODEL = "qwen2.5"
_DEFAULT_LLM_TIMEOUT_SECONDS = 45
_VALID_SUMMARY_MODES = {"extractive", "llm"}


@dataclass(frozen=True)
class ChapterSummaryConfig:
    mode: str = "extractive"
    max_bullets: int = _DEFAULT_MAX_BULLETS
    llm_fallback_to_extractive: bool = True
    llm_model: str = _DEFAULT_LLM_MODEL
    llm_timeout_seconds: int = _DEFAULT_LLM_TIMEOUT_SECONDS


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)


def _as_bool(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    return default


def _as_positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return parsed


def _chapter_summary_config_from_payload(payload: dict) -> ChapterSummaryConfig:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    generation_cfg = ctx.get("generation", {}) if isinstance(ctx, dict) else {}
    summary_cfg = generation_cfg.get("chapter_summary", {}) if isinstance(generation_cfg, dict) else {}
    if not isinstance(summary_cfg, dict):
        summary_cfg = {}

    mode = str(summary_cfg.get("mode", "extractive")).strip().lower()
    if mode not in _VALID_SUMMARY_MODES:
        mode = "extractive"

    max_bullets = _as_positive_int(summary_cfg.get("max_bullets"), _DEFAULT_MAX_BULLETS)
    llm_timeout_seconds = _as_positive_int(
        summary_cfg.get("llm_timeout_seconds"),
        _DEFAULT_LLM_TIMEOUT_SECONDS,
    )

    llm_model_raw = summary_cfg.get("llm_model", _DEFAULT_LLM_MODEL)
    llm_model = str(llm_model_raw).strip() if llm_model_raw is not None else ""
    if not llm_model:
        llm_model = _DEFAULT_LLM_MODEL

    llm_fallback_to_extractive = _as_bool(
        summary_cfg.get("llm_fallback_to_extractive", True),
        True,
    )

    return ChapterSummaryConfig(
        mode=mode,
        max_bullets=max_bullets,
        llm_fallback_to_extractive=llm_fallback_to_extractive,
        llm_model=llm_model,
        llm_timeout_seconds=llm_timeout_seconds,
    )


def _chapter_key(chapter: dict) -> str:
    title = (chapter.get("title") or "").strip()
    if title:
        return title
    return str(chapter.get("id", "")).strip()


def _split_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if not normalized:
        return []
    parts = re.split(r"(?<=[.!?])\s+", normalized)
    return [p.strip() for p in parts if p and p.strip()]


def _looks_noisy(sentence: str) -> bool:
    s = sentence.strip()
    if not s:
        return True
    if len(s) < _MIN_SENTENCE_CHARS or len(s) > _MAX_SENTENCE_CHARS:
        return True
    alpha_chars = sum(1 for ch in s if ch.isalpha())
    if alpha_chars < 12:
        return True
    return False


def _score_sentence(sentence: str, index: int, total: int) -> float:
    tokens = re.findall(r"[A-Za-zÀ-ÿ']+", sentence)
    token_count = len(tokens)
    if token_count == 0:
        return float("-inf")

    proper_nouns = sum(1 for t in tokens if t and t[0].isupper())
    unique_ratio = len({t.lower() for t in tokens}) / token_count

    # Light position prior to keep some early context without forcing the first sentence.
    position_bonus = max(0.0, 1.0 - (index / max(total, 1)))
    return (proper_nouns / token_count) * 2.0 + unique_ratio + position_bonus * 0.25


def summarize_chapter(chapter: dict) -> dict:
    chapter_id = str(chapter.get("id", "")).strip()
    chapter_title = str(chapter.get("title", "")).strip()
    sentences = _split_sentences(chapter.get("content", ""))
    candidates = [
        (i, s) for i, s in enumerate(sentences)
        if not _looks_noisy(s)
    ]

    if not candidates:
        bullets = [_FALLBACK_BULLET]
    else:
        ranked = sorted(
            candidates,
            key=lambda item: _score_sentence(item[1], item[0], len(sentences)),
            reverse=True,
        )[:3]
        chosen_idxs = {idx for idx, _ in ranked}
        bullets = [s for i, s in enumerate(sentences) if i in chosen_idxs][:3]
        if not bullets:
            bullets = [_FALLBACK_BULLET]

    return {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "summary_bullets": bullets,
    }


def summarize_chapters(chapters: list[dict]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for chapter in chapters:
        key = _chapter_key(chapter)
        if not key:
            continue
        result[key] = summarize_chapter(chapter)
    return result


def _epub_output_from_payload(payload: dict) -> dict:
    all_outputs = payload.get("all_stage_outputs", {})
    if isinstance(all_outputs, dict):
        stage = all_outputs.get("epub-parse")
        if isinstance(stage, dict) and stage.get("chapters") is not None:
            return stage

    prev_outputs = payload.get("previous_outputs", {})
    if isinstance(prev_outputs, dict):
        stage = prev_outputs.get("epub-parse")
        if isinstance(stage, dict) and stage.get("chapters") is not None:
            return stage

    prev_stage = payload.get("previous_stage_output", {})
    if isinstance(prev_stage, dict) and prev_stage.get("chapters") is not None:
        return prev_stage

    return {}


def main() -> None:
    payload = json.load(sys.stdin)
    epub_data = _epub_output_from_payload(payload)
    chapters = epub_data.get("chapters", [])

    chapter_summaries = summarize_chapters(chapters)
    out = {"chapter_summaries": chapter_summaries}

    paths = _paths_from_payload(payload)
    paths.processing.mkdir(parents=True, exist_ok=True)
    out_file = paths.processing / "chapter_summaries.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
