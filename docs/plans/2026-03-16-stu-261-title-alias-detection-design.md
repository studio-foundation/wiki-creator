# STU-261 — Title-alias detection via `role_words`

**Date:** 2026-03-16
**Status:** Approved
**Issue:** https://linear.app/studioag/issue/STU-261

---

## Problem

`alias_resolution.py` has two detection paths before the LLM confirmer:

1. `_detect_pattern_match` — pattern phrases ("also known as", "formerly known as", etc.)
2. `_detect_reveal_signal` — co-occurrence of reveal words ("another name", "real name", etc.)

Title-based aliases (`"Captain Westfall"` → `"Chaol Westfall"`, `"Crown Prince"` → `"Dorian Havilliard"`) produce no reveal signal in the text. The LLM confirmer is never reached for these pairs, so they persist as duplicate entities in `wiki_pages.json`.

`use_llm: true` was merged in STU-261 (commit `abf6edd`) and is confirmed active in batches post-fix. The bug is architectural, not a configuration issue.

---

## Root Cause

In `resolve_aliases()` ([alias_resolution.py:463–469](../../scripts/alias_resolution.py)):

```python
reveal = _detect_reveal_signal(entity, candidate, persons_full, ...)
if not reveal:
    continue  # LLM never called for title-aliases
```

---

## Design

### Approach chosen: Direct LLM path for title-aliases (Approach 1)

Add `_detect_title_alias()` as a third detection path that routes matching pairs directly to the LLM confirmer, without requiring a reveal signal.

```
_detect_pattern_match  → direct merge  (high confidence, existing)
_detect_title_alias    → LLM confirmer (medium confidence, NEW)
_detect_reveal_signal  → LLM confirmer (medium confidence, existing)
nothing                → skip
```

### Why not merge directly (Approach 2)?

Deterministic title-alias merging would be fragile across books. `"Captain Flint"` + `"Flint"` would merge silently in a different novel. The LLM always confirms before any merge.

---

## Changes

### 1. Book YAML — add `crown prince` to `role_words`

`library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`:

```yaml
role_words:
  - crown prince   # added: covers "Crown Prince" → "Dorian Havilliard"
  - captain
  - prince
  ...
```

`role_words` is already per-book, so this is the right place. A generic heuristic in code would duplicate what the YAML already encodes correctly.

### 2. New function `_detect_title_alias`

```python
def _detect_title_alias(
    entity_a: dict,
    entity_b: dict,
    role_words: list[str],
) -> dict | None:
```

**Logic:**
- For each `(name_a, name_b)` pair from `_entity_names(entity_a)` × `_entity_names(entity_b)`
- For each `role` in `role_words`: if `name.lower().startswith(role + " ")`
- `remainder = name[len(role)+1:].lower()`
- If `remainder` appears in the other entity's canonical name → return evidence dict

**Returns:** `{"method": "title_alias", "confidence": "medium", "snippet": "<name_a> / <name_b>"}` or `None`.

### 3. Wire into `resolve_aliases()`

New parameter: `role_words: list[str] = []`

Insert between `_detect_pattern_match` and `_detect_reveal_signal`:

```python
title = _detect_title_alias(entity, candidate, role_words)
if title:
    if llm_confirmer is None:
        stats["ambiguous_pairs"] += 1
        continue
    stats["llm_attempts"] += 1
    try:
        decision = llm_confirmer({...}) or {}
    except Exception:
        stats["llm_failed"] += 1
        stats["ambiguous_pairs"] += 1
        continue
    if decision.get("same_person"):
        # merge with method="title_alias"
        ...
    stats["ambiguous_pairs"] += 1
    continue
```

### 4. Propagate `role_words` from `main()`

```python
role_words = ctx.get("role_words", [])
result = resolve_aliases(
    entities, persons_full=persons_full, narrator=narrator,
    llm_confirmer=llm_confirmer, reveal_words=reveal_words,
    role_words=role_words,   # new
)
```

### 5. Stats

Add `"title_alias": 0` to `_empty_stats()["merges_by_method"]`.

---

## Acceptance Criteria (from issue)

- [ ] Batches confirmed re-generated post-fix (already true — confirmed 2026-03-16)
- [ ] `Captain Westfall` absent from `wiki_pages.json` (merged into `Chaol Westfall`)
- [ ] `Crown Prince` absent from `wiki_pages.json` (merged into `Dorian Havilliard`)
- [ ] No false positives on `PLACE` or `ORG` entities (detection scoped to PERSON pairs, unchanged)
- [ ] `King of Adarlan` treated correctly — it is a legitimate separate entity (Dorian's father), not a duplicate

---

## Tests

| Test | Input | Expected |
|---|---|---|
| Unit: match | `"Captain Westfall"` + `"Chaol Westfall"` + `["captain"]` | evidence dict returned |
| Unit: match | `"Crown Prince"` + `"Dorian Havilliard"` + `["crown prince"]` | evidence dict returned |
| Unit: no match | `"Princess Nehemia"` + `"Dorian Havilliard"` + `["princess"]` | `None` (remainder "nehemia" not in "dorian havilliard") |
| Unit: no match | `"Captain"` (no remainder) + `"Chaol Westfall"` + `["captain"]` | `None` (empty remainder) |
| Integration | `resolve_aliases()` with mocked LLM returning `same_person: true` for title pair | one entity merged, stats updated |
| Integration | `resolve_aliases()` with `llm_confirmer=None` and title pair | `ambiguous_pairs` incremented, no merge |
