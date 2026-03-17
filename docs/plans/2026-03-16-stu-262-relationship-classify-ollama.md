# STU-262: Fix relationship classification — switch to Ollama, activate by default

**Date:** 2026-03-16
**Issue:** https://linear.app/studioag/issue/STU-262

## Problem

All relationships produced by `relationship_extraction.py` have `relationship_type: null`. Two root causes:

1. **Not activated:** `classify: true` is absent from the book YAML. Classification is gated on this flag in the pipeline stdin-parsing block.
2. **Wrong backend:** `classify_relationships()` calls `anthropic.Anthropic()` (Claude Haiku). The project runs Ollama Mistral. Without an Anthropic API key, every pair silently fails with a `[WARN]`, and all fields remain null.

## Design

### 1. `classify_relationships()` — replace Anthropic with Ollama

Add a private `_call_ollama_json()` helper (inline, no new shared utility — scripts are standalone). The function signature gains `model` and `ollama_url`:

```python
def classify_relationships(
    relationships: list[dict],
    model: str = "mistral",
    ollama_url: str = "http://localhost:11434",
) -> list[dict]:
```

**Availability check:** Before iterating pairs, do a HEAD/GET to `ollama_url/api/tags`. If unreachable, log `[ERROR] Ollama not available — classification skipped` and return relationships unchanged. This makes the failure explicit instead of 15 silent per-pair warnings.

**Per-pair error handling:** Keep existing pattern — log `[WARN]` to stderr, append nulls, don't crash.

**Prompt:** Unchanged (French, same 4 fields). JSON response parsed with `json.loads`; parse failure → nulls for that pair.

### 2. Pipeline mode — read model/url from context

In the pipeline stdin block (around line 1145), read from `additional_context` YAML:
- `llm_model` (default `"mistral"`) → passed as `model`
- `ollama_url` (default `"http://localhost:11434"`) → passed as `ollama_url`

Same pattern as `alias_resolution.py`.

### 3. Book YAML — add `classify: true`

```yaml
# library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
classify: true   # alongside existing use_llm: true
```

### 4. Test mode

`--classify` CLI path calls `classify_relationships()` with defaults. No change to invocation.

### 5. Tests

- Update any test that mocks `anthropic` for classification → mock Ollama HTTP instead.
- Add test: when Ollama is unreachable, `classify_relationships()` returns relationships unchanged (no crash, no exception).

## Acceptance criteria (from STU-262)

- [ ] Celaena↔Chaol and Celaena↔Dorian have non-null `relationship_type` after `make run-resolution`
- [ ] `## Relations` section in Celaena's wiki page has real content
- [ ] Ollama unavailability logs a clear `[ERROR]` instead of silent nulls
