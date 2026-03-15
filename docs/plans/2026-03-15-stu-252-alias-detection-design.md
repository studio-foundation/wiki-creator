# STU-252 Alias Detection Design

**Date:** 2026-03-15
**Issue:** [STU-252](https://linear.app/studioag/issue/STU-252)
**Status:** Approved

## Problem

Named aliases (orthographically distinct proper names referring to the same PERSON entity) are not detected by the current pipeline. The `alias_resolution.py` script has partial implementations (`_detect_pattern_match`, `_detect_reveal_signal`) but lacks a clean public interface and uses keyword matching instead of a real token-window scan for co-occurrence.

## Scope

Option A: refactor internals, expose public interface, fix co-occurrence strategy. No cross-script Union-Find integration (deferred to follow-up if chain aliases become a real problem).

## Data Types

Add `AliasPair` TypedDict to `alias_resolution.py`:

```python
class AliasPair(TypedDict):
    entity_a: str                              # canonical_name
    entity_b: str                              # canonical_name
    confidence: Literal["high", "medium"]
    source: Literal["pattern", "cooccurrence"]
    snippet: str
```

## Public Interface

```python
def detect_named_aliases(mentions: dict[str, list[str]], text: str) -> list[AliasPair]:
    ...
```

- `mentions`: `{entity_name: [context snippets]}`
- `text`: raw concatenated book text (used for token-window scan)
- Returns a flat list of `AliasPair`

`resolve_aliases` remains the pipeline integration point and calls `detect_named_aliases` internally.

## Strategy 1 — Pattern Matching (confidence: high)

Keep existing `_PATTERN_TEMPLATES`. Add missing patterns:

- `r"\bformerly {b}\b"` — covers "formerly Y" shorthand
- `r"\bnée {b}\b"` — covers "née Y"
- `r"\bknown as {b}\b"` — covers "I am known as Y"

Returns `AliasPair` with `confidence="high"`, `source="pattern"`.

## Strategy 2 — Token-Window Co-occurrence (confidence: medium)

Replace `_detect_reveal_signal` with a proper window scan:

1. Tokenize `text` by whitespace into a flat list of tokens with positions
2. Build index: for each entity name, record all token positions where it appears
3. For each pair (entity_a, entity_b), count distinct 300-token windows where both appear
4. Threshold: 2+ distinct windows → emit `AliasPair` with `confidence="medium"`, `source="cooccurrence"`
5. `snippet`: first matching window trimmed to ~200 chars
6. `_REVEAL_WORDS` retained as optional signal boost (does not change confidence level)

## Testing

- Unit tests for `detect_named_aliases` directly (both strategies)
- Existing `resolve_aliases` tests preserved
- Manual validation on *Le Jeu de l'Ange* to check for false positives (not automated)

## Out of Scope

- Union-Find integration with `entity_clustering.py` (transitive chain aliases)
- LLM confirmation pass (already exists as optional hook in `resolve_aliases`)
