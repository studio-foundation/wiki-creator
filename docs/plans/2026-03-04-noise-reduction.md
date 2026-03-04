# Noise Reduction in Entity Extraction — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce ~735 extracted entities to meaningful story entities by filtering obvious garbage in the Python script and having the resolver LLM mark common-word false positives as `relevant: false`.

**Architecture:** Two-layer: (1) pure heuristic filter in `entity_extraction.py` — frontmatter skip + length ≥ 3 + starts uppercase; (2) `relevant` boolean added to resolver output + writer agent respects it.

**Tech Stack:** Python 3, spaCy, pytest, YAML (Studio agent/contract/pipeline files)

---

## Task 1: Unit-test `_is_valid_mention` helper

**Files:**
- Test: `tests/test_entity_extraction.py` (append new test class)

No new imports needed. `_is_valid_mention` doesn't exist yet — test will fail on import.

**Step 1: Add the failing tests**

Append to `tests/test_entity_extraction.py`:

```python
# --- _is_valid_mention filter tests ---

from scripts.entity_extraction import _is_valid_mention


def test_is_valid_mention_rejects_too_short():
    assert _is_valid_mention("E") is False
    assert _is_valid_mention("Me") is False
    assert _is_valid_mention("II") is False
    assert _is_valid_mention("Ah") is False
    assert _is_valid_mention("Or") is False


def test_is_valid_mention_rejects_lowercase_start():
    assert _is_valid_mention("objectai") is False
    assert _is_valid_mention("plaidais-je") is False


def test_is_valid_mention_rejects_non_alpha_start():
    """Dash-prefixed dialog fragments like '— Liberté' must be rejected."""
    assert _is_valid_mention("— Liberté") is False
    assert _is_valid_mention("  ") is False


def test_is_valid_mention_accepts_valid_names():
    assert _is_valid_mention("David Martín") is True
    assert _is_valid_mention("Barcelone") is True
    assert _is_valid_mention("Merci") is True   # ambiguous — left to LLM
    assert _is_valid_mention("Balthazar") is True
    assert _is_valid_mention("Don Basilio") is True
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_entity_extraction.py::test_is_valid_mention_rejects_too_short -v
```

Expected: `ImportError: cannot import name '_is_valid_mention'`

---

## Task 2: Implement `_is_valid_mention`

**Files:**
- Modify: `scripts/entity_extraction.py` (after `LABEL_TO_TYPE`, before `TEST_CHAPTERS`)

**Step 1: Add the function**

After line 44 (`}`), insert:

```python

def _is_valid_mention(text: str) -> bool:
    """
    Return True if `text` looks like a valid proper-noun mention.

    Rejects:
    - Strings shorter than 3 characters (single letters, "Ah", "II", etc.)
    - Strings whose first non-whitespace character is not an uppercase letter
      (lowercase verbs, dash-prefixed dialog fragments, punctuation artifacts)
    """
    stripped = text.strip()
    if len(stripped) < 3:
        return False
    if not stripped[0].isupper():
        return False
    return True
```

**Step 2: Export it** — it's already at module level, so the import in the test will work.

**Step 3: Run the tests**

```bash
pytest tests/test_entity_extraction.py -k "is_valid_mention" -v
```

Expected: all 4 tests PASS.

**Step 4: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat: add _is_valid_mention helper for entity noise filtering"
```

---

## Task 3: Frontmatter chapter skip — test then implement

**Files:**
- Test: `tests/test_entity_extraction.py` (append)
- Modify: `scripts/entity_extraction.py`

**Step 1: Write the failing test**

Append to `tests/test_entity_extraction.py`:

```python
# --- Frontmatter chapter skip tests ---

from scripts.entity_extraction import FRONTMATTER_ID_PATTERNS


def test_frontmatter_patterns_exist():
    """The module must export a set of lowercase frontmatter patterns."""
    assert isinstance(FRONTMATTER_ID_PATTERNS, (set, frozenset))
    assert "titlepage" in FRONTMATTER_ID_PATTERNS


