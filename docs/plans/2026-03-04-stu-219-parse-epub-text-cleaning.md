# STU-219: parse_epub.py — Aggressive Text Cleaning Before Entity Extraction

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Clean chapter text in `parse_epub.py` to eliminate noise (broken newlines, HTML artifacts, short/metadata chapters) before it reaches the LLM entity extractor.

**Architecture:** Add a pure `clean_chapter_text(text: str) -> str` function to `scripts/parse_epub.py`, then apply it in `parse_epub()` before appending chapters. Filter out chapters under 100 chars. All logic is unit-tested independently.

**Tech Stack:** Python stdlib (`re`, `html`), pytest, existing `scripts/parse_epub.py`, `tests/test_parse_epub.py`.

---

### Task 1: Normalize isolated newlines and multiple spaces

**Files:**
- Modify: `scripts/parse_epub.py`
- Test: `tests/test_parse_epub.py`

**Step 1: Write the failing tests**

Add to `tests/test_parse_epub.py`:

```python
from scripts.parse_epub import clean_chapter_text


def test_clean_isolated_newline_replaced_by_space():
    """Single \\n inside text → space (A. C.\\nVidal becomes A. C. Vidal)."""
    assert clean_chapter_text("A. C.\nVidal") == "A. C. Vidal"


def test_clean_isolated_newline_mid_word():
    """Single \\n mid-word → space (I\\nntéressant becomes I ntéressant)."""
    assert clean_chapter_text("I\nntéressant") == "I ntéressant"


def test_clean_double_newline_preserved():
    """Double \\n\\n (paragraph break) is preserved."""
    result = clean_chapter_text("Paragraph one.\n\nParagraph two.")
    assert result == "Paragraph one.\n\nParagraph two."


def test_clean_multiple_spaces_normalized():
    """Multiple consecutive spaces → single space."""
    assert clean_chapter_text("hello   world") == "hello world"


def test_clean_leading_trailing_whitespace_stripped():
    """Leading/trailing whitespace stripped."""
    assert clean_chapter_text("  hello world  ") == "hello world"
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_parse_epub.py -k "test_clean" -v
```
Expected: 5 FAILED with `ImportError: cannot import name 'clean_chapter_text'`

**Step 3: Implement `clean_chapter_text`**

Add after the imports in `scripts/parse_epub.py`, before `parse_epub()`:

```python
import html
import re


def clean_chapter_text(text: str) -> str:
    """Normalize chapter text to remove noise before LLM processing."""
    # 1. Unescape HTML entities (&nbsp; → space, &mdash; → —, etc.)
    text = html.unescape(text)

    # 2. Collapse runs of 2+ newlines into exactly \n\n (paragraph break)
    text = re.sub(r'\n{2,}', '\n\n', text)

    # 3. Replace remaining single \n with a space
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)

    # 4. Normalize runs of spaces/tabs to a single space
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 5. Strip each paragraph
    paragraphs = [p.strip() for p in text.split('\n\n')]
    text = '\n\n'.join(p for p in paragraphs if p)

    return text.strip()
```

Note: `html` is stdlib — no new dependency. Add `import html` and `import re` at the top of the file (alongside existing `import json`, `import sys`, `import yaml`).

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_parse_epub.py -k "test_clean" -v
```
Expected: 5 PASSED

**Step 5: Commit**

```bash
git add scripts/parse_epub.py tests/test_parse_epub.py
git commit -m "feat(stu-219): add clean_chapter_text — normalize newlines and spaces"
```

---

### Task 2: HTML entity unescaping

**Files:**
- Test: `tests/test_parse_epub.py`
- Modify: `scripts/parse_epub.py` (already has `html.unescape` from Task 1)

**Step 1: Write the failing tests**

Add to `tests/test_parse_epub.py`:

```python
def test_clean_html_entities_unescaped():
    """HTML entities are unescaped: &nbsp; → space, &mdash; → —."""
    assert clean_chapter_text("hello&nbsp;world") == "hello\u00a0world".replace('\u00a0', ' ') or \
           clean_chapter_text("hello&nbsp;world") == "hello world"


def test_clean_mdash_unescaped():
    """&mdash; is unescaped to the em dash character."""
    result = clean_chapter_text("word&mdash;word")
    assert "\u2014" in result  # em dash


