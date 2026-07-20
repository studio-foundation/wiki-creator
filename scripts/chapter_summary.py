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

import argparse
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
from typing import get_args

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from wiki_creator.paths import BookPaths, book_paths_from_yaml
from wiki_creator.lang import load_lang_config, infer_language
from wiki_creator.pov_attribution import attribute_pov_character
from wiki_creator import studio_io
from wiki_creator.chapters import is_frontmatter_chapter
from wiki_creator.types import TEMPORAL, ChapterSummary, ClassifiedBundle

_TEMPORAL_VALUES = frozenset(get_args(TEMPORAL))

_FALLBACK_BULLET = "No reliable summary available for this chapter."
_MIN_SENTENCE_CHARS = 25
_MAX_SENTENCE_CHARS = 320
_DEFAULT_MAX_BULLETS = 3
_DEFAULT_LLM_MODEL = "qwen2.5"
_DEFAULT_LLM_TIMEOUT_SECONDS = 45
_VALID_SUMMARY_MODES = {"extractive", "llm"}
OLLAMA_URL = "http://localhost:11434"

_AGENTS_DIR = PROJECT_ROOT / ".studio" / "agents"

# STU-433: extractive sentence-selection bonus per entity importance tier.
# Numeric weights only — the entity surface forms come from entity-classification
# output, not a hardcoded vocabulary.
_IMPORTANCE_WEIGHTS = {"principal": 0.6, "secondary": 0.3}
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


def build_entity_importance_index(
    entities: list[dict] | None,
    weights: dict[str, float] | None = None,
) -> tuple[tuple[re.Pattern[str], float], ...]:
    """Compile a whole-word matcher per important entity surface form.

    Returns a tuple of (compiled_pattern, weight). Entities whose importance
    tier is not in ``weights`` (figurant/ignored/unknown) are skipped, so an
    empty or absent classification degrades to no weighting.
    """
    weights = weights or _IMPORTANCE_WEIGHTS
    surface_to_weight: dict[str, float] = {}
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        weight = weights.get(str(entity.get("importance", "")).strip().lower())
        if not weight:
            continue
        forms = [entity.get("canonical_name", "")] + list(entity.get("aliases") or [])
        for form in forms:
            key = re.sub(r"\s+", " ", str(form or "").strip().lower())
            if len(key) < 2:
                continue
            if surface_to_weight.get(key, 0.0) < weight:
                surface_to_weight[key] = weight

    index: list[tuple[re.Pattern[str], float]] = []
    for surface, weight in surface_to_weight.items():
        # Collapse escaped spaces to \s+ so multi-word names tolerate whitespace runs.
        body = re.escape(surface).replace(r"\ ", r"\s+")
        pattern = re.compile(r"(?<!\w)" + body + r"(?!\w)")
        index.append((pattern, weight))
    return tuple(index)


def _load_classified_entities(path: Path) -> list[dict]:
    """Load validated entities from an entities_classified.json file.

    Absent or unreadable file degrades to [] (chapter-summary is a pre-step
    of wiki-resolution, so entity-classification may not have run yet); a
    schema-drift key propagates ArtifactSchemaError.
    """
    if not path.exists():
        return []
    try:
        bundle = studio_io.load_artifact(path, ClassifiedBundle)
    except (OSError, json.JSONDecodeError):
        return []
    # dict-only boundary: build_entity_importance_index (pure) consumes plain
    # entity dicts — validated on load above.
    return studio_io.to_dict(bundle.entities)


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


def _detect_temporal_context(content: str, flashback_cues: tuple[str, ...] = ()) -> str:
    if not flashback_cues:
        return "unknown"
    lowered = (content or "").lower()
    for cue in flashback_cues:
        if cue.lower() in lowered:
            return "flashback"
    return "present"


