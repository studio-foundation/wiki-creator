# STU-254 Apostrophe Normalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent malformed English contractions and apostrophe variants from reaching spaCy NER as false named entities.

**Architecture:** Extend the existing EPUB text-cleaning boundary in `scripts/parse_epub.py` instead of adding a new pipeline stage. Cover the regression with focused tests around Unicode apostrophes and split contraction repair so `entity_extraction` continues to consume already-normalized chapter text.

**Tech Stack:** Python, pytest, regex-based text normalization, existing EPUB parsing pipeline

---

### Task 1: Add regression tests for apostrophe normalization

**Files:**
- Modify: `tests/test_parse_epub.py`
- Test: `tests/test_parse_epub.py`

**Step 1: Write the failing test**

Add focused tests covering:
- curly apostrophes not yet normalized at the cleaning boundary
- malformed `I 'll` / `I ’ve` style contractions repaired before NER
- contractions still preserved with a standard ASCII apostrophe

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_parse_epub.py -k apostrophe`
Expected: FAIL on the new regression case(s)

**Step 3: Write minimal implementation**

Update `clean_chapter_text()` in `scripts/parse_epub.py` to:
- normalize a broader set of apostrophe-like Unicode characters to `'`
- repair whitespace-separated English `I'<suffix>` contractions into a single token

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_parse_epub.py -k apostrophe`
Expected: PASS

### Task 2: Verify the shared extraction flow still passes

**Files:**
- Modify: `scripts/parse_epub.py`
- Test: `tests/test_parse_epub.py`
- Test: `tests/test_entity_extraction.py`

**Step 1: Run focused parse tests**

Run: `pytest -q tests/test_parse_epub.py`
Expected: PASS

**Step 2: Run shared extraction regression coverage**

Run: `pytest -q tests/test_entity_extraction.py`
Expected: PASS

**Step 3: Commit**

```bash
git add docs/plans/2026-03-11-stu-254-apostrophe-normalization.md tests/test_parse_epub.py scripts/parse_epub.py
git commit -m "fix: normalize apostrophes before entity extraction"
```
