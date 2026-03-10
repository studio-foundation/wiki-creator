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
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import BookPaths, book_paths_from_epub
from scripts.entity_extraction import _is_frontmatter_chapter

_FALLBACK_BULLET = "No reliable summary available for this chapter."
_MIN_SENTENCE_CHARS = 25
_MAX_SENTENCE_CHARS = 320
_DEFAULT_MAX_BULLETS = 3
_DEFAULT_LLM_MODEL = "qwen2.5"
_DEFAULT_LLM_TIMEOUT_SECONDS = 45
_VALID_SUMMARY_MODES = {"extractive", "llm"}
_ACTION_CUES = (
    "found", "discovered", "revealed", "warned", "reported", "followed",
    "attacked", "killed", "escaped", "met", "decided", "realized", "uncovered",
    "arrived", "left", "returned", "asked", "opened", "closed",
)
OLLAMA_URL = "http://localhost:11434"
_LLM_DEBUGGABLE_ERRORS = {
    "llm_timeout",
    "llm_http_error",
    "llm_transport_json_parse_error",
    "llm_json_parse_error",
    "llm_missing_summary_bullets",
    "llm_empty_response",
}


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


def _looks_dialogue_heavy(sentence: str) -> bool:
    stripped = sentence.strip()
    if not stripped:
        return False
    if stripped.startswith(("“", "\"", "'")):
        return True

    quote_chars = sum(1 for ch in stripped if ch in {'"', "“", "”", "'"})
    return (quote_chars / max(len(stripped), 1)) > 0.05


def _score_sentence(sentence: str, index: int, total: int) -> float:
    tokens = re.findall(r"[A-Za-zÀ-ÿ']+", sentence)
    token_count = len(tokens)
    if token_count == 0:
        return float("-inf")

    proper_nouns = sum(1 for t in tokens if t and t[0].isupper())
    unique_ratio = len({t.lower() for t in tokens}) / token_count

    # Light position prior to keep some early context without forcing the first sentence.
    position_bonus = max(0.0, 1.0 - (index / max(total, 1)))
    lowered = sentence.lower()
    action_bonus = 0.0
    for cue in _ACTION_CUES:
        if cue in lowered:
            action_bonus += 0.15

    dialogue_penalty = 0.75 if _looks_dialogue_heavy(sentence) else 0.0
    return (proper_nouns / token_count) * 2.0 + unique_ratio + position_bonus * 0.25 + action_bonus - dialogue_penalty


def _sanitize_bullets(raw: object, max_bullets: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    cleaned: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        bullet = re.sub(r"\s+", " ", item).strip()
        if not bullet:
            continue
        cleaned.append(bullet)
        if len(cleaned) >= max_bullets:
            break
    return cleaned


def _parse_llm_summary_response_text(response_text: str, max_bullets: int) -> tuple[list[str], str | None]:
    text = str(response_text or "").strip()
    if not text:
        return [], "llm_empty_response"

    decoder = json.JSONDecoder()
    response_json = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            response_json = candidate
            break

    if response_json is None:
        return [], "llm_json_parse_error"

    bullets = _sanitize_bullets(response_json.get("summary_bullets"), max_bullets)
    if not bullets:
        return [], "llm_missing_summary_bullets"
    return bullets, None


def _call_llm_summary(*, chapter: dict, model: str, timeout_seconds: int, max_bullets: int) -> dict:
    chapter_title = str(chapter.get("title", "")).strip() or str(chapter.get("id", "")).strip() or "Untitled chapter"
    chapter_content = str(chapter.get("content", "")).strip()
    if not chapter_content:
        return {"summary_bullets": [], "error": "llm_empty_chapter"}

    prompt = (
        "Summarize this novel chapter into concise wiki-context bullets.\n"
        f"Return ONLY valid JSON as an object: {{\"summary_bullets\": [\"...\"]}}.\n"
        f"Use at most {max_bullets} bullets. No quotes unless essential. No invented facts.\n"
        f"Chapter title: {chapter_title}\n"
        "Chapter text:\n"
        f"{chapter_content}"
    )
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1},
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            payload = json.loads(resp.read())
    except TimeoutError:
        return {"summary_bullets": [], "error": "llm_timeout", "raw_response": ""}
    except socket.timeout:
        return {"summary_bullets": [], "error": "llm_timeout", "raw_response": ""}
    except urllib.error.URLError:
        return {"summary_bullets": [], "error": "llm_http_error", "raw_response": ""}
    except json.JSONDecodeError:
        return {"summary_bullets": [], "error": "llm_transport_json_parse_error", "raw_response": ""}

    response_text = str(payload.get("response", "")).strip()
    bullets, error = _parse_llm_summary_response_text(response_text, max_bullets)
    return {"summary_bullets": bullets, "error": error, "raw_response": response_text}