def _resolve_pov_fields(
    chapter: dict,
    thought_markers: tuple[str, ...] = (),
    exclusion_words: tuple[str, ...] = (),
    llm_item_result: dict | None = None,
) -> dict:
    """Resolve the canonical per-chapter POV field set.

    Gate: deterministic attribution wins when it is `high`; otherwise use the
    LLM item's `pov_character` when present; otherwise abstain (`null`).
    """
    pov = str(chapter.get("pov", "unknown") or "unknown")
    fields = {
        "pov": pov,
        "pov_confidence": str(chapter.get("pov_confidence", "unknown") or "unknown"),
        "pov_character": None,
        "pov_character_confidence": "low",
        "pov_character_source": "none",
    }
    if pov not in ("first_person", "third_limited"):
        return fields

    det = attribute_pov_character(chapter.get("content", ""), pov, thought_markers, exclusion_words)
    if det["pov_character"] and det["pov_character_confidence"] == "high":
        fields["pov_character"] = det["pov_character"]
        fields["pov_character_confidence"] = "high"
        fields["pov_character_source"] = "deterministic"
        return fields

    if isinstance(llm_item_result, dict):
        llm_name = str(llm_item_result.get("pov_character") or "").strip()
        if llm_name:
            fields["pov_character"] = llm_name
            fields["pov_character_confidence"] = str(
                llm_item_result.get("pov_character_confidence", "medium") or "medium"
            )
            fields["pov_character_source"] = "llm"
            return fields

    return fields


def _score_sentence(
    sentence: str,
    index: int,
    total: int,
    action_cues: tuple[str, ...] = (),
    entity_index: tuple[tuple[re.Pattern[str], float], ...] = (),
) -> float:
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
    for cue in action_cues:
        if cue in lowered:
            action_bonus += 0.15

    # STU-433: favor sentences mentioning entities classified principal/secondary.
    entity_bonus = 0.0
    if entity_index:
        matched = [weight for pat, weight in entity_index if pat.search(lowered)]
        if matched:
            entity_bonus = max(matched) + 0.1 * (len(matched) - 1)

    dialogue_penalty = 0.75 if _looks_dialogue_heavy(sentence) else 0.0
    return (proper_nouns / token_count) * 2.0 + unique_ratio + position_bonus * 0.25 + action_bonus + entity_bonus - dialogue_penalty


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


def _summarize_chapter_extractive(chapter: dict, cfg: ChapterSummaryConfig, method: str = "extractive", seed_flags: list[str] | None = None, action_cues: tuple[str, ...] = (), flashback_cues: tuple[str, ...] = (), thought_markers: tuple[str, ...] = (), exclusion_words: tuple[str, ...] = (), entity_index: tuple[tuple[re.Pattern[str], float], ...] = ()) -> dict:
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
            key=lambda item: _score_sentence(item[1], item[0], len(sentences), action_cues, entity_index),
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
        "temporal_context": _detect_temporal_context(chapter.get("content", ""), flashback_cues),
        "flashback_anchor": None,
        **_resolve_pov_fields(chapter, thought_markers, exclusion_words),
    }


def summarize_chapter(chapter: dict, config: ChapterSummaryConfig | None = None, action_cues: tuple[str, ...] = (), flashback_cues: tuple[str, ...] = (), thought_markers: tuple[str, ...] = (), exclusion_words: tuple[str, ...] = (), entity_index: tuple[tuple[re.Pattern[str], float], ...] = ()) -> dict:
    cfg = config or ChapterSummaryConfig()
    if cfg.mode == "llm":
        llm_result = _call_llm_summary(
            chapter=chapter,
            model=cfg.llm_model,
            timeout_seconds=cfg.llm_timeout_seconds,
            max_bullets=cfg.max_bullets,
        )
        return summarize_chapter_from_item_result(chapter, llm_result, config=cfg, action_cues=action_cues, flashback_cues=flashback_cues, thought_markers=thought_markers, exclusion_words=exclusion_words, entity_index=entity_index)
    return _summarize_chapter_extractive(chapter, cfg, action_cues=action_cues, flashback_cues=flashback_cues, thought_markers=thought_markers, exclusion_words=exclusion_words, entity_index=entity_index)


def _run_chapter_summary_item(*, chapter: dict, config: ChapterSummaryConfig) -> dict:
    return _run_studio_chapter_summary_item(chapter=chapter, config=config)


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
    run_id = studio_io.extract_run_id(result.stdout or "")
    run_payload = studio_io.extract_first_json_object(result.stdout or "")
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

    payload = studio_io.stage_output_from_stdout(result.stdout or "", "chapter-summary-item")
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


