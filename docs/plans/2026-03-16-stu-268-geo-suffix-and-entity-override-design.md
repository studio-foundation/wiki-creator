# STU-268 — `_normalize_entity_type`: geo-suffix check + book YAML overrides

**Date:** 2026-03-16
**Issue:** https://linear.app/studioag/issue/STU-268
**File:** `scripts/entity_classification.py`

---

## Problem

`_normalize_entity_type` applies a conservative PERSON retag: it only retags to PLACE
if the name is in `_KNOWN_WORLD_PLACES` or matches a geopolitical regex. Two cases escape:

1. **Geo-suffix in name** — "White Fang Mountains": contains "mountains" (a structural
   geographic suffix) but the PERSON block never checks name tokens.
2. **Opaque artifact name** — "Nothung" (the king's sword): no heuristic detects named
   artifacts whose names carry no structural clue.

---

## Approach

**Option B (chosen):** Name-token geo-suffix check (automatic) + book YAML override map
(explicit, for opaque cases like artifacts).

---

## Design

### 1. New constant `_GEO_SUFFIXES`

```python
_GEO_SUFFIXES = frozenset({
    "mountains", "mountain", "sea", "ocean", "river", "lake", "forest",
    "coast", "bay", "gulf", "isle", "island", "valley", "desert",
    "plains", "peak", "pass", "strait", "fjord", "cape",
})
```

Distinct from `_GEO_KEYWORDS` (contextual words like "kingdom", "capital").
`_GEO_SUFFIXES` are structural components of proper geographic names.

---

### 2. PERSON block patch in `_normalize_entity_type`

After the `_KNOWN_WORLD_PLACES` check, before the geo-pattern regex:

```python
name_tokens = set(re.split(r"[\s'\-]+", lowered))
if name_tokens & _GEO_SUFFIXES:
    return "PLACE"
```

"White Fang Mountains" → tokens `{"white", "fang", "mountains"}` → hit → PLACE.

---

### 3. New parameter: `entity_type_overrides`

`_normalize_entity_type` gains:

```python
entity_type_overrides: dict[str, str] | None = None
```

At the top of the function, before all other logic:

```python
if entity_type_overrides:
    override = entity_type_overrides.get(name) or entity_type_overrides.get(lowered)
    if override:
        return override.upper()
```

`classify_entities` loads this from the book config and passes it through, parallel
to `geo_keywords` and `concept_keywords`.

---

### 4. Book YAML schema addition

```yaml
entity_type_overrides:
  Nothung: OTHER
```

Key: canonical name (case-insensitive lookup). Value: any valid type in `_VALID_TYPES`.

---

### 5. Tests

| Test | Assertion |
|---|---|
| `test_normalize_geo_suffix_retags_person_to_place` | "White Fang Mountains" typed PERSON → PLACE |
| `test_normalize_geo_suffix_single_token` | e.g. "Oakwald Sea" typed PERSON → PLACE |
| `test_normalize_person_no_false_positive_on_blade` | "Blade" (no geo token, no override) → PERSON |
| `test_normalize_entity_type_override_wins` | override `{"Nothung": "OTHER"}` → OTHER regardless of input type |

---

## Out of scope

- Full `_ARTIFACT_SUFFIXES` list (sword, blade, etc.) — too brittle for fantasy names;
  the YAML override is the correct mechanism.
- Any changes to `merge_entities.py`, `wiki_preparation.py`, or downstream scripts.

## Implementation Notes

Section 3 (new `entity_type_overrides` parameter on `_normalize_entity_type`) was superseded during implementation: `_apply_entity_overrides` with `force_type` already existed and runs after `_normalize_entity_type`. Use `entity_overrides.Nothung.force_type: OTHER` in the book YAML — no code change needed.
