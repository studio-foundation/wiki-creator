# Design: STU-285 — Canonicalize relationships after alias-resolution

## Problem

Relationships are extracted using raw text names before alias-resolution merges entities.
After alias-resolution, the same real-world pair can appear under multiple string forms:

- `Captain Westfall / Celaena` + `Chaol Westfall / Celaena` + `Chaol / Celaena` → 3 entries for one pair
- `Crown Prince / Dorian Havilliard` → same entity on both sides (unresolved alias)
- `Brullo / Master` → `Master` = Weapons Master = Brullo (same person)

`_filter_intra_entity_relationships` (STU-282) only drops pairs where **both** sides are already
aliases of the same entity at string-comparison time. It does not rewrite names to canonical form,
so non-self-relation duplicates (three different spellings of Chaol all relating to Celaena) survive.

## Root Cause

`run_studio_mode()` in `entity_classification.py`:
1. Reads entities from `alias-resolution` output (post-merge, canonical names + aliases)
2. Reads relationships from `relationship-extraction` output (pre-merge, raw text names)
3. Calls `_filter_intra_entity_relationships` — only filters the self-relation edge case
4. Passes relationships downstream without canonicalizing names

## Solution: Option A — `_build_alias_merge_map` + reuse `_rewrite_relationships`

### New pure function

```python
def _build_alias_merge_map(entities: list[dict]) -> dict[str, str]:
    """Map every alias (and canonical_name) to its canonical_name."""
    m: dict[str, str] = {}
    for e in entities:
        canonical = e.get("canonical_name", "")
        if not canonical:
            continue
        for name in [canonical] + list(e.get("aliases", [])):
            if name:
                m[name] = canonical
    return m
```

### Call site change in `run_studio_mode()`

After stripping `sample_contexts`/`chapters`, add:

```python
alias_map = _build_alias_merge_map(entities)
relationships = _rewrite_relationships(relationships, alias_map)
relationships = _filter_intra_entity_relationships(entities, relationships)  # safety net
```

### Why this works

`_rewrite_relationships` already:
- Rewrites `entity_a` / `entity_b` via the map (falling back to the original name if not found)
- Drops self-relations (a == b after rewrite)
- Deduplicates by `tuple(sorted((a, b)))`
- Aggregates `cooccurrence_count` across merged pairs

`_filter_intra_entity_relationships` is kept afterward as a safety net for any edge cases
not covered by the merge map (e.g., entities not in alias-resolution output).

## Acceptance Criteria

- Zero relationships where `entity_a` or `entity_b` is a non-canonical alias
- Zero self-relations (entity related to itself)
- Zero duplicate pairs `(canonical_a, canonical_b)`
- `cooccurrence_count` of merged duplicates is the sum of all merged entries

## Scope

Only `scripts/entity_classification.py` is modified:
- Add `_build_alias_merge_map` (pure function, testable)
- 2-line change in `run_studio_mode()`
- New unit tests for `_build_alias_merge_map`
- New integration-style test for the full canonicalization + dedup flow