def test_skips_titlepage_chapter(nlp):
    """Entities from a Titlepage.xhtml chapter must not appear in the registry."""
    chapters = [
        {"id": "Titlepage.xhtml", "title": "Title Page",
         "content": "Harry Potter is a renowned wizard from England."},
        {"id": "ch01", "title": "Chapter 1",
         "content": "Harry Potter walked through London on a cold morning."},
    ]
    result = extract_entities(chapters, nlp)
    for entry in result["entities"].values():
        assert "Titlepage.xhtml" not in entry["mentions_by_chapter"], (
            f"Frontmatter chapter leaked into registry: {entry}"
        )


def test_skips_cover_chapter(nlp):
    """Chapter IDs that include 'cover' are also frontmatter."""
    chapters = [
        {"id": "cover.xhtml", "title": "Cover",
         "content": "Alice Liddell discovered a magical land called Wonderland."},
    ]
    result = extract_entities(chapters, nlp)
    assert result["entities"] == {}, (
        f"Cover chapter should produce no entities, got: {result['entities']}"
    )


def test_non_frontmatter_chapter_not_skipped(nlp):
    """Normal chapter IDs must still be processed."""
    chapters = [
        {"id": "chapter01.xhtml", "title": "Chapter 1",
         "content": "Alice walked into London and met Harry Potter."},
    ]
    result = extract_entities(chapters, nlp)
    assert result["entities"] != {}, "Normal chapter should not be skipped"
```

**Step 2: Run to confirm failure**

```bash
pytest tests/test_entity_extraction.py -k "frontmatter or titlepage or cover_chapter or non_frontmatter" -v
```

Expected: `ImportError: cannot import name 'FRONTMATTER_ID_PATTERNS'`

**Step 3: Add `FRONTMATTER_ID_PATTERNS` constant**

In `scripts/entity_extraction.py`, after `LABEL_TO_TYPE` (around line 44), add:

```python

# Chapter IDs (lowercased) matching these substrings are skipped entirely.
# They contain metadata (author, translator, epub-maker) not story entities.
FRONTMATTER_ID_PATTERNS: frozenset[str] = frozenset({
    "titlepage",
    "cover",
    "colophon",
    "copyright",
    "toc",
    "halftitle",
    "dedication",
    "index",
})
```

**Step 4: Integrate the skip into `extract_entities()`**

Replace the chapter loop header:

```python
    for chapter in chapters:
        if "content" not in chapter or "id" not in chapter:
            raise ValueError(f"chapter missing required fields 'content' or 'id': {list(chapter.keys())}")
        doc = nlp(chapter["content"])
```

With:

```python
    for chapter in chapters:
        if "content" not in chapter or "id" not in chapter:
            raise ValueError(f"chapter missing required fields 'content' or 'id': {list(chapter.keys())}")
        chapter_id_lower = chapter["id"].lower()
        if any(pattern in chapter_id_lower for pattern in FRONTMATTER_ID_PATTERNS):
            continue
        doc = nlp(chapter["content"])
```

**Step 5: Run the tests**

```bash
pytest tests/test_entity_extraction.py -k "frontmatter or titlepage or cover_chapter or non_frontmatter" -v
```

Expected: all 4 tests PASS.

**Step 6: Run the full test suite to verify no regressions**

```bash
pytest tests/test_entity_extraction.py -v
```

Expected: all tests PASS.

**Step 7: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat: skip frontmatter chapters in entity extraction"
```

---

## Task 4: Wire `_is_valid_mention` into `extract_entities()`

**Files:**
- Modify: `scripts/entity_extraction.py`

No new tests needed — `_is_valid_mention` unit tests cover the filter logic. The integration is a one-liner inside the existing entity loop.

**Step 1: Add the filter inside the entity loop**

In `extract_entities()`, after `key = ent.text.lower().strip()` and `if not key: continue`, add:

```python
            if not _is_valid_mention(ent.text):
                continue
```

