# STU-285: Canonicalize Relationships After Alias-Resolution

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** After alias-resolution merges entities, rewrite all relationship names to their canonical form and deduplicate/aggregate the resulting pairs.

**Architecture:** Add a pure function `_build_alias_merge_map(entities)` in `entity_classification.py` that maps every alias to its canonical name, then call it with the existing `_rewrite_relationships` helper in `run_studio_mode()`. `_rewrite_relationships` already handles dedup + count aggregation — we just need to wire the alias map in.

**Tech Stack:** Python 3.11+, pytest, no new dependencies.

---

### Task 1: Add `_build_alias_merge_map` with TDD

**Files:**
- Modify: `scripts/entity_classification.py` — add new pure function after `_filter_intra_entity_relationships` (around line 401)
- Modify: `tests/test_entity_classification.py` — add tests for `_build_alias_merge_map`

**Context:** Open `scripts/entity_classification.py`. The function `_filter_intra_entity_relationships` ends around line 401. New function goes right after it. `_rewrite_relationships` is at line 404 for reference on how it consumes a merge map.

---

**Step 1: Add the import in the test file**

Open `tests/test_entity_classification.py`. Find the import block at the top (around line 1–15). Add `_build_alias_merge_map` to the existing import from `entity_classification`:

```python
from scripts.entity_classification import (
    ...,  # existing imports
    _build_alias_merge_map,
)
```

---

**Step 2: Write failing tests**

Add these tests at the end of `tests/test_entity_classification.py`:

```python
# STU-285 — _build_alias_merge_map

def test_build_alias_merge_map_maps_canonical_to_itself():
    entities = [{"canonical_name": "Chaol Westfall", "aliases": []}]
    result = _build_alias_merge_map(entities)
    assert result["Chaol Westfall"] == "Chaol Westfall"


def test_build_alias_merge_map_maps_aliases_to_canonical():
    entities = [{"canonical_name": "Chaol Westfall", "aliases": ["Chaol", "Captain Westfall"]}]
    result = _build_alias_merge_map(entities)
    assert result["Chaol"] == "Chaol Westfall"
    assert result["Captain Westfall"] == "Chaol Westfall"


def test_build_alias_merge_map_multiple_entities():
    entities = [
        {"canonical_name": "Celaena Sardothien", "aliases": ["Laena"]},
        {"canonical_name": "Chaol Westfall", "aliases": ["Chaol"]},
    ]
    result = _build_alias_merge_map(entities)
    assert result["Laena"] == "Celaena Sardothien"
    assert result["Chaol"] == "Chaol Westfall"
    assert len(result) == 4  # 2 canonicals + 2 aliases


def test_build_alias_merge_map_skips_empty_canonical():
    entities = [{"canonical_name": "", "aliases": ["Ghost"]}]
    result = _build_alias_merge_map(entities)
    assert result == {}


def test_build_alias_merge_map_skips_empty_aliases():
    entities = [{"canonical_name": "Dorian", "aliases": ["", None]}]
    result = _build_alias_merge_map(entities)
    assert "Dorian" in result
    assert "" not in result
    assert None not in result
```

---

**Step 3: Run tests to verify they fail**

```bash
pytest tests/test_entity_classification.py -k "build_alias_merge_map" -v
```

Expected: `ImportError` or `FAILED` — `_build_alias_merge_map` does not exist yet.

---

**Step 4: Implement `_build_alias_merge_map`**

In `scripts/entity_classification.py`, add right after `_filter_intra_entity_relationships` (after line 401):

```python
def _build_alias_merge_map(entities: list[dict]) -> dict[str, str]:
    """Map every alias (and canonical_name) to its canonical_name.

    Used to canonicalize relationship names after alias-resolution so that
    'Chaol', 'Captain Westfall', and 'Chaol Westfall' all rewrite to the
    canonical, and duplicate pairs are aggregated by _rewrite_relationships.
    """
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

---

**Step 5: Run tests to verify they pass**

```bash
pytest tests/test_entity_classification.py -k "build_alias_merge_map" -v
```

Expected: 5 tests PASSED.

---

**Step 6: Commit**

```bash
git add scripts/entity_classification.py tests/test_entity_classification.py
git commit -m "feat(entity-classification): add _build_alias_merge_map (STU-285)"
```

---

### Task 2: Wire canonicalization into `run_studio_mode()` with TDD

**Files:**
- Modify: `scripts/entity_classification.py:585-589` — add alias_map + rewrite call in `run_studio_mode()`
- Modify: `tests/test_entity_classification.py` — add integration test for the full dedup flow

**Context:** `run_studio_mode()` is at line 565. The relevant block is lines 585–589:

```python
relationships = [
    {k: v for k, v in r.items() if k not in ("sample_contexts", "chapters")}
    for r in rel_output.get("relationships", [])
]
relationships = _filter_intra_entity_relationships(entities, relationships)
```

We add two lines between the list comprehension and the existing filter call.

---

**Step 1: Write failing integration test**

This test exercises the full `run_studio_mode()` dedup behaviour by driving it via `_build_alias_merge_map` + `_rewrite_relationships` (unit-level, no stdin needed).

Add to `tests/test_entity_classification.py`:

```python
# STU-285 — alias canonicalization + dedup integration