def _summarize_chapter_extractive(chapter: dict, cfg: ChapterSummaryConfig, method: str = "extractive", seed_flags: list[str] | None = None) -> dict:
    chapter_id = str(chapter.get("id", "")).strip()
    chapter_title = str(chapter.get("title", "")).strip()
    sentences = _split_sentences(chapter.get("content", ""))
    candidates = [
        (i, s) for i, s in enumerate(sentences)
        if not _looks_noisy(s)
    ]

    quality_flags: list[str] = list(seed_flags or [])
    if not candidates:
        bullets = [_FALLBACK_BULLET]
        quality_flags.append("low_signal")
    else:
        ranked = sorted(
            candidates,
            key=lambda item: _score_sentence(item[1], item[0], len(sentences)),
            reverse=True,
        )[: cfg.max_bullets]
        chosen_idxs = {idx for idx, _ in ranked}
        bullets = [s for i, s in enumerate(sentences) if i in chosen_idxs][: cfg.max_bullets]
        if not bullets:
            bullets = [_FALLBACK_BULLET]
            quality_flags.append("low_signal")

    return {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "summary_bullets": bullets,
        "summary_method": method,
        "quality_flags": quality_flags,
    }


def summarize_chapter(chapter: dict, config: ChapterSummaryConfig | None = None) -> dict:
    cfg = config or ChapterSummaryConfig()
    if cfg.mode == "llm":
        llm_result = _call_llm_summary(
            chapter=chapter,
            model=cfg.llm_model,
            timeout_seconds=cfg.llm_timeout_seconds,
            max_bullets=cfg.max_bullets,
        )
        return summarize_chapter_from_item_result(chapter, llm_result, config=cfg)
    return _summarize_chapter_extractive(chapter, cfg)


def _run_chapter_summary_item(*, chapter: dict, config: ChapterSummaryConfig) -> dict:
    return _run_studio_chapter_summary_item(chapter=chapter, config=config)


def _extract_first_json_object(text: str) -> dict | None:
    decoder = json.JSONDecoder()
    for i, ch in enumerate(str(text or "")):
        if ch != "{":
            continue
        try:
            candidate, _ = decoder.raw_decode(text[i:])
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            return candidate
    return None


def _studio_run_log_path(run_id: str) -> Path | None:
    runs_dir = PROJECT_ROOT / ".studio" / "runs"
    run_id = str(run_id or "").strip()
    matches = sorted(runs_dir.glob(f"*-{run_id}.jsonl"))
    if not matches and run_id:
        matches = sorted(runs_dir.glob(f"*-{run_id[:8]}.jsonl"))
    if not matches:
        return None
    return matches[-1]


def _extract_stage_output_from_run_payload(run_payload: dict, stage_name: str) -> dict | None:
    stages = run_payload.get("stages", [])
    if not isinstance(stages, list):
        return None
    for stage in stages:
        if not isinstance(stage, dict):
            continue
        if stage.get("stage_name") != stage_name:
            continue
        if stage.get("status") != "success":
            continue
        output = stage.get("output")
        if isinstance(output, dict):
            return output
    return None


