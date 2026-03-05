# Split entities by type — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `entities_full.json` with three type-specific files (`persons_full.json`, `places_full.json`, `orgs_full.json`) written by `entity_extraction.py`, and update `writer.agent.yaml` to read them.

**Architecture:** Add a pure `split_by_type(entities_full)` function that partitions the entity registry by type, call it from `main()` to write 3 files, and update the writer agent's system prompt to read those files. `split_entities` and stdout output are unchanged.

**Tech Stack:** Python, spaCy, pytest, Studio agent YAML

---

### Task 1: Add failing tests for `split_by_type`

**Files:**
- Modify: `tests/test_entity_extraction.py`

**Step 1: Add the import at the top of the test file**

The import line is currently:
```python
from scripts.entity_extraction import extract_entities, extract_context, split_entities, KEPT_LABELS, _is_valid_mention, FRONTMATTER_ID_PATTERNS
```

Change it to:
```python
from scripts.entity_extraction import extract_entities, extract_context, split_entities, split_by_type, KEPT_LABELS, _is_valid_mention, FRONTMATTER_ID_PATTERNS
```

**Step 2: Append these tests at the end of `tests/test_entity_extraction.py`**

```python
# --- split_by_type tests ---

def test_split_by_type_separates_by_type(nlp):
    """split_by_type must return separate dicts for PERSON, PLACE, ORG."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London and met the Royal Society."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    by_type = split_by_type(entities_full)

    assert "PERSON" in by_type
    assert "PLACE" in by_type
    assert "ORG" in by_type


def test_split_by_type_entities_are_in_correct_bucket(nlp):
    """Every entity in a bucket must have the matching type."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London and met the Royal Society."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    by_type = split_by_type(entities_full)

    for type_key in ("PERSON", "PLACE", "ORG"):
        for entity_id, entity in by_type[type_key].items():
            assert entity["type"] == type_key, (
                f"[{entity_id}] is in bucket {type_key!r} but has type={entity['type']!r}"
            )


def test_split_by_type_covers_all_entities(nlp):
    """All entities from entities_full must appear in exactly one bucket."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London and met the Royal Society."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    by_type = split_by_type(entities_full)

    all_bucket_ids = set()
    for bucket in by_type.values():
        all_bucket_ids |= set(bucket.keys())

    known_types = {e["type"] for e in entities_full.values()} & {"PERSON", "PLACE", "ORG"}
    expected_ids = {
        eid for eid, e in entities_full.items() if e["type"] in known_types
    }
    assert all_bucket_ids == expected_ids


def test_split_by_type_entities_retain_mentions_by_chapter(nlp):
    """Entities in each bucket must still have mentions_by_chapter."""
    chapters = [
        {"id": "ch01", "title": "Chapter 1", "content": "Alice walked into London."}
    ]
    result = extract_entities(chapters, nlp)
    _, entities_full = split_entities(result["entities"])
    by_type = split_by_type(entities_full)

    for bucket in by_type.values():
        for entity_id, entity in bucket.items():
            assert "mentions_by_chapter" in entity, (
                f"[{entity_id}] missing mentions_by_chapter in split_by_type output"
            )
```

**Step 3: Run tests to verify they fail**

```bash
pytest tests/test_entity_extraction.py -k "split_by_type" -v
```

Expected: 4 ERRORS — `ImportError: cannot import name 'split_by_type'`

**Step 4: Commit the failing tests**

```bash
git add tests/test_entity_extraction.py
git commit -m "test: add failing tests for split_by_type"
```

---

### Task 2: Implement `split_by_type` in `entity_extraction.py`

**Files:**
- Modify: `scripts/entity_extraction.py`

**Step 1: Add the function after `split_entities` (around line 201)**

Insert this block immediately after the `split_entities` function:

```python
def split_by_type(entities_full: dict) -> dict[str, dict]:
    """
    Partition entities_full by entity type.

    Returns a dict with keys "PERSON", "PLACE", "ORG".
    Entities with other types are silently dropped (extraction artifacts).
    """
    result: dict[str, dict] = {"PERSON": {}, "PLACE": {}, "ORG": {}}
    for entity_id, entity in entities_full.items():
        t = entity.get("type", "OTHER")
        if t in result:
            result[t][entity_id] = entity
    return result
```