def test_alias_canonicalization_deduplicates_relationships():
    """Three alias spellings of the same character-pair collapse to one entry."""
    from scripts.entity_classification import _rewrite_relationships

    entities = [
        {"canonical_name": "Chaol Westfall", "aliases": ["Chaol", "Captain Westfall"]},
        {"canonical_name": "Celaena Sardothien", "aliases": ["Laena"]},
    ]
    relationships = [
        {"entity_a": "Captain Westfall", "entity_b": "Celaena", "cooccurrence_count": 3},
        {"entity_a": "Chaol", "entity_b": "Laena", "cooccurrence_count": 7},
        {"entity_a": "Chaol Westfall", "entity_b": "Celaena Sardothien", "cooccurrence_count": 10},
    ]
    alias_map = _build_alias_merge_map(entities)
    result = _rewrite_relationships(relationships, alias_map)

    assert len(result) == 1
    assert result[0]["entity_a"] == "Celaena Sardothien"
    assert result[0]["entity_b"] == "Chaol Westfall"
    assert result[0]["cooccurrence_count"] == 20  # 3 + 7 + 10


def test_alias_canonicalization_drops_self_relations():
    """A relationship where both sides are aliases of the same entity is dropped."""
    from scripts.entity_classification import _rewrite_relationships

    entities = [
        {"canonical_name": "Dorian Havilliard", "aliases": ["Crown Prince", "Prince Dorian"]},
    ]
    relationships = [
        {"entity_a": "Crown Prince", "entity_b": "Dorian Havilliard", "cooccurrence_count": 5},
    ]
    alias_map = _build_alias_merge_map(entities)
    result = _rewrite_relationships(relationships, alias_map)
    assert result == []
```

---

**Step 2: Run tests to verify they pass without code change**

```bash
pytest tests/test_entity_classification.py -k "alias_canonicalization" -v
```

Expected: PASSED — these tests call `_build_alias_merge_map` + `_rewrite_relationships` directly, which already exist. This confirms the primitives behave correctly before we wire them in.

---

**Step 3: Wire into `run_studio_mode()`**

In `scripts/entity_classification.py`, find the block at lines 585–589 in `run_studio_mode()`:

```python
    relationships = [
        {k: v for k, v in r.items() if k not in ("sample_contexts", "chapters")}
        for r in rel_output.get("relationships", [])
    ]
    relationships = _filter_intra_entity_relationships(entities, relationships)
```

Replace with:

```python
    relationships = [
        {k: v for k, v in r.items() if k not in ("sample_contexts", "chapters")}
        for r in rel_output.get("relationships", [])
    ]
    # STU-285: canonicalize alias names → canonical_name, then deduplicate and aggregate
    alias_map = _build_alias_merge_map(entities)
    relationships = _rewrite_relationships(relationships, alias_map)
    relationships = _filter_intra_entity_relationships(entities, relationships)
```

---

**Step 4: Run full test suite**

```bash
pytest -q
```

Expected: all previously passing tests still pass (no regressions). The new tests added in Task 1 and Task 2 also pass.

---

**Step 5: Commit**

```bash
git add scripts/entity_classification.py tests/test_entity_classification.py
git commit -m "feat(entity-classification): canonicalize relationships via alias map (STU-285)"
```

---

### Task 3: Final verification

**Step 1: Run the full suite one more time**

```bash
pytest -q
```

Expected: all tests pass (485 + new tests).

**Step 2: Verify acceptance criteria manually (optional)**

If you have a local run of the pipeline, check `entities_classified.json`:
- No `entity_a` / `entity_b` that appears in any entity's `aliases` list
- No pair where `entity_a == entity_b`
- No duplicate `(entity_a, entity_b)` pairs

**Step 3: Commit if any cleanup needed, then push**

```bash
git push
```
