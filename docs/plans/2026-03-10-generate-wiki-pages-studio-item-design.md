# Generate Wiki Pages Studio Item Design

**Date:** 2026-03-10  
**Scope:** Replace direct Ollama calls in `generate_wiki_pages.py` with Studio-native per-entity generation and validation, while preserving incremental save/resume behavior.

## Problem
`scripts/generate_wiki_pages.py` currently calls Ollama directly for each entity. This gives good local resume semantics, but it bypasses Studio-native contract validation and Ralph regeneration. Invalid JSON, placeholder leaks, and malformed pages are handled only by local parsing and heuristics.

The desired behavior is:
- keep `1 entity = 1 save`
- keep resume from existing `wiki_pages.json`
- use Studio and Ralph to regenerate invalid entity outputs
- keep local failed stubs/debug artifacts when Studio ultimately fails

## Decision
Adopt the same hybrid pattern as `chapter-summary`:
- keep `scripts/generate_wiki_pages.py` as the outer incremental orchestrator
- replace direct Ollama generation with one nested Studio run per entity
- introduce a new item-level Studio pipeline dedicated to a single wiki page
- let Ralph validate and retry malformed outputs
- keep final persistence and resume in the outer script

## Architecture
### Outer Orchestrator
`scripts/generate_wiki_pages.py` remains responsible for:
- loading batch files
- iterating entities in batch order
- resuming from existing `processing_output/<slug>/wiki_pages.json`
- saving after each entity
- writing failed stubs when an entity cannot be generated
- logging debug artifacts for failed nested Studio runs

### Nested Studio Pipeline
Add a new pipeline, e.g. `.studio/pipelines/wiki-page-item.pipeline.yaml`, that processes exactly one entity.

Its input should contain:
- `entity`: a single entity bundle in the same shape currently used by `build_prompt`
- `book_title`
- optional generation profile details if needed

Its output should be one validated page object:
```json
{
  "title": "Celaena",
  "importance": "principal",
  "entity_type": "PERSON",
  "infobox_fields": {},
  "content": "## Biographie\n..."
}
```

### Ralph Validation
The nested item pipeline uses a dedicated contract, e.g. `.studio/contracts/wiki-page-item.contract.yaml`, requiring:
- `title`
- `importance`
- `entity_type`
- `infobox_fields`
- `content`

Ralph retries when the model returns:
- plain strings
- malformed JSON
- wrong schema
- empty content

### Save/Resume Semantics
The outer script remains the only writer of `wiki_pages.json`.

Per entity:
1. Skip if already completed in `wiki_pages.json`
2. Run nested Studio page-item pipeline
3. If valid page returned, append it and save immediately
4. If nested run fails, write debug artifact and append failed stub
5. Do not mark failed pages as complete so reruns may retry them later

This preserves the current standalone script’s resumability exactly.

## Components
### New Files
- `.studio/pipelines/wiki-page-item.pipeline.yaml`
- `.studio/contracts/wiki-page-item.contract.yaml`
- `.studio/agents/wiki-page-item.agent.yaml`

### Modified Files
- `scripts/generate_wiki_pages.py`
- `tests/test_generate_wiki_pages.py`
- `tests/test_pipeline_configs.py`

## Data Flow
Current flow:
- batch JSON file -> local prompt construction -> direct Ollama call -> local parse -> append to `wiki_pages.json`

New flow:
- batch JSON file -> outer script picks one entity -> nested Studio item run -> validated page object -> append to `wiki_pages.json`

The outer `wiki_pages.json` format remains unchanged:
```json
{"pages": [...]}
```

## Error Handling
If nested Studio run fails:
- outer script records a debug artifact per entity in `processing_output/<slug>/wiki_page_item_debug/`
- artifact includes entity title, error code, raw run response, and run metadata
- outer script appends a failed stub page with `_failed: true`

If nested Studio run succeeds but returns content that still violates local post-processing rules:
- outer script may still reject it locally and write a failed stub
- local guards remain a second line of defense

## Testing Strategy
### Unit Tests
Extend `tests/test_generate_wiki_pages.py` to cover:
- nested item runner usage instead of direct Ollama call
- successful page append and save after each entity
- resume behavior from existing `wiki_pages.json`
- failed nested run writes debug artifact and failed stub
- failed pages remain retryable on next run

### Pipeline Tests
Extend `tests/test_pipeline_configs.py` to verify:
- `wiki-page-item.pipeline.yaml` exists and parses
- item stage uses `contract: wiki-page-item`
- item stage has `ralph:` configured
- item agent file exists

### Smoke Check
Run one mock or live Studio item run and verify:
- run metadata is captured
- successful output can be extracted from `studio run --json`

## Non-Goals
- Replacing `pages-export.pipeline.yaml`
- Reworking `writer.agent.yaml` batch orchestration
- Changing `wiki_pages.json` schema

## Risks and Mitigations
- **Risk:** More Studio run overhead per entity.
  - **Mitigation:** only affects generation step; resume semantics minimize rework.
- **Risk:** Studio output extraction differs between stdout and JSONL.
  - **Mitigation:** parse `--json` response first, keep JSONL fallback.
- **Risk:** Duplicate validation between Studio and local script.
  - **Mitigation:** keep local validation as a safety net; it remains cheap.

## Acceptance Criteria
- `generate_wiki_pages.py` still saves after each entity and resumes from partial output.
- Invalid page outputs are retried by Ralph in Studio.
- Final `wiki_pages.json` format remains unchanged.
- Failed nested runs produce debug artifacts and retryable failed stubs.