**Step 2: Run the tests**

```bash
pytest tests/test_entity_extraction.py -k "split_by_type" -v
```

Expected: 4 PASSED

**Step 3: Run the full test suite to check for regressions**

```bash
pytest tests/test_entity_extraction.py -v
```

Expected: all tests PASSED

**Step 4: Commit**

```bash
git add scripts/entity_extraction.py
git commit -m "feat: add split_by_type function in entity_extraction"
```

---

### Task 3: Update `main()` to write 3 files instead of `entities_full.json`

**Files:**
- Modify: `scripts/entity_extraction.py:276-280`

**Step 1: Replace the file-writing block in `main()`**

Find this block (around line 278–280):
```python
    # Write full entities to disk for wiki-generation to read via repo_manager-read_file
    with open("entities_full.json", "w", encoding="utf-8") as f:
        json.dump({"entities_full": entities_full}, f, ensure_ascii=False)
```

Replace with:
```python
    # Write full entities to disk split by type, for wiki-generation to read via repo_manager-read_file
    by_type = split_by_type(entities_full)
    type_files = {
        "PERSON": ("persons_full.json", "persons_full"),
        "PLACE": ("places_full.json", "places_full"),
        "ORG": ("orgs_full.json", "orgs_full"),
    }
    for type_key, (filename, json_key) in type_files.items():
        with open(filename, "w", encoding="utf-8") as f:
            json.dump({json_key: by_type[type_key]}, f, ensure_ascii=False)
```

**Step 2: Verify the script still runs in test mode (no stdin needed)**

```bash
python scripts/entity_extraction.py --test
```

Expected: exits 0, prints entity count and sample.

**Step 3: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all PASSED

**Step 4: Commit**

```bash
git add scripts/entity_extraction.py
git commit -m "feat: write persons/places/orgs_full.json instead of entities_full.json"
```

---

### Task 4: Update `run_test_mode()` to show per-type file sizes

**Files:**
- Modify: `scripts/entity_extraction.py` — `run_test_mode` function (around lines 204–247)

This is informational only, no new tests needed.

**Step 1: In `run_test_mode()`, add `split_by_type` call and print per-type sizes**

Find the block that prints size info (around lines 242–247):
```python
    full_size = len(json.dumps(entities, ensure_ascii=False))
    slim_size = len(json.dumps(entities_for_resolution, ensure_ascii=False))
    print(
        f"\nSize: entities_full={full_size} chars, entities_for_resolution={slim_size} chars "
        f"({100 * slim_size // full_size if full_size else 0}% of full)"
    )
```

Replace with:
```python
    full_size = len(json.dumps(entities, ensure_ascii=False))
    slim_size = len(json.dumps(entities_for_resolution, ensure_ascii=False))
    print(
        f"\nSize: entities_full={full_size} chars, entities_for_resolution={slim_size} chars "
        f"({100 * slim_size // full_size if full_size else 0}% of full)"
    )

    by_type = split_by_type(entities)
    print("\nPer-type file sizes (chars):")
    for type_key, (filename, json_key) in [
        ("PERSON", ("persons_full.json", "persons_full")),
        ("PLACE", ("places_full.json", "places_full")),
        ("ORG", ("orgs_full.json", "orgs_full")),
    ]:
        size = len(json.dumps({json_key: by_type[type_key]}, ensure_ascii=False))
        print(f"  {filename}: {size} chars ({len(by_type[type_key])} entities)")
```

**Step 2: Verify test mode still works**

```bash
python scripts/entity_extraction.py --test
```

Expected: exits 0, now prints "Per-type file sizes" section.

**Step 3: Run the full test suite**

```bash
pytest tests/ -v
```

Expected: all PASSED (the `test_test_mode_exits_successfully` test checks `returncode == 0` and the existing output strings, which are unchanged).

