# Design: STU-253 — Alias Resolution LLM Pass (Ollama)

**Date:** 2026-03-15
**Issue:** STU-253
**Status:** Approved

## Context

The deterministic heuristics in `alias-resolution` (STU-252) leave ambiguous cases unresolved — entities flagged via `_detect_reveal_signal` but not confirmed. `resolve_aliases` already accepts a `llm_confirmer` callable; this design wires a real Ollama-backed confirmer into `main()`.

## Approach

All changes are confined to `scripts/alias_resolution.py`. No new pipeline stages, no new files.

## Components

### `_pick_snippets(entity, persons_full, n=3) -> list[str]`

Selects up to `n` snippets for an entity from `persons_full`, prioritising those containing the entity's `canonical_name` (better LLM anchoring). Falls back to any available snippet.

### `make_ollama_confirmer(model, url, timeout) -> Callable`

Factory that returns a closure used as `llm_confirmer`. The closure:

1. Calls `_pick_snippets` for each entity (3 snippets each)
2. Formats the prompt (see below)
3. POSTs to `{url}/api/generate` via `urllib` (same pattern as `generate_wiki_pages.py`)
4. Parses response with 3-level fallback: direct `json.loads` → regex `\{[^}]+\}` → `None`
5. Returns `{"same_person": bool, "confidence": str, "evidence": str}` or `None`

### Prompt template

```
Given two character entities from a novel, determine if they refer to the same person.

Entity A: "{name_a}"
Snippets:
- {snippet_1}
- {snippet_2}
- {snippet_3}

Entity B: "{name_b}"
Snippets:
- {snippet_1}
- {snippet_2}
- {snippet_3}

Signal: "{reveal_snippet}"

Reply ONLY with valid JSON:
{"same_person": true/false, "confidence": "high"/"medium"/"low", "evidence": "<one sentence>"}
```

### `_check_ollama_available(url) -> bool`

HEAD request on `{url}/api/tags`, timeout 2s. Returns `False` on any error (connection refused, timeout, HTTP error). Logs a warning when unavailable.

### `main()` changes

Reads from `additional_context`:
- `use_llm: bool` (default: `false`) — opt-in flag
- `llm_model: str` (default: `"mistral"`) — model name

If `use_llm=true` and `_check_ollama_available()` returns `True`, instantiates `make_ollama_confirmer` and passes it to `resolve_aliases`. Otherwise passes `llm_confirmer=None` (current behaviour, no regression).

## Error Handling

- Ollama unavailable → `warn` log, `llm_confirmer=None`, stage completes normally
- LLM response unparseable → confirmer returns `None` → `llm_failed` stat incremented, entity stays unresolved
- LLM says `same_person: false` → `ambiguous_pairs` incremented, no merge
- Any exception in confirmer → caught in `resolve_aliases`, `llm_failed` incremented

## Tests

| Test | What it verifies |
|------|-----------------|
| `test_llm_confirmer_merge` | Mock confirmer returns `same_person: true` → entities merged, `llm_confirmed` = 1 |
| `test_llm_confirmer_skip` | Mock confirmer returns `same_person: false` → no merge, `ambiguous_pairs` = 1 |
| `test_llm_confirmer_failure` | Confirmer raises exception → `llm_failed` = 1, entities unchanged |
| `test_ollama_unavailable` | `_check_ollama_available` returns `False` → confirmer is `None`, warn emitted |
| `test_pick_snippets_prioritises_name` | Snippets containing canonical name are returned first |

## Stats output (unchanged shape, existing fields used)

```json
{
  "llm_attempts": 2,
  "llm_confirmed": 1,
  "llm_failed": 0,
  "ambiguous_pairs": 1
}
```

## Out of scope

- Refactoring `generate_wiki_pages.py` to share `call_ollama`
- New pipeline stage
- Non-Ollama LLM providers