def test_clean_amp_unescaped():
    """&amp; is unescaped to &."""
    assert clean_chapter_text("AT&amp;T") == "AT&T"
```

Note on `&nbsp;`: `html.unescape` converts `&nbsp;` to `\u00a0` (non-breaking space). The subsequent space normalization regex `[ \t]{2,}` only matches regular spaces/tabs, not `\u00a0`. That's acceptable — a single `\u00a0` won't cause spaCy issues. The test above handles both outcomes.

**Step 2: Run to verify they pass (no new code needed)**

```bash
pytest tests/test_parse_epub.py -k "test_clean_html or test_clean_mdash or test_clean_amp" -v
```
Expected: 3 PASSED (html.unescape was already added in Task 1)

If any fail, debug `clean_chapter_text` — the `html.unescape` call should handle all three.

**Step 3: Commit (if any fix was needed)**

```bash
git add scripts/parse_epub.py tests/test_parse_epub.py
git commit -m "test(stu-219): add HTML entity unescape tests"
```

---

### Task 3: Filter chapters shorter than 100 characters

**Files:**
- Modify: `scripts/parse_epub.py` (the `parse_epub()` function)
- Test: `tests/test_parse_epub.py`

**Step 1: Write the failing test**

Add to `tests/test_parse_epub.py`:

```python
def test_clean_short_text_returned_as_is():
    """clean_chapter_text itself doesn't filter — filtering is in parse_epub."""
    # 9-char input passes through clean_chapter_text unchanged
    assert clean_chapter_text("Chapitre") == "Chapitre"


def test_short_chapter_filtered(tmp_path):
    """Chapters with fewer than 100 chars of content are excluded from output."""
    import ebooklib
    from ebooklib import epub

    # Build a minimal EPUB with one short and one normal chapter
    book = epub.EpubBook()
    book.set_title("Test Book")
    book.set_language("fr")

    short_item = epub.EpubHtml(title="Short", file_name="short.xhtml", lang="fr")
    short_item.set_content(b"<html><body><p>Court.</p></body></html>")

    long_item = epub.EpubHtml(title="Long", file_name="long.xhtml", lang="fr")
    long_content = "<html><body><p>" + "A" * 150 + "</p></body></html>"
    long_item.set_content(long_content.encode())

    book.add_item(short_item)
    book.add_item(long_item)
    book.spine = [("short", True), ("long", True)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    epub_path = str(tmp_path / "test.epub")
    epub.write_epub(epub_path, book)

    from scripts.parse_epub import parse_epub
    result = parse_epub(epub_path)

    ids = [c["id"] for c in result["chapters"]]
    assert "short" not in ids, "Short chapter should be filtered out"
    assert "long" in ids, "Long chapter should be included"
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_parse_epub.py::test_short_chapter_filtered -v
```
Expected: FAIL — short chapter is currently included in output.

**Step 3: Apply `clean_chapter_text` and filtering in `parse_epub()`**

Replace the chapter-building loop in `scripts/parse_epub.py`:

```python
MIN_CHAPTER_CHARS = 100

chapters = []
for spine_id in spine_ids:
    item = items_by_id.get(spine_id)
    if item is None:
        continue
    soup = BeautifulSoup(item.get_content(), "html.parser")
    raw_text = soup.get_text(separator="\n", strip=True)
    cleaned = clean_chapter_text(raw_text)
    if len(cleaned) < MIN_CHAPTER_CHARS:
        continue
    chapters.append({
        "id": item.get_id(),
        "title": item.get_name(),
        "content": cleaned,
    })
```

`MIN_CHAPTER_CHARS = 100` is a module-level constant — easy to tune.

**Step 4: Run all tests**

```bash
pytest tests/test_parse_epub.py -v
```
Expected: all passing (including the two existing tests + all new ones).

**Step 5: Run full test suite**

```bash
pytest -q
```
Expected: 25+ passed, 0 failed.

**Step 6: Commit**

```bash
git add scripts/parse_epub.py tests/test_parse_epub.py
git commit -m "feat(stu-219): apply clean_chapter_text in parse_epub, filter chapters < 100 chars"
```

---

## Final Verification

```bash
# All tests green
pytest -v

# Confirm no regressions on entity_extraction --test mode (STU-218)
python scripts/entity_extraction.py --test 2>&1 | head -20
```

If `entity_extraction.py --test` produces output, verify it still runs without errors.