**Step 4: Commit**

```bash
git add scripts/entity_extraction.py
git commit -m "feat: show per-type file sizes in --test mode"
```

---

### Task 5: Update `writer.agent.yaml` to read 3 files

**Files:**
- Modify: `.studio/agents/writer.agent.yaml`

**Step 1: Replace the `entities_full.json` reference in the system prompt**

Find this block (lines 17–19):
```yaml
  2. entities_full.json — the full entity registry with context sentences, written to the project
     root by the entity-extraction stage. Read it with repo_manager-read_file("entities_full.json").
     Format: {"entities_full": {entity_id: {type, raw_mentions, first_seen, mentions_by_chapter}}}
```

Replace with:
```yaml
  2. Type-specific entity files — the full entity registry split by type, written to the project
     root by the entity-extraction stage. Read the file matching the entity's type:
     - PERSON entities → repo_manager-read_file("persons_full.json")
       Format: {"persons_full": {entity_id: {type, raw_mentions, first_seen, mentions_by_chapter}}}
     - PLACE entities  → repo_manager-read_file("places_full.json")
       Format: {"places_full": {entity_id: {type, raw_mentions, first_seen, mentions_by_chapter}}}
     - ORG entities    → repo_manager-read_file("orgs_full.json")
       Format: {"orgs_full": {entity_id: {type, raw_mentions, first_seen, mentions_by_chapter}}}
```

**Step 2: Update the correlation instructions**

Find this block (lines 21–23):
```yaml
  ## How to correlate resolved entities with context

  For each resolved entity:
  - Its "source_ids" field lists the entity IDs from entities_full that were merged into it
  - Read entities_full.json, then look up each source_id to get mentions_by_chapter
  - Use those context sentences to write the wiki page
```

Replace with:
```yaml
  ## How to correlate resolved entities with context

  For each resolved entity:
  - Its "source_ids" field lists the entity IDs from the entity-extraction stage
  - Determine the entity type (PERSON / PLACE / ORG) from the resolved entity's "type" field
  - Read the matching file (persons_full.json / places_full.json / orgs_full.json)
  - Look up each source_id to get mentions_by_chapter
  - Use those context sentences to write the wiki page
```

**Step 3: Verify the YAML is still valid**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/agents/writer.agent.yaml'))"
```

Expected: exits 0, no output.

**Step 4: Commit**

```bash
git add .studio/agents/writer.agent.yaml
git commit -m "feat: update writer agent to read persons/places/orgs_full.json"
```

---

### Task 6: Update `scripts/test_extraction.py` to use `split_by_type`

**Files:**
- Modify: `scripts/test_extraction.py`

**Step 1: Update the import**

Find:
```python
from scripts.entity_extraction import extract_entities, split_entities
```

Replace with:
```python
from scripts.entity_extraction import extract_entities, split_entities, split_by_type
```

**Step 2: Add per-type stats after the size block**

Find the size print block (lines 60–65):
```python
    print(
        f"\nContext size:"
        f"\n  entities_full        = {full_size:>10,} chars  (→ wiki-generation)"
        f"\n  entities_for_resolution = {slim_size:>7,} chars  (→ entity-resolution)"
        f"\n  reduction: {100 * slim_size // full_size}% of full"
    )
```

Append after it:
```python
    by_type = split_by_type(entities_full)
    print("\nPer-type file sizes:")
    for type_key, (filename, json_key) in [
        ("PERSON", ("persons_full.json", "persons_full")),
        ("PLACE", ("places_full.json", "places_full")),
        ("ORG", ("orgs_full.json", "orgs_full")),
    ]:
        size = len(json.dumps({json_key: by_type[type_key]}, ensure_ascii=False))
        print(f"  {filename}: {size:>10,} chars  ({len(by_type[type_key])} entities)")
```

**Step 3: Run the full test suite one last time**

```bash
pytest tests/ -v
```

Expected: all PASSED

**Step 4: Commit**

```bash
git add scripts/test_extraction.py
git commit -m "feat: show per-type sizes in test_extraction.py"
```
