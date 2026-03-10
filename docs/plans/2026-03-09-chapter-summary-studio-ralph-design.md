# Chapter Summary Studio Ralph Design

**Date:** 2026-03-09  
**Scope:** Replace direct Ollama calls in `chapter-summary` with Studio-native per-chapter validation and retry, while preserving incremental save/resume semantics.

## Problem
Current `chapter-summary` LLM mode calls Ollama directly from `scripts/chapter_summary.py`. When the model returns plain strings or malformed JSON, the script can only fallback locally to extractive summaries. Studio and Ralph cannot invalidate and regenerate those responses because, from Studio's perspective, the stage is just a successful script executor.

The required behavior is stricter:
- one chapter per generation unit
- save `chapter_summaries.json` after each chapter
- resume from existing partial output
- use Studio contract validation and Ralph regeneration for invalid LLM responses

## Decision
Adopt a hybrid architecture:
- keep `scripts/chapter_summary.py` as the incremental orchestrator
- replace direct HTTP generation with a nested Studio run per chapter
- add a new item-level Studio pipeline dedicated to one chapter summary
- let Ralph reject and regenerate invalid chapter summary outputs
- preserve extractive fallback and debug artifacts in the outer script

## Architecture
### Outer Orchestrator
`scripts/chapter_summary.py` remains responsible for:
- loading chapters from `epub-parse`
- excluding front/back matter
- resuming from `processing_output/<slug>/chapter_summaries.json`
- saving after each completed chapter
- writing `chapter_summary_llm_debug/*.json` for failed item runs
- falling back to extractive summaries when the nested Studio run fails definitively

### Nested Studio Pipeline
Add a new pipeline, e.g. `.studio/pipelines/chapter-summary-item.pipeline.yaml`, that handles exactly one chapter.

Its input payload contains:
- `chapter_id`
- `chapter_title`
- `chapter_content`
- `max_bullets`
- optional model/runtime config

Its output contract is one validated item:
```json
{
  "chapter_id": "C07.xhtml",
  "chapter_title": "Chapter 7",
  "summary_bullets": ["...", "...", "..."]
}
```

### Ralph Validation
The item pipeline uses a dedicated contract, e.g. `.studio/contracts/chapter-summary-item.contract.yaml`, with strict shape requirements:
- `chapter_id`: non-empty string
- `chapter_title`: non-empty string
- `summary_bullets`: list of 1..N non-empty strings

Ralph handles retries when the LLM returns:
- free-form prose
- fenced JSON with wrong outer shape
- missing `summary_bullets`
- empty bullet arrays

### Save/Resume Semantics
The outer script remains the only writer of `chapter_summaries.json`.

Flow per chapter:
1. Skip if already present and complete in existing file.
2. Run nested Studio pipeline for this chapter.
3. If item output validates, merge into `chapter_summaries`.
4. Save immediately.
5. If item run ultimately fails, log failure artifact, generate extractive fallback, save immediately.

This preserves exact restart semantics: reruns continue from the last successful saved chapter.

## Components
### New Files
- `.studio/pipelines/chapter-summary-item.pipeline.yaml`
- `.studio/contracts/chapter-summary-item.contract.yaml`
- likely `.studio/agents/chapter-summary.agent.yaml`
- possibly a small script-wrapper if Studio needs a preprocessing or load step for item payloads

### Modified Files
- `scripts/chapter_summary.py`
- `tests/test_chapter_summary.py`
- `tests/test_pipeline_configs.py`
- potentially docs referencing available pipelines

## Error Handling
If the nested Studio run fails after Ralph retries:
- outer script writes `processing_output/<slug>/chapter_summary_llm_debug/<chapter_id>.json`
- artifact includes chapter identifiers, failure mode, and any run metadata available
- outer script falls back to extractive mode when configured to do so

If extractive fallback is disabled:
- outer script records a placeholder summary with the final error flag
- still saves incrementally so reruns can inspect progress

## Testing Strategy
### Unit Tests
Extend `tests/test_chapter_summary.py` to verify:
- existing completed chapters are skipped
- nested chapter result is merged and saved immediately
- failed nested run creates debug artifact
- failed nested run falls back extractively

### Pipeline Tests
Extend `tests/test_pipeline_configs.py` to verify:
- new item pipeline parses as valid YAML
- `chapter-summary-item` stage has a contract
- Ralph is configured on the LLM stage

### Integration Checks
Run a one-book chapter-summary pass and confirm:
- malformed LLM outputs are rejected by Studio/Ralph, not silently accepted
- `chapter_summaries.json` grows chapter by chapter
- rerun resumes from partial file

## Non-Goals
- Replacing `wiki_preparation.py` chapter summary consumption
- Removing extractive mode
- Reworking standalone `generate_wiki_pages.py`

## Risks and Mitigations
- **Risk:** Nested Studio runs add orchestration overhead.
  - **Mitigation:** only used in `llm` mode; extractive mode remains cheap.
- **Risk:** Studio run invocation API may be awkward from a script executor.
  - **Mitigation:** isolate run launch/retrieval behind one helper in `chapter_summary.py`.
- **Risk:** Partial nested-run failures leave ambiguous state.
  - **Mitigation:** only outer script writes final aggregate file; nested runs are item-scoped.

## Acceptance Criteria
- `chapter-summary` still saves after each chapter and resumes from partial output.
- Invalid per-chapter LLM outputs are rejected and retried by Studio/Ralph.
- Final aggregate output schema remains backward-compatible for downstream consumers.
- On unrecoverable failure, the script logs debug data and falls back deterministically.
