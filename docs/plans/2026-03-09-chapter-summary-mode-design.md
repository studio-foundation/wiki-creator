# Chapter Summary Dual-Mode Design (Extractive + LLM)

**Date:** 2026-03-09  
**Scope:** `chapter-summary` stage quality and configurability for wiki context usefulness.

## Problem
Current chapter summaries are purely extractive and often pick low-signal fragments (short dialogue snippets, partial quotes, boilerplate). This degrades `chapter_summary_context` in wiki inputs and provides little usable signal to downstream LLM generation.

## Decision
Adopt **dual-mode chapter summaries**:
- Keep deterministic extractive mode (default, low-cost)
- Add optional LLM mode (higher semantic quality)
- Improve extractive mode quality so default output is still useful
- Preserve backward compatibility via `summary_bullets`

## Architecture
### Config
Add nested config under `generation.chapter_summary`:
- `mode`: `extractive` | `llm` (default: `extractive`)
- `max_bullets`: integer (default: `3`)
- `llm_fallback_to_extractive`: boolean (default: `true`)
- `llm_model`: string (optional, used in `llm` mode)
- `llm_timeout_seconds`: integer (optional, default safe timeout)

Keep existing `generation.chapter_summary_max_chapters_per_entity` unchanged (used later in wiki preparation).

### Output Schema
Per chapter output remains keyed in `chapter_summaries`, and keeps:
- `chapter_id`
- `chapter_title`
- `summary_bullets`

Additive metadata:
- `summary_method`: `extractive` | `llm` | `extractive_fallback`
- `quality_flags`: string[] (e.g. `low_signal_dialog_heavy`, `front_matter`, `fallback_used`)

## Behavior
### Improved Extractive Mode
1. Normalize and split chapter text into sentences.
2. Filter/noise handling:
- Remove empty/very short lines and malformed fragments.
- De-prioritize quote-only dialogue snippets.
- Detect likely front-matter/metadata chapters and mark with `quality_flags`.
3. Scoring:
- Reward event/action signals (verbs, causal connectors, entity presence).
- Penalize repetitive or contextless snippets.
4. Coverage-aware selection:
- Prefer bullets spanning early/mid/late chapter windows to avoid redundancy.
5. Rewrite-lite cleanup:
- Minimal normalization for standalone, readable bullets.

### LLM Mode
1. Build constrained prompt with chapter content only.
2. Request strict JSON bullet list (`max_bullets` capped).
3. Enforce no-invention/no-cross-chapter leakage constraints in prompt.
4. Validate response; on parse/quality failure, fallback to extractive when enabled.

## Data Flow and Compatibility
- `scripts/chapter_summary.py` continues writing `processing_output/.../chapter_summaries.json`.
- `scripts/wiki_preparation.py` and `scripts/generate_wiki_pages.py` continue using `summary_bullets` unchanged.
- New metadata fields are additive and optional for downstream use.

## Testing Strategy
### Unit tests (`tests/test_chapter_summary.py`)
- Extractive quality regressions:
  - ignores low-signal dialogue fragments better than current heuristic
  - returns max bullets with non-empty meaningful strings
  - preserves deterministic output
  - handles empty/noise-only content
- Mode selection:
  - `mode=extractive` uses extractive path
  - `mode=llm` uses llm path when response valid
  - llm failure + fallback true returns extractive bullets and `summary_method=extractive_fallback`

### Config/pipeline tests
- Validate new config block parsing/defaulting in chapter summary script.
- Keep pipeline YAML stage shape unchanged (`script` path still plain `.py`).

### Optional integration check
- Run one-book pipeline and inspect sampled chapter summaries for readability and event signal.

## Non-Goals
- Reworking wiki page generation prompts in this change.
- Replacing chapter summary context consumption logic in wiki-preparation.

## Risks and Mitigations
- **Risk:** LLM nondeterminism.
  - **Mitigation:** strict JSON format, validation, deterministic fallback.
- **Risk:** Token/runtime overhead.
  - **Mitigation:** default to extractive; LLM mode opt-in.
- **Risk:** Contract drift.
  - **Mitigation:** preserve `summary_bullets`; additive fields only.

## Acceptance Criteria
- Extractive mode outputs materially more informative bullets than current baseline on representative chapters.
- LLM mode can be enabled per book config without breaking existing pipelines.
- Fallback behavior is explicit and test-covered.
- Existing downstream consumers continue to function without code changes.
