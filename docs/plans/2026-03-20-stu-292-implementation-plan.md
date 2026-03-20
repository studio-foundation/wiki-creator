# STU-292 — References Book Title Constraint Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Prevent the LLM from injecting unauthorized book titles in the `## Références` section by adding a prompt constraint and a validator check.

**Architecture:** Two-layer fix — (1) prompt rule in `build_prompt()` to prevent generation of wrong titles, (2) validator check `check_references_book_title()` that extracts italicized titles from the Références section and verifies each against an allowlist loaded from `epub_data.json`. Allowlist is `list[str]` for future multi-book compatibility (STU-233).

**Tech Stack:** Python, pytest, regex, existing `BookPaths` / `book_paths_from_epub` from `wiki_creator/paths.py`.

---

### Task 1: Prompt constraint in `build_prompt()`

**Files:**
- Modify: `scripts/generate_wiki_pages.py` — `build_prompt()`, lines ~356–365 (Structure rules block)

**Step 1: Write the failing test**

In `tests/test_generate_wiki_pages.py`, add:

```python
def test_build_prompt_references_constraint_present():
    """build_prompt must include an explicit rule constraining the Références section."""
    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "aliases": [],
        "context_by_chapter": {},
        "related_context": [],
        "relationships": [],
        "chapter_summary_context": [],
    }
    prompt = build_prompt(entity, book_title="Throne of Glass", sections=["infobox", "biography", "references"])
    assert "Références" in prompt or "references" in prompt.lower()
    assert "Throne of Glass" in prompt
    # The key constraint: prompt must explicitly restrict what goes in Références
    assert "must list ONLY" in prompt or "ONLY" in prompt
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_generate_wiki_pages.py::test_build_prompt_references_constraint_present -v
```

Expected: FAIL — `assert "must list ONLY" in prompt` fails.

**Step 3: Add the rule to `build_prompt()`**

In `scripts/generate_wiki_pages.py`, find the `Structure:` block inside the f-string (around line 356). After the line:
```
- Context labels like [Chapter N] are internal references — never mention them in your output.
```

Add:
```
- The ## Références section must list ONLY "{book_title}". Do not add any other book, volume, or series title.
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_generate_wiki_pages.py::test_build_prompt_references_constraint_present -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(stu-292): constrain Références section to book_title in build_prompt"
```

---

### Task 2: `check_references_book_title()` in the validator

**Files:**
- Modify: `scripts/wiki_page_validator.py`
- Test: `tests/test_wiki_page_validator.py`

**Step 1: Write the failing tests**

In `tests/test_wiki_page_validator.py`, add these tests (import `check_references_book_title` at top):

```python
def test_check_references_book_title_passes_correct_title():
    page = {"content": "## Biographie\nTexte.\n\n## Références\n- *Throne of Glass* de Sarah J. Maas\n"}
    assert check_references_book_title(page, ["Throne of Glass"]) == []


def test_check_references_book_title_detects_wrong_title():
    page = {"content": "## Biographie\nTexte.\n\n## Références\n- *La Colonne de feu* de Sarah J. Maas\n"}
    errors = check_references_book_title(page, ["Throne of Glass"])
    assert any("La Colonne de feu" in e for e in errors)


def test_check_references_book_title_no_section_passes():
    page = {"content": "## Biographie\nTexte sans références.\n"}
    assert check_references_book_title(page, ["Throne of Glass"]) == []


def test_check_references_book_title_no_italics_passes():
    page = {"content": "## Références\nVoir le livre source.\n"}
    assert check_references_book_title(page, ["Throne of Glass"]) == []


def test_check_references_book_title_multi_book_passes():
    page = {"content": "## Références\n- *Tome 1* et *Tome 2*\n"}
    assert check_references_book_title(page, ["Tome 1", "Tome 2"]) == []


def test_check_references_book_title_underscore_italics():
    page = {"content": "## Références\n- _Mauvais Titre_\n"}
    errors = check_references_book_title(page, ["Throne of Glass"])
    assert any("Mauvais Titre" in e for e in errors)
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_wiki_page_validator.py::test_check_references_book_title_passes_correct_title -v
```

Expected: FAIL — `check_references_book_title` not defined.

**Step 3: Implement `check_references_book_title()`**

In `scripts/wiki_page_validator.py`, add after the existing imports (add `import re` at top if not present):

```python
import re
```

Add the function after `check_forbidden_series()`:

```python
def check_references_book_title(page: dict, allowed_book_titles: list[str]) -> list[str]:
    """Verify that all italicized titles in ## Références are in allowed_book_titles."""
    content = page.get("content", "")
    # Extract the ## Références block (up to next ## or end)
    match = re.search(r"##\s*Références(.*?)(?=\n##|\Z)", content, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    block = match.group(1)
    # Find all italicized titles (*title* or _title_)
    titles = re.findall(r"\*([^*\n]+)\*|_([^_\n]+)_", block)
    found = [t[0] or t[1] for t in titles]
    allowed_lower = [a.lower() for a in allowed_book_titles]
    errors = []
    for title in found:
        if title.lower() not in allowed_lower:
            errors.append(f"❌ Titre non autorisé dans Références : '{title}'")
    return errors
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_wiki_page_validator.py -k "references_book_title" -v
```

