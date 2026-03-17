# STU-265 Artifact Leaks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix three artifact leaks in wiki generation: EPUB chapter IDs in content, `_failed` stubs reaching export, and broken chapter summary context lookup.

**Architecture:** Three independent, minimal fixes across `generate_wiki_pages.py`, `wiki_preparation.py`, and `wiki_export.py`. Each fix is a small targeted change guarded by TDD. No batch data format changes.

**Tech Stack:** Python, pytest, regex

---

### Task 1: Normalize EPUB chapter IDs in prompt labels

**Files:**
- Modify: `scripts/generate_wiki_pages.py:203-207` (context block formatting in `build_prompt`)
- Test: `tests/test_generate_wiki_pages.py`

**Step 1: Write the failing test**

Add to `tests/test_generate_wiki_pages.py`, near the existing `test_build_prompt_includes_requested_sections_in_order` test:

```python
def test_build_prompt_normalizes_xhtml_chapter_keys():
    entity = {
        "canonical_name": "Celaena",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {
            "C25.xhtml": ["She crossed the hall."],
            "C03.xhtml": ["She entered the palace."],
        },
        "chapter_summary_context": [],
        "related_context": [],
        "relationships": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["biography"])
    assert "C25.xhtml" not in prompt
    assert "C03.xhtml" not in prompt
    assert "Chapter 25" in prompt
    assert "Chapter 3" in prompt


def test_build_prompt_keeps_non_xhtml_chapter_keys_unchanged():
    entity = {
        "canonical_name": "Celaena",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {
            "Chapter 5": ["She crossed the hall."],
        },
        "chapter_summary_context": [],
        "related_context": [],
        "relationships": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["biography"])
    assert "Chapter 5" in prompt


def test_build_prompt_warns_against_citing_chapter_labels():
    entity = {
        "canonical_name": "Celaena",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {"C01.xhtml": ["mention"]},
        "chapter_summary_context": [],
        "related_context": [],
        "relationships": [],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["biography"])
    assert "never mention" in prompt.lower() or "internal reference" in prompt.lower()
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_generate_wiki_pages.py::test_build_prompt_normalizes_xhtml_chapter_keys tests/test_generate_wiki_pages.py::test_build_prompt_keeps_non_xhtml_chapter_keys_unchanged tests/test_generate_wiki_pages.py::test_build_prompt_warns_against_citing_chapter_labels -v
```

Expected: all 3 FAIL

**Step 3: Add helper and update `build_prompt`**

In `scripts/generate_wiki_pages.py`, before `build_prompt` (around line 192), add:

```python
def _label_chapter_key(key: str) -> str:
    """Convert EPUB file IDs like C25.xhtml to readable labels like Chapter 25."""
    m = re.match(r'^[Cc](\d+)\.xhtml$', key)
    return f"Chapter {int(m.group(1))}" if m else key
```

In `build_prompt`, update the context block loop (lines 203–207):

```python
context_lines = []
for chapter, mentions in list(context.items())[:15]:
    label = _label_chapter_key(chapter)
    for mention in mentions[:3]:
        context_lines.append(f"  [{label}] {mention}")
context_block = "\n".join(context_lines) if context_lines else "  (no excerpts available)"
```

Also add this line to the prompt instructions block (find the existing `- infobox_fields keys must be plain strings` rule area around line 331, add after it):

```
- Context labels like [Chapter N] are internal references — never mention them in your output.
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_generate_wiki_pages.py::test_build_prompt_normalizes_xhtml_chapter_keys tests/test_generate_wiki_pages.py::test_build_prompt_keeps_non_xhtml_chapter_keys_unchanged tests/test_generate_wiki_pages.py::test_build_prompt_warns_against_citing_chapter_labels -v
```

Expected: all 3 PASS

**Step 5: Run full suite**

```bash
pytest -q
```

Expected: all tests pass

**Step 6: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "fix(STU-265): normalize EPUB chapter IDs in prompt labels"
```

---

### Task 2: Filter `_failed` pages in wiki export

**Files:**
- Modify: `scripts/wiki_export.py:97` (page loop in `main`)
- Test: `tests/test_wiki_export.py` (create new)

**Step 1: Write the failing test**

Create `tests/test_wiki_export.py`:

```python
"""Tests for wiki_export.py — focusing on _failed page filtering."""
import json
import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.wiki_export import _filter_exportable_pages


def test_filter_exportable_pages_excludes_failed():
    pages = [
        {"title": "Celaena", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "## Bio\n\nHero."},
        {"title": "Dorian", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "stub", "_failed": True},
        {"title": "Chaol", "entity_type": "PERSON", "importance": "secondary",
         "infobox_fields": {}, "content": "## Bio\n\nCaptain."},
    ]
    result = _filter_exportable_pages(pages)
    assert len(result) == 2
    assert all(not p.get("_failed") for p in result)
    assert {p["title"] for p in result} == {"Celaena", "Chaol"}