def _load_studio_stage_output(run_id: str, stage_name: str) -> dict | None:
    log_path = _studio_run_log_path(run_id)
    if log_path is None or not log_path.exists():
        return None

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") != "stage_complete":
                continue
            if event.get("stage") != stage_name:
                continue
            if event.get("status") != "success":
                continue
            output = event.get("output")
            if isinstance(output, dict):
                return output
    return None


def _chapter_summary_item_input(chapter: dict, config: ChapterSummaryConfig) -> dict:
    return {
        "chapter_id": str(chapter.get("id", "")).strip(),
        "chapter_title": str(chapter.get("title", "")).strip(),
        "chapter_content": str(chapter.get("content", "")).strip(),
        "max_bullets": config.max_bullets,
    }


def _run_studio_chapter_summary_item(*, chapter: dict, config: ChapterSummaryConfig) -> dict:
    item_input = _chapter_summary_item_input(chapter, config)
    timeout_seconds = max(config.llm_timeout_seconds * 4, 120)

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = [
        "studio",
        "run",
        "chapter-summary-item",
        "--input-file",
        input_path,
        "--json",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError:
        return {
            "error": "studio_cli_missing",
            "raw_response": "",
            "run_metadata": {"command": cmd},
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "error": "studio_run_timeout",
            "raw_response": (exc.stdout or "") + ("\n" + exc.stderr if exc.stderr else ""),
            "run_metadata": {"command": cmd, "timeout_seconds": timeout_seconds},
        }
    finally:
        try:
            Path(input_path).unlink(missing_ok=True)
        except OSError:
            pass

    combined_output = (result.stdout or "") + (("\n" + result.stderr) if result.stderr else "")
    run_payload = _extract_first_json_object(result.stdout or "")
    run_id = str((run_payload or {}).get("id") or "").strip()
    run_metadata = {
        "command": cmd,
        "returncode": result.returncode,
        "run_id": run_id or None,
        "status": (run_payload or {}).get("status"),
    }
    if result.returncode != 0:
        return {
            "error": "studio_run_failed",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    if run_payload is None:
        return {
            "error": "studio_output_json_parse_error",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    if not run_id:
        return {
            "error": "studio_run_missing_id",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    payload = _extract_stage_output_from_run_payload(run_payload, "chapter-summary-item")
    if payload is None:
        payload = _load_studio_stage_output(run_id, "chapter-summary-item")
    if payload is None:
        return {
            "error": "studio_run_output_missing",
            "raw_response": combined_output.strip(),
            "run_metadata": run_metadata,
        }

    bullets = _sanitize_bullets(payload.get("summary_bullets"), config.max_bullets)
    if not bullets:
        return {
            "error": "studio_invalid_output",
            "raw_response": combined_output.strip(),
            "run_metadata": {**run_metadata, "payload": payload},
        }

    return {
        "chapter_id": str(payload.get("chapter_id") or item_input["chapter_id"]).strip(),
        "chapter_title": str(payload.get("chapter_title") or item_input["chapter_title"]).strip(),
        "summary_bullets": bullets,
        "run_metadata": run_metadata,
    }


def _slugify_filename(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    slug = slug.strip("._")
    return slug or "untitled"


def _save_llm_debug_artifact(debug_dir: Path, chapter: dict, llm_result: dict) -> None:
    error = str(llm_result.get("error") or "").strip()
    if error not in _LLM_DEBUGGABLE_ERRORS and not error.startswith("studio_"):
        return

    debug_dir.mkdir(parents=True, exist_ok=True)
    chapter_id = str(chapter.get("id", "")).strip()
    chapter_title = str(chapter.get("title", "")).strip()
    filename = f"{_slugify_filename(chapter_id or chapter_title)}.json"
    payload = {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "error": error,
        "raw_response": str(llm_result.get("raw_response", "") or ""),
        "run_metadata": llm_result.get("run_metadata"),
    }
    with open(debug_dir / filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def summarize_chapters(chapters: list[dict], config: ChapterSummaryConfig | None = None) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for chapter in chapters:
        if _is_frontmatter_chapter(chapter):
            continue
        key = _chapter_key(chapter)
        if not key:
            continue
        result[key] = summarize_chapter(chapter, config=config)
    return result


def _save_chapter_summaries(chapter_summaries: dict[str, dict], output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({"chapter_summaries": chapter_summaries}, f, ensure_ascii=False, indent=2)


def _load_existing_chapter_summaries(output_file: Path) -> dict[str, dict]:
    if not output_file.exists():
        return {}
    try:
        with open(output_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    chapter_summaries = data.get("chapter_summaries", {})
    return chapter_summaries if isinstance(chapter_summaries, dict) else {}


def _is_summary_complete(summary: dict) -> bool:
    bullets = summary.get("summary_bullets")
    if not isinstance(bullets, list):
        return False
    return any(isinstance(bullet, str) and bullet.strip() for bullet in bullets)


def summarize_chapters_incrementally(
    chapters: list[dict],
    *,
    output_file: Path,
    debug_dir: Path | None = None,
    config: ChapterSummaryConfig | None = None,
) -> dict[str, dict]:
    result = {
        key: value
        for key, value in _load_existing_chapter_summaries(output_file).items()
        if isinstance(key, str) and isinstance(value, dict) and _is_summary_complete(value)
    }

    for chapter in chapters:
        if _is_frontmatter_chapter(chapter):
            continue
        key = _chapter_key(chapter)
        if not key or key in result:
            continue
        if (config or ChapterSummaryConfig()).mode == "llm":
            item_result = _run_chapter_summary_item(chapter=chapter, config=(config or ChapterSummaryConfig()))
            if debug_dir is not None and isinstance(item_result, dict) and item_result.get("error"):
                _save_llm_debug_artifact(debug_dir, chapter, item_result)
            result[key] = summarize_chapter_from_item_result(chapter, item_result, config=config)
        else:
            result[key] = summarize_chapter(chapter, config=config)
        _save_chapter_summaries(result, output_file)

    return result


def summarize_chapter_from_item_result(
    chapter: dict,
    item_result: dict | list[str],
    config: ChapterSummaryConfig | None = None,
) -> dict:
    cfg = config or ChapterSummaryConfig()
    if isinstance(item_result, list):
        llm_bullets = item_result
        llm_error = None if llm_bullets else "llm_invalid_response"
    else:
        llm_bullets = _sanitize_bullets(item_result.get("summary_bullets"), cfg.max_bullets)
        llm_error = item_result.get("error") or None
    if llm_bullets:
        return {
            "chapter_id": str(chapter.get("id", "")).strip(),
            "chapter_title": str(chapter.get("title", "")).strip(),
            "summary_bullets": llm_bullets,
            "summary_method": "llm",
            "quality_flags": [],
        }
    if cfg.llm_fallback_to_extractive:
        return _summarize_chapter_extractive(
            chapter,
            cfg,
            method="extractive_fallback",
            seed_flags=([llm_error] if llm_error else []) + ["fallback_used"],
        )
    return {
        "chapter_id": str(chapter.get("id", "")).strip(),
        "chapter_title": str(chapter.get("title", "")).strip(),
        "summary_bullets": [_FALLBACK_BULLET],
        "summary_method": "llm",
        "quality_flags": [llm_error] if llm_error else [],
    }


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
    config = _chapter_summary_config_from_payload(payload)

    paths = _paths_from_payload(payload)
    out_file = paths.processing / "chapter_summaries.json"
    debug_dir = paths.processing / "chapter_summary_llm_debug"
    chapter_summaries = summarize_chapters_incrementally(
        chapters,
        output_file=out_file,
        debug_dir=debug_dir,
        config=config,
    )
    out = {"chapter_summaries": chapter_summaries}

    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
