# Design: STU-282 — Filter intra-entity relationships before classification

**Date:** 2026-03-17
**Issue:** STU-282
**Status:** Approved

## Problem

In `entities_classified.json`, relationships appear between two names that alias-resolution has merged into the same entity. Example: `Captain Westfall ↔ Chaol Westfall → "antagoniste"` (same person). This happens because:

1. `relationship-extraction` runs before `alias-resolution` and records co-occurrences using pre-merge entity IDs.
2. `entity-classification` loads post-merge entities from `alias-resolution` and raw relationships from `relationship-extraction`.
3. No step reconciles the two: an intra-entity pair passes straight through to classification.

`_rewrite_relationships` in `entity_classification.py` already drops `a == b` pairs, but only fires after a programmatic merge — it never sees alias-resolution inter-alias pairs.

## Solution

Add `_filter_intra_entity_relationships(entities, relationships)` in `entity_classification.py`. Call it in `run_studio_mode` right after the relationships list is built from `rel_output`, before `_canonicalize_role_entities`.

### Helper signature

```python
def _filter_intra_entity_relationships(
    entities: list[dict],
    relationships: list[dict],
) -> list[dict]:
    """Drop relationships where both names resolve to the same canonical entity."""
```

### Logic

1. Build `name_to_canonical: dict[str, str]` by iterating over entities: map `canonical_name.lower()` and each `alias.lower()` → `canonical_name`.
2. For each relationship, look up `entity_a` and `entity_b` in the map. Drop the pair if both resolve to the same canonical.
3. Pairs where either name is unknown (not in the map) pass through unchanged.

### Call site

In `run_studio_mode`, after line building `relationships` from `rel_output.get("relationships", [])`:

```python
relationships = _filter_intra_entity_relationships(entities, relationships)
```

## Data flow

```
alias-resolution.entities  +  relationship-extraction.relationships
                          ↓
        _filter_intra_entity_relationships   ← NEW
                          ↓
        _canonicalize_role_entities
        _apply_entity_overrides
        classify_entities
```

## Tests

File: `tests/test_entity_classification.py`

| Test | Scenario |
|------|----------|
| `test_filter_intra_entity_relationships_drops_canonical_alias_pair` | canonical ↔ alias of same entity → dropped |
| `test_filter_intra_entity_relationships_drops_alias_alias_pair` | alias ↔ alias of same entity → dropped |
| `test_filter_intra_entity_relationships_keeps_cross_entity_pair` | names from different entities → kept |
| `test_filter_intra_entity_relationships_keeps_unknown_name` | one name not in entity list → kept (pass-through) |

## Constraints

- No schema changes to any pipeline stage.
- `alias_resolution.py` and `relationship_extraction.py` are untouched.
- `_rewrite_relationships` is untouched.