Expected: all 6 tests PASS.

**Step 5: Commit**

```bash
git add scripts/wiki_page_validator.py tests/test_wiki_page_validator.py
git commit -m "feat(stu-292): add check_references_book_title to wiki-page-validator"
```

---

### Task 3: Wire `check_references_book_title()` into `validate_page()`

**Files:**
- Modify: `scripts/wiki_page_validator.py` — `validate_page()`, add book title loading

**Step 1: Write the failing test**

In `tests/test_wiki_page_validator.py`, add:

```python
def test_validate_page_catches_wrong_references_title(tmp_path):
    """validate_page catches unauthorized title in Références when file_path resolves."""
    # Build a fake epub_data.json
    processing_dir = tmp_path / "processing_output" / "01-mybook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "epub_data.json").write_text('{"title": "My Book"}', encoding="utf-8")

    # Build a fake epub path that book_paths_from_epub can resolve
    epub_path = tmp_path / "books" / "01-mybook.epub"
    epub_path.parent.mkdir(parents=True)
    epub_path.touch()

    page = {
        "title": "Hero",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "Hero est un personnage de My Book.\n\n## Références\n- *Wrong Title*\n",
    }
    meta = {
        "file_path": str(epub_path),
        "series": "My Book",
        "forbidden_series": [],
    }
    result = validate_page(page, meta)
    assert result["valid"] is False
    assert any("Wrong Title" in e for e in result["errors"])


def test_validate_page_skips_references_check_when_no_file_path():
    page = {
        "title": "Hero",
        "importance": "principal",
        "entity_type": "PERSON",
        "infobox_fields": {},
        "content": "Hero est un personnage de My Book.\n\n## Références\n- *Any Title*\n",
    }
    meta = {"series": "My Book", "forbidden_series": []}
    # No file_path → check is skipped, no crash
    result = validate_page(page, meta)
    # valid/invalid depends on other checks, but no KeyError/crash
    assert "valid" in result
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_wiki_page_validator.py::test_validate_page_catches_wrong_references_title -v
```

Expected: FAIL — `validate_page` doesn't call `check_references_book_title` yet.

**Step 3: Add book title loading and wire the check**

In `scripts/wiki_page_validator.py`, add these imports at the top:

```python
import json
from pathlib import Path
```

Add a helper function after `check_references_book_title()`:

```python
def _load_allowed_book_titles(meta: dict) -> list[str]:
    """Load book title from epub_data.json via file_path in meta. Returns [] on failure."""
    file_path = meta.get("file_path", "")
    if not file_path:
        return []
    try:
        # Import here to avoid circular imports — paths module is lightweight
        import sys
        PROJECT_ROOT = Path(__file__).resolve().parents[1]
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from wiki_creator.paths import book_paths_from_epub
        paths = book_paths_from_epub(file_path)
        epub_data = paths.processing / "epub_data.json"
        with open(epub_data, encoding="utf-8") as f:
            data = json.load(f)
        title = data.get("title", "")
        return [title] if title else []
    except Exception:
        return []
```

Update `validate_page()`:

```python
def validate_page(page: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_language_fr(page)
    errors += check_epub_ids(page)
    errors += check_infobox_keys(page)
    errors += check_series_anchor(page, meta)
    errors += check_forbidden_series(page, meta)
    allowed_book_titles = _load_allowed_book_titles(meta)
    if allowed_book_titles:
        errors += check_references_book_title(page, allowed_book_titles)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors) if errors else "",
    }
```

**Step 4: Run all validator tests**

```bash
pytest tests/test_wiki_page_validator.py -v
```

Expected: all tests PASS (including the two new ones + all existing).

**Step 5: Run full suite**

```bash
pytest -q
```

Expected: all tests pass (same count as before + new ones).

**Step 6: Commit**

```bash
git add scripts/wiki_page_validator.py tests/test_wiki_page_validator.py
git commit -m "feat(stu-292): wire check_references_book_title into validate_page"
```

---

### Task 4: Update imports in test file

**Note:** After adding `check_references_book_title` to the validator, update the import line in `tests/test_wiki_page_validator.py` to include the new function:

```python
from scripts.wiki_page_validator import (
    parse_payload,
    check_language_fr,
    check_epub_ids,
    check_infobox_keys,
    check_series_anchor,
    check_forbidden_series,
    check_references_book_title,
    validate_page,
    build_feedback,
)
```

This should be done as part of Task 2, Step 3 — just adding `check_references_book_title` to the import list.