def _save_llm_debug_artifact(debug_dir: Path, chapter: dict, llm_result: dict) -> None:
    error = str(llm_result.get("error") or "").strip()
    if error not in _LLM_DEBUGGABLE_ERRORS and not error.startswith("studio_"):
        return

    debug_dir.mkdir(parents=True, exist_ok=True)
    chapter_id = str(chapter.get("id", "")).strip()
    chapter_title = str(chapter.get("title", "")).strip()
    filename = f"{studio_io.slugify_filename(chapter_id or chapter_title)}.json"
    payload = {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "error": error,
        "raw_response": str(llm_result.get("raw_response", "") or ""),
        "run_metadata": llm_result.get("run_metadata"),
    }
    with open(debug_dir / filename, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def summarize_chapters(chapters: list[dict], config: ChapterSummaryConfig | None = None, action_cues: tuple[str, ...] = (), flashback_cues: tuple[str, ...] = (), thought_markers: tuple[str, ...] = (), exclusion_words: tuple[str, ...] = (), entity_index: tuple[tuple[re.Pattern[str], float], ...] = ()) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for chapter in chapters:
        if is_frontmatter_chapter(chapter):
            continue
        key = _chapter_key(chapter)
        if not key:
            continue
        result[key] = summarize_chapter(chapter, config=config, action_cues=action_cues, flashback_cues=flashback_cues, thought_markers=thought_markers, exclusion_words=exclusion_words, entity_index=entity_index)
    return result


def summary_prompt_fingerprint(config: "ChapterSummaryConfig", language: str) -> str:
    """Fingerprint the prompt + config every summary in the artifact was written under.

    The resume state is the output artifact itself, keyed per chapter — so before
    STU-589 an edited chapter-summary prompt, a mode flip (extractive↔llm) or a
    changed max_bullets/model replayed the stale summaries silently. This busts the
    whole resume when any of them moves (chapter content is the per-item input and
    already re-keys itself)."""
    return studio_io.prompt_fingerprint(
        agents=[
            _AGENTS_DIR / "chapter-summary.agent.yaml",
            _AGENTS_DIR / "chapter-summary-validator.agent.yaml",
        ],
        config={
            "mode": config.mode,
            "max_bullets": config.max_bullets,
            "llm_model": config.llm_model,
            "language": language,
        },
    )


def _stored_summary_fingerprint(output_file: Path) -> str | None:
    if not output_file.exists():
        return None
    try:
        with open(output_file, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data.get("prompt") if isinstance(data, dict) else None


def _save_chapter_summaries(
    chapter_summaries: dict[str, dict], output_file: Path, fingerprint: str | None = None
) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    records = {key: ChapterSummary(**summary) for key, summary in chapter_summaries.items()}
    payload = studio_io.to_dict(records)
    studio_io.from_dict(dict[str, ChapterSummary], payload)  # self-check: never write off-schema
    out: dict = {"chapter_summaries": payload}
    if fingerprint is not None:
        out["prompt"] = fingerprint
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


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


def _is_failed_llm_summary(summary: dict) -> bool:
    """A summary standing in for a failed LLM call — the extractive fallback or
    the stub. Kept as the current answer, but retried on resume rather than
    frozen (persist-as-you-go: a failure must not permanently freeze its unit)."""
    method = summary.get("summary_method")
    if method == "extractive_fallback":
        return True
    return method == "llm" and summary.get("summary_bullets") == [_FALLBACK_BULLET]


def summarize_chapters_incrementally(
    chapters: list[dict],
    *,
    output_file: Path,
    debug_dir: Path | None = None,
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
    flashback_cues: tuple[str, ...] = (),
    thought_markers: tuple[str, ...] = (),
    exclusion_words: tuple[str, ...] = (),
    entity_index: tuple[tuple[re.Pattern[str], float], ...] = (),
    fingerprint: str | None = None,
) -> dict[str, dict]:
    retry_failed_llm = (config or ChapterSummaryConfig()).mode == "llm"
    # STU-589: a stored fingerprint that no longer matches means the prompt or config
    # changed since these summaries were written — discard the resume so every chapter
    # re-summarizes instead of replaying answers the old prompt produced.
    existing = (
        {}
        if fingerprint is not None and _stored_summary_fingerprint(output_file) != fingerprint
        else _load_existing_chapter_summaries(output_file)
    )
    result = {
        key: value
        for key, value in existing.items()
        if isinstance(key, str) and isinstance(value, dict) and _is_summary_complete(value)
        and not (retry_failed_llm and _is_failed_llm_summary(value))
    }

    pending = [
        chapter for chapter in chapters
        if not is_frontmatter_chapter(chapter) and _chapter_key(chapter) and _chapter_key(chapter) not in result
    ]
    total = len(result) + len(pending)
    done = len(result)

    try:
        from tqdm import tqdm
        bar = tqdm(pending, total=total, initial=done, unit="ch", desc="chapter-summary", file=sys.stderr)
    except ImportError:
        bar = None

    for chapter in pending:
        key = _chapter_key(chapter)
        if (config or ChapterSummaryConfig()).mode == "llm":
            item_result = _run_chapter_summary_item(chapter=chapter, config=(config or ChapterSummaryConfig()))
            if debug_dir is not None and isinstance(item_result, dict) and item_result.get("error"):
                _save_llm_debug_artifact(debug_dir, chapter, item_result)
            result[key] = summarize_chapter_from_item_result(chapter, item_result, config=config, action_cues=action_cues, flashback_cues=flashback_cues, thought_markers=thought_markers, exclusion_words=exclusion_words, entity_index=entity_index)
        else:
            result[key] = summarize_chapter(chapter, config=config, action_cues=action_cues, flashback_cues=flashback_cues, thought_markers=thought_markers, exclusion_words=exclusion_words, entity_index=entity_index)
        _save_chapter_summaries(result, output_file, fingerprint)
        if bar is not None:
            bar.set_postfix(chapter=key[:40])
            bar.update(1)

    if bar is not None:
        bar.close()

    return result


def summarize_chapter_from_item_result(
    chapter: dict,
    item_result: dict | list[str],
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
    flashback_cues: tuple[str, ...] = (),
    thought_markers: tuple[str, ...] = (),
    exclusion_words: tuple[str, ...] = (),
    entity_index: tuple[tuple[re.Pattern[str], float], ...] = (),
) -> dict:
    cfg = config or ChapterSummaryConfig()
    if isinstance(item_result, list):
        llm_bullets = item_result
        llm_error = None if llm_bullets else "llm_invalid_response"
        temporal_context = "unknown"
        flashback_anchor = None
    else:
        llm_bullets = _sanitize_bullets(item_result.get("summary_bullets"), cfg.max_bullets)
        llm_error = item_result.get("error") or None
        temporal_context = item_result.get("temporal_context") or _detect_temporal_context(chapter.get("content", ""), flashback_cues)
        if temporal_context not in _TEMPORAL_VALUES:
            temporal_context = "unknown"
        flashback_anchor = item_result.get("flashback_anchor") or None

    _pov = _resolve_pov_fields(
        chapter,
        thought_markers,
        exclusion_words,
        llm_item_result=item_result if isinstance(item_result, dict) else None,
    )

    if llm_bullets:
        return {
            "chapter_id": str(chapter.get("id", "")).strip(),
            "chapter_title": str(chapter.get("title", "")).strip(),
            "summary_bullets": llm_bullets,
            "summary_method": "llm",
            "quality_flags": [],
            "temporal_context": temporal_context,
            "flashback_anchor": flashback_anchor,
            **_pov,
        }
    if cfg.llm_fallback_to_extractive:
        return _summarize_chapter_extractive(
            chapter,
            cfg,
            method="extractive_fallback",
            seed_flags=([llm_error] if llm_error else []) + ["fallback_used"],
            action_cues=action_cues,
            flashback_cues=flashback_cues,
            thought_markers=thought_markers,
            exclusion_words=exclusion_words,
            entity_index=entity_index,
        )
    return {
        "chapter_id": str(chapter.get("id", "")).strip(),
        "chapter_title": str(chapter.get("title", "")).strip(),
        "summary_bullets": [_FALLBACK_BULLET],
        "summary_method": "llm",
        "quality_flags": [llm_error] if llm_error else [],
        "temporal_context": "unknown",
        "flashback_anchor": None,
        **_pov,
    }


def _read_epub_data(paths: BookPaths) -> dict:
    """epub_data.json, written by the epub-parse stage of wiki-extraction."""
    path = paths.processing / "epub_data.json"
    if not path.exists():
        print(
            f"[ERROR] {path} not found. Run wiki-extraction first:\n"
            "  studio run wiki-extraction --input-file <book.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def _main_from_book(book_path: str) -> None:
    """Standalone entry point: reads epub_data.json from disk, runs summarization."""
    paths = book_paths_from_yaml(book_path)
    chapters = _read_epub_data(paths).get("chapters", [])

    with open(book_path, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}

    spacy_model = book_cfg.get("spacy_model", "en_core_web_lg")
    export_categories = book_cfg.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    lang_config = load_lang_config(language)
    action_cues = tuple(lang_config.get("action_cues", ()))
    flashback_cues = tuple(lang_config.get("flashback_cues", ()))
    thought_markers = tuple(lang_config.get("third_person_thought_markers", ()))
    exclusion_words = tuple(
        set(lang_config.get("noise_words", []))
        | set(lang_config.get("false_positive_words", []))
        | set(lang_config.get("determiners", []))
        | set(lang_config.get("role_words", []))
        | set(lang_config.get("pronouns", []))
    )

    generation_cfg = book_cfg.get("generation", {})
    summary_cfg = generation_cfg.get("chapter_summary", {}) if isinstance(generation_cfg, dict) else {}
    mode = str(summary_cfg.get("mode", "extractive")).strip().lower()
    if mode not in _VALID_SUMMARY_MODES:
        mode = "extractive"
    llm_model_raw = summary_cfg.get("llm_model", _DEFAULT_LLM_MODEL)
    llm_model = str(llm_model_raw).strip() if llm_model_raw is not None else _DEFAULT_LLM_MODEL
    config = ChapterSummaryConfig(
        mode=mode,
        max_bullets=int(summary_cfg.get("max_bullets", 8)),
        llm_model=llm_model or _DEFAULT_LLM_MODEL,
        llm_timeout_seconds=_as_positive_int(summary_cfg.get("llm_timeout_seconds"), _DEFAULT_LLM_TIMEOUT_SECONDS),
        llm_fallback_to_extractive=_as_bool(summary_cfg.get("llm_fallback_to_extractive", True), True),
    )

    # STU-433: opportunistically weight summaries toward important entities when a
    # prior entity-classification exists. Absent on a fresh run (chapter-summary is a
    # pre-step of wiki-resolution), so this degrades cleanly to no weighting.
    entity_index = build_entity_importance_index(
        _load_classified_entities(paths.processing / "entities_classified.json")
    )

    out_file = paths.processing / "chapter_summaries.json"
    debug_dir = paths.processing / "chapter_summary_llm_debug"
    summarize_chapters_incrementally(
        chapters,
        output_file=out_file,
        debug_dir=debug_dir,
        config=config,
        action_cues=action_cues,
        flashback_cues=flashback_cues,
        thought_markers=thought_markers,
        exclusion_words=exclusion_words,
        entity_index=entity_index,
        fingerprint=summary_prompt_fingerprint(config, language),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate chapter summaries.")
    parser.add_argument("--book", help="Path to book YAML (standalone mode, reads chapters.json from disk)")
    args, _ = parser.parse_known_args()

    if args.book:
        _main_from_book(args.book)
        return

    # Studio stdin mode (legacy — called from wiki-preparation pipeline)
    payload = studio_io.read_payload()
    paths = studio_io.paths_from_payload(payload)
    chapters = _read_epub_data(paths).get("chapters", [])
    config = _chapter_summary_config_from_payload(payload)

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    spacy_model = ctx.get("spacy_model", "en_core_web_lg")
    export_categories = ctx.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    lang_config = load_lang_config(language)
    action_cues = tuple(lang_config.get("action_cues", ()))
    flashback_cues = tuple(lang_config.get("flashback_cues", ()))
    thought_markers = tuple(lang_config.get("third_person_thought_markers", ()))
    exclusion_words = tuple(
        set(lang_config.get("noise_words", []))
        | set(lang_config.get("false_positive_words", []))
        | set(lang_config.get("determiners", []))
        | set(lang_config.get("role_words", []))
        | set(lang_config.get("pronouns", []))
    )

    # STU-433: weight toward important entities. Degrades to no weighting when
    # the classification artifact is absent.
    classified_entities = _load_classified_entities(paths.processing / "entities_classified.json")
    entity_index = build_entity_importance_index(classified_entities)

    out_file = paths.processing / "chapter_summaries.json"
    debug_dir = paths.processing / "chapter_summary_llm_debug"
    chapter_summaries = summarize_chapters_incrementally(
        chapters,
        output_file=out_file,
        debug_dir=debug_dir,
        config=config,
        action_cues=action_cues,
        flashback_cues=flashback_cues,
        thought_markers=thought_markers,
        exclusion_words=exclusion_words,
        entity_index=entity_index,
        fingerprint=summary_prompt_fingerprint(config, language),
    )
    out = {"chapter_summaries": chapter_summaries}
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
