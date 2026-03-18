# STU-282: Filter Intra-Entity Relationships Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Drop relationships where both `entity_a` and `entity_b` are names (canonical or alias) of the same post-alias-resolution entity, before entity classification runs.

**Architecture:** Add a pure helper `_filter_intra_entity_relationships(entities, relationships)` in `entity_classification.py`. Call it in `run_studio_mode` right after the relationships list is built from `rel_output`, before `_canonicalize_role_entities`. No schema changes, no other files touched.

**Tech Stack:** Python, pytest. No new dependencies.

---

### Task 1: Write failing tests for `_filter_intra_entity_relationships`

**Files:**
- Modify: `tests/test_entity_classification.py` (append at end of file)

**Step 1: Write the four failing tests**

Append to `tests/test_entity_classification.py`:

```python
# ---------------------------------------------------------------------------
# STU-282 — _filter_intra_entity_relationships
# ---------------------------------------------------------------------------
from scripts.entity_classification import _filter_intra_entity_relationships


def test_filter_intra_entity_drops_canonical_alias_pair():
    """canonical ↔ alias of the same entity must be dropped."""
    entities = [
        {"canonical_name": "Chaol Westfall", "aliases": ["Captain Westfall", "Chaol"], "type": "PERSON"},
        {"canonical_name": "Celaena Sardothien", "aliases": ["Laena"], "type": "PERSON"},
    ]
    relationships = [
        {"entity_a": "Chaol Westfall", "entity_b": "Captain Westfall", "cooccurrence_count": 12},
    ]
    assert _filter_intra_entity_relationships(entities, relationships) == []


def test_filter_intra_entity_drops_alias_alias_pair():
    """Two aliases of the same entity must be dropped."""
    entities = [
        {"canonical_name": "Dorian Havilliard", "aliases": ["Crown Prince", "Dorian"], "type": "PERSON"},
    ]
    relationships = [
        {"entity_a": "Crown Prince", "entity_b": "Dorian", "cooccurrence_count": 8},
    ]
    assert _filter_intra_entity_relationships(entities, relationships) == []


def test_filter_intra_entity_keeps_cross_entity_pair():
    """Relationship between two different entities must be kept."""
    entities = [
        {"canonical_name": "Chaol Westfall", "aliases": ["Captain Westfall"], "type": "PERSON"},
        {"canonical_name": "Celaena Sardothien", "aliases": ["Laena"], "type": "PERSON"},
    ]
    rel = {"entity_a": "Chaol Westfall", "entity_b": "Celaena Sardothien", "cooccurrence_count": 30}
    result = _filter_intra_entity_relationships(entities, [rel])
    assert result == [rel]


def test_filter_intra_entity_keeps_unknown_name():
    """If one name is not in the entity list, the relationship passes through."""
    entities = [
        {"canonical_name": "Chaol Westfall", "aliases": ["Captain Westfall"], "type": "PERSON"},
    ]
    rel = {"entity_a": "Chaol Westfall", "entity_b": "UnknownEntity", "cooccurrence_count": 5}
    result = _filter_intra_entity_relationships(entities, [rel])
    assert result == [rel]
```

**Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_entity_classification.py::test_filter_intra_entity_drops_canonical_alias_pair tests/test_entity_classification.py::test_filter_intra_entity_drops_alias_alias_pair tests/test_entity_classification.py::test_filter_intra_entity_keeps_cross_entity_pair tests/test_entity_classification.py::test_filter_intra_entity_keeps_unknown_name -v
```

Expected: 4 × `FAILED` with `ImportError: cannot import name '_filter_intra_entity_relationships'`

**Step 3: Commit the failing tests**

```bash
git add tests/test_entity_classification.py
git commit -m "test(entity-classification): failing tests for _filter_intra_entity_relationships (STU-282)"
```

---

### Task 2: Implement `_filter_intra_entity_relationships`

**Files:**
- Modify: `scripts/entity_classification.py` — add the helper just before `_rewrite_relationships` (around line 374)

**Step 1: Insert the helper**

Add this function immediately before `def _rewrite_relationships` in `scripts/entity_classification.py`:

```python
def _filter_intra_entity_relationships(
    entities: list[dict],
    relationships: list[dict],
) -> list[dict]:
    """Drop relationships where both names resolve to the same canonical entity.

    After alias-resolution, two names that were separate pre-merge entities may
    now be the canonical_name and an alias of the same entity.  Keeping such
    pairs would produce absurd self-relations in the wiki output (STU-282).
    """
    name_to_canonical: dict[str, str] = {}
    for entity in entities:
        canonical = entity.get("canonical_name", "")
        if not canonical:
            continue
        name_to_canonical[canonical.lower()] = canonical
        for alias in entity.get("aliases", []):
            if alias:
                name_to_canonical[alias.lower()] = canonical

    result = []
    for rel in relationships:
        a = name_to_canonical.get((rel.get("entity_a") or "").lower())
        b = name_to_canonical.get((rel.get("entity_b") or "").lower())
        if a and b and a == b:
            continue
        result.append(rel)
    return result
```

**Step 2: Run the tests to verify they pass**

```bash
pytest tests/test_entity_classification.py::test_filter_intra_entity_drops_canonical_alias_pair tests/test_entity_classification.py::test_filter_intra_entity_drops_alias_alias_pair tests/test_entity_classification.py::test_filter_intra_entity_keeps_cross_entity_pair tests/test_entity_classification.py::test_filter_intra_entity_keeps_unknown_name -v
```

Expected: 4 × `PASSED`

**Step 3: Run full test suite to check for regressions**

```bash
pytest -q
```

Expected: all previously passing tests still pass.

**Step 4: Commit the implementation**

```bash
git add scripts/entity_classification.py
git commit -m "feat(entity-classification): add _filter_intra_entity_relationships (STU-282)"
```

---

### Task 3: Wire into `run_studio_mode`

**Files:**
- Modify: `scripts/entity_classification.py:run_studio_mode` — one line after the `relationships` list is built (currently around line 558)

**Step 1: Add the call**

In `run_studio_mode`, find this block (right after `relationships = [...]`):

```python
    relationships = [
        {k: v for k, v in r.items() if k not in ("sample_contexts", "chapters")}
        for r in rel_output.get("relationships", [])
    ]
```

Add immediately after it:

```python
    relationships = _filter_intra_entity_relationships(entities, relationships)
```

**Step 2: Run the full test suite**

```bash
pytest -q
```

Expected: all tests pass.

**Step 3: Commit**

```bash
git add scripts/entity_classification.py
git commit -m "feat(entity-classification): filter intra-entity relationships in run_studio_mode (STU-282)"
```

---

### Task 4: Verify with live data (manual smoke test)

If you have access to a processed run for `01-throne-of-glass`:

```bash
# Check that no relationship has entity_a == entity_b canonical
python - <<'EOF'
import json
with open("library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/entities_classified.json") as f:
    data = json.load(f)

entities = data["entities"]
name_to_canonical = {}
for e in entities:
    c = e.get("canonical_name", "")
    name_to_canonical[c.lower()] = c
    for a in e.get("aliases", []):
        if a:
            name_to_canonical[a.lower()] = c

bad = [
    r for r in data["relationships"]
    if (ca := name_to_canonical.get((r.get("entity_a") or "").lower()))
    and (cb := name_to_canonical.get((r.get("entity_b") or "").lower()))
    and ca == cb
]
print(f"Intra-entity relationships found: {len(bad)}")
for r in bad:
    print(f"  {r['entity_a']} ↔ {r['entity_b']}")
EOF
```

Expected: `Intra-entity relationships found: 0`

This smoke test requires a pre-existing `entities_classified.json` regenerated after Task 3. If none exists, skip and rely on unit tests.
