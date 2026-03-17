# STU-268 — Geo-suffix name-token check in `_normalize_entity_type`

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Retag PERSON entities whose canonical name contains a geographic suffix token (e.g. "Mountains", "Sea") to PLACE; document the existing `entity_overrides.force_type` mechanism for opaque artifact names (e.g. "Nothung").

**Architecture:** Single constant `_GEO_SUFFIXES` added to `scripts/entity_classification.py`. The PERSON block in `_normalize_entity_type` gains a token-set intersection check before the geo-pattern regex. No new function parameters needed — artifact overrides already work via `entity_overrides` in the book YAML (`_apply_entity_overrides` already handles `force_type`).

**Tech Stack:** Python 3.11, pytest, `re` stdlib.

---

### Task 1: Add failing tests for geo-suffix PERSON → PLACE retag

**Files:**
- Modify: `tests/test_entity_classification.py`

**Step 1: Add three failing tests at the end of the file**

```python
def test_normalize_geo_suffix_retags_person_to_place():
    """Name token 'mountains' is a geo-suffix → PERSON retags to PLACE."""
    entity = {
        "canonical_name": "White Fang Mountains",
        "type": "PERSON",
        "source_ids": [],
        "aliases": [],
    }
    new_type = _normalize_entity_type(entity, {}, {}, {}, {})
    assert new_type == "PLACE"


def test_normalize_geo_suffix_single_word_place():
    """Name ending in a geo-suffix token even without context → PLACE."""
    entity = {
        "canonical_name": "Oakwald Sea",
        "type": "PERSON",
        "source_ids": [],
        "aliases": [],
    }
    new_type = _normalize_entity_type(entity, {}, {}, {}, {})
    assert new_type == "PLACE"


def test_normalize_no_false_positive_on_plain_person_name():
    """Name with no geo-suffix tokens stays PERSON."""
    entity = {
        "canonical_name": "Blade",
        "type": "PERSON",
        "source_ids": [],
        "aliases": [],
    }
    new_type = _normalize_entity_type(entity, {}, {}, {}, {})
    assert new_type == "PERSON"
```

**Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_entity_classification.py::test_normalize_geo_suffix_retags_person_to_place tests/test_entity_classification.py::test_normalize_geo_suffix_single_word_place tests/test_entity_classification.py::test_normalize_no_false_positive_on_plain_person_name -v
```

Expected: first two FAIL (`assert "PERSON" == "PLACE"`), third PASS.

**Step 3: Commit the failing tests**

```bash
git add tests/test_entity_classification.py
git commit -m "test(STU-268): add failing tests for geo-suffix PERSON→PLACE retag"
```

---

### Task 2: Add `_GEO_SUFFIXES` constant and patch the PERSON block

**Files:**
- Modify: `scripts/entity_classification.py:47-70` (constants block)
- Modify: `scripts/entity_classification.py:344-355` (PERSON block in `_normalize_entity_type`)

**Step 1: Add `_GEO_SUFFIXES` after the `_GEO_KEYWORDS` block (around line 55)**

Insert after `_GEO_KEYWORDS = frozenset({...})`:

```python
# Structural tokens that appear as part of proper geographic names.
# Distinct from _GEO_KEYWORDS (contextual words like "kingdom", "capital").
_GEO_SUFFIXES = frozenset({
    "mountains", "mountain", "sea", "ocean", "river", "lake", "forest",
    "coast", "bay", "gulf", "isle", "island", "valley", "desert",
    "plains", "peak", "pass", "strait", "fjord", "cape",
})
```

**Step 2: Patch the PERSON block in `_normalize_entity_type`**

Current code (around line 344):
```python
    # Conservative PERSON retag: only with explicit geopolitical evidence.
    if current_type == "PERSON":
        if lowered in _KNOWN_WORLD_PLACES:
            return "PLACE"
        geo_patterns = (
```

Replace with:
```python
    # Conservative PERSON retag: only with explicit geopolitical evidence.
    if current_type == "PERSON":
        if lowered in _KNOWN_WORLD_PLACES:
            return "PLACE"
        name_tokens = set(re.split(r"[\s'\-]+", lowered))
        if name_tokens & _GEO_SUFFIXES:
            return "PLACE"
        geo_patterns = (
```

**Step 3: Run the new tests**

```bash
pytest tests/test_entity_classification.py::test_normalize_geo_suffix_retags_person_to_place tests/test_entity_classification.py::test_normalize_geo_suffix_single_word_place tests/test_entity_classification.py::test_normalize_no_false_positive_on_plain_person_name -v
```

Expected: all three PASS.

**Step 4: Run the full test suite**

```bash
pytest -q
```

Expected: all passing (≥ 288).

**Step 5: Commit**

```bash
git add scripts/entity_classification.py
git commit -m "feat(STU-268): add _GEO_SUFFIXES and patch PERSON block to retag geo-suffix names to PLACE"
```

---

### Task 3: Document `entity_overrides.force_type` for artifact names (Nothung)

**Context:** `_apply_entity_overrides` in `entity_classification.py` already supports
`force_type`. Nothung does NOT need a code change — just a YAML entry in the book config.

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Step 1: Add the override entry**

In `01-throne-of-glass.yaml`, add (or extend) an `entity_overrides` section:

```yaml
entity_overrides:
  Nothung:
    force_type: OTHER
    exclude: true
```

`exclude: true` sets `relevant: false` so Nothung won't generate a wiki page.
`force_type: OTHER` ensures downstream scoring doesn't treat it as a person.

**Step 2: Verify manually (optional)**

```bash
make run-extraction  # or just inspect entities_classified.json after a run
```

Check that `Nothung` no longer appears as `type: PERSON` in
`library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/entities_classified.json`.

**Step 3: Commit**

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "fix(STU-268): exclude Nothung artifact via entity_overrides in book YAML"
```

---

### Task 4: Final verification

**Step 1: Run full test suite**

```bash
pytest -q
```

Expected: all passing.

**Step 2: Update the design doc to reflect that no new parameter was needed**

In `docs/plans/2026-03-16-stu-268-geo-suffix-and-entity-override-design.md`, note:

> Section 3 (new parameter) is superseded: `_apply_entity_overrides` with `force_type` already exists. Use `entity_overrides.Nothung.force_type: OTHER` in the book YAML.

**Step 3: Commit**

```bash
git add docs/plans/2026-03-16-stu-268-geo-suffix-and-entity-override-design.md
git commit -m "docs(STU-268): note that entity_type_overrides parameter is not needed"
```