def test_filter_exportable_pages_all_valid():
    pages = [
        {"title": "A", "entity_type": "PERSON", "importance": "principal",
         "infobox_fields": {}, "content": "content"},
    ]
    assert _filter_exportable_pages(pages) == pages


def test_filter_exportable_pages_all_failed():
    pages = [
        {"title": "A", "_failed": True, "entity_type": "PERSON",
         "importance": "principal", "infobox_fields": {}, "content": ""},
    ]
    assert _filter_exportable_pages(pages) == []
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_wiki_export.py -v
```

Expected: FAIL — `_filter_exportable_pages` does not exist

**Step 3: Add helper and apply in `main`**

In `scripts/wiki_export.py`, add before `main()`:

```python
def _filter_exportable_pages(pages: list[dict]) -> list[dict]:
    """Exclude pages that failed generation — they have no usable content."""
    exportable = [p for p in pages if not p.get("_failed")]
    skipped = len(pages) - len(exportable)
    if skipped:
        print(f"[wiki-export] Skipping {skipped} _failed page(s)", file=sys.stderr)
    return exportable
```

In `main()`, apply it right after loading pages (after line 63, before `for page in pages:`):

```python
pages = _filter_exportable_pages(pages)
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_wiki_export.py -v
```

Expected: all 3 PASS

**Step 5: Run full suite**

```bash
pytest -q
```

Expected: all tests pass

**Step 6: Commit**

```bash
git add scripts/wiki_export.py tests/test_wiki_export.py
git commit -m "fix(STU-265): filter _failed pages before wiki export"
```

---

### Task 3: Fix chapter summary context lookup for EPUB-keyed chapters

**Files:**
- Modify: `scripts/wiki_preparation.py:261-290` (`build_chapter_summary_context`)
- Test: `tests/test_wiki_preparation.py`

**Background:** `context_by_chapter` uses EPUB keys like `C25.xhtml`. `chapter_summaries` keys are human-readable like `"Chapter 25"`. The current lookup `chapter_summaries.get(chapter_key)` never matches, so `chapter_summary_context` is always empty for throne-of-glass.

**Step 1: Write the failing test**

Add to `tests/test_wiki_preparation.py`, near the existing `test_build_entity_bundle_adds_chapter_summary_context_when_summaries_are_keyed_by_title` test:

```python
def test_build_chapter_summary_context_matches_xhtml_keys_to_chapter_title_keys():
    """chapter_summaries uses 'Chapter N' keys; context_by_chapter uses 'C{N}.xhtml' — must match."""
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "source_ids": ["p1"],
    }
    chapter_summaries = {
        "Chapter 25": {
            "chapter_id": None,
            "chapter_title": "Chapter 25",
            "summary_bullets": ["Celaena faces the champion trials."],
        },
    }
    context_by_chapter = {"C25.xhtml": ["She drew her blade."]}

    from scripts.wiki_preparation import build_chapter_summary_context
    result = build_chapter_summary_context(
        entity=entity,
        chapter_summaries=chapter_summaries,
        chapter_summary_max=8,
        context_by_chapter=context_by_chapter,
    )
    assert len(result) == 1
    assert result[0]["chapter_key"] == "C25.xhtml"
    assert result[0]["summary_bullets"] == ["Celaena faces the champion trials."]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_wiki_preparation.py::test_build_chapter_summary_context_matches_xhtml_keys_to_chapter_title_keys -v
```

Expected: FAIL — result is empty list

**Step 3: Add normalizer helper and update lookup**

In `scripts/wiki_preparation.py`, add a helper near the top of the file (after existing imports):

```python
import re as _re

def _epub_key_to_chapter_label(key: str) -> str | None:
    """Convert 'C25.xhtml' -> 'Chapter 25'. Returns None if key doesn't match pattern."""
    m = _re.match(r'^[Cc](\d+)\.xhtml$', key)
    return f"Chapter {int(m.group(1))}" if m else None
```

Note: `re` may already be imported — check first. If so, skip the `import re as _re` line and just use `re`.

In `build_chapter_summary_context`, update the lookup (line 277):

```python
for chapter_key in chapter_keys:
    label = _epub_key_to_chapter_label(chapter_key)
    summary = (
        chapter_summaries.get(chapter_key)
        or summaries_by_id.get(chapter_key)
        or (chapter_summaries.get(label) if label else None)
    )
    if not summary:
        continue
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_wiki_preparation.py::test_build_chapter_summary_context_matches_xhtml_keys_to_chapter_title_keys -v
```

Expected: PASS

**Step 5: Run full suite**

```bash
pytest -q
```

Expected: all tests pass

**Step 6: Commit**

```bash
git add scripts/wiki_preparation.py tests/test_wiki_preparation.py
git commit -m "fix(STU-265): resolve xhtml chapter keys against Chapter N summary keys"
```

---

## Final Verification

```bash
pytest -q
```

Expected: all tests pass (was 288 before this work; should be 288 + new tests added).