The full loop body around lines 118-125 becomes:

```python
        for ent in doc.ents:
            if ent.label_ not in KEPT_LABELS:
                continue

            key = ent.text.lower().strip()
            if not key:
                continue
            if not _is_valid_mention(ent.text):
                continue

            context = extract_context(doc, ent)
```

**Step 2: Run the full test suite**

```bash
pytest tests/test_entity_extraction.py -v
```

Expected: all tests PASS.

**Step 3: Run the real extraction to measure impact**

```bash
make test-extraction
```

Expected: entity count noticeably lower than 735. Note the new total in your commit message.

**Step 4: Commit**

```bash
git add scripts/entity_extraction.py
git commit -m "feat: filter short/lowercase entity mentions in extraction

Applies _is_valid_mention() to each spaCy span before adding to registry.
Drops single-letter artifacts, lowercase verb forms, and dash-prefixed
dialog fragments."
```

---

## Task 5: Add `relevant` field to resolver agent output

**Files:**
- Modify: `.studio/agents/resolver.agent.yaml`

No tests needed (prompt engineering change, not code logic).

**Step 1: Add relevance instruction to system_prompt**

In `.studio/agents/resolver.agent.yaml`, find the line:

```yaml
  Return a JSON object: {"entities": [{canonical_name, type, aliases, source_ids}]}
```

Replace with:

```yaml
  For each resolved entity, add a "relevant" boolean field:
  - Set relevant: false ONLY for entries that are clearly not proper nouns — common
    words or interjections mistakenly extracted as entities (e.g. "Merci", "Parfait",
    "Salaud"), grammar artifacts (e.g. "J'écrivis"), or punctuation fragments.
  - Every real proper noun — even rarely mentioned characters, places, or organisations
    — must have relevant: true. Do not filter places just because they are real-world
    geography.

  Return a JSON object: {"entities": [{canonical_name, type, aliases, source_ids, relevant}]}
```

**Step 2: Verify YAML is valid**

```bash
python3 -c "import yaml; yaml.safe_load(open('.studio/agents/resolver.agent.yaml'))" && echo "OK"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add .studio/agents/resolver.agent.yaml
git commit -m "feat: add relevant flag to entity-resolution output

Resolver LLM now marks common-word false positives (Merci, Parfait,
Salaud) as relevant:false while preserving real proper nouns."
```

---

## Task 6: Update contract and writer agent to respect `relevant`

**Files:**
- Modify: `.studio/contracts/entity-resolution.contract.yaml`
- Modify: `.studio/agents/writer.agent.yaml`

**Step 1: Update entity-resolution contract**

In `.studio/contracts/entity-resolution.contract.yaml`, replace the full content with:

```yaml
name: entity-resolution
version: 1
schema:
  required_fields:
    - entities
  # Each entity in the list must include:
  #   canonical_name (str), type (str), aliases (list), source_ids (list), relevant (bool)
```

**Step 2: Add skip instruction to writer agent**

In `.studio/agents/writer.agent.yaml`, find the line starting with `  Output one wiki page per entity`:

```yaml
  Output one wiki page per entity as a JSON array: [{ title, content }]
```

Replace with:

```yaml
  Skip any entity where relevant: false — these are extraction artifacts, not real story entities.
  Output one wiki page per relevant entity as a JSON array: [{ title, content }]
```

**Step 3: Verify both YAML files are valid**

```bash
python3 -c "
import yaml
yaml.safe_load(open('.studio/contracts/entity-resolution.contract.yaml'))
yaml.safe_load(open('.studio/agents/writer.agent.yaml'))
print('OK')
"
```

Expected: `OK`

**Step 4: Run full test suite one last time**

```bash
pytest -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add .studio/contracts/entity-resolution.contract.yaml .studio/agents/writer.agent.yaml
git commit -m "feat: wire relevant filter through contract and wiki-generation

Contract documents the relevant field. Writer agent skips relevant:false
entities so they don't become wiki pages."
```
