# STU-234 — Copyright Validator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect verbatim sequences of ≥15 consecutive words between wiki output and source EPUB text, rejecting the `wiki-generation` stage via a `hooks.on_stage_complete` hook.

**Architecture:** A deterministic Python script (`scripts/copyright_check.py`) that builds a set of 15-gram hashes from the EPUB source text, then slides a window over each wiki page to detect matches. Short quotes (≤5 words between guillemets) are masked before checking. The script runs as a Studio hook after `wiki-generation`; violations trigger a rejection with feedback naming the offending pages.

**Tech Stack:** Python 3, `ebooklib` (already in deps for epub parsing), `re`, `json`, `sys` — no new dependencies.

---

## Reference Files

- Design doc: `docs/plans/2026-03-05-stu-234-copyright-validator-design.md`
- Pipeline: `.studio/pipelines/wiki-pipeline.pipeline.yaml`
- Existing epub parser (for ebooklib patterns): `scripts/parse_epub.py`
- Test pattern reference: `tests/test_relationship_extraction.py`

---

### Task 1: Tokenizer and quote masker (pure functions)

**Files:**
- Create: `scripts/copyright_check.py`
- Create: `tests/test_copyright_check.py`

**Step 1: Write the failing tests**

```python
# tests/test_copyright_check.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.copyright_check import tokenize, mask_short_quotes


def test_tokenize_lowercases_and_strips_punctuation():
    tokens = tokenize("David Martín entra, les mains vides.")
    assert tokens == ["david", "martín", "entra", "les", "mains", "vides"]


def test_tokenize_handles_newlines_and_extra_spaces():
    tokens = tokenize("Il entra.\n\nElle sortit.  Voilà.")
    assert tokens == ["il", "entra", "elle", "sortit", "voilà"]


def test_mask_short_quotes_french_guillemets():
    text = "Il dit « bonjour ami » et repartit."
    result = mask_short_quotes(text, max_words=5)
    assert "bonjour" not in result
    assert "Il dit" in result
    assert "et repartit" in result


def test_mask_short_quotes_preserves_long_quotes():
    # 6 words — should NOT be masked
    text = "Il cria « un deux trois quatre cinq six » dans la nuit."
    result = mask_short_quotes(text, max_words=5)
    assert "un deux trois quatre cinq six" in result


def test_mask_short_quotes_double_quotes():
    text = 'Elle murmura "mon dieu" et ferma les yeux.'
    result = mask_short_quotes(text, max_words=5)
    assert "mon dieu" not in result
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_copyright_check.py -v
```
Expected: ImportError or NameError — `copyright_check` doesn't exist yet.

**Step 3: Implement the functions**

```python
#!/usr/bin/env python3
"""
Stage hook: Copyright Violation Detector (STU-234)
Detects verbatim sequences of ≥15 consecutive words between wiki output and EPUB source.

Hook usage (Studio on_stage_complete):
  python scripts/copyright_check.py --epub <path/to/book.epub>
  (reads wiki pages JSON from stdin: {"pages": [{"title", "content", "importance"}]})

Standalone test:
  python scripts/copyright_check.py --test
  python scripts/copyright_check.py --test --threshold 10
"""

import json
import re
import sys
from typing import Dict, List, Tuple


def tokenize(text: str) -> List[str]:
    """Lowercase, strip punctuation, split on whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return text.split()


def mask_short_quotes(text: str, max_words: int = 5) -> str:
    """Replace short quoted text (≤max_words words) with neutral filler tokens."""
    def replace_if_short(m: re.Match) -> str:
        content = m.group(1)
        words = content.split()
        if len(words) <= max_words:
            return " ".join(f"QMASK{i}" for i in range(len(words)))
        return m.group(0)

    text = re.sub(r"«([^»]*)»", replace_if_short, text)
    text = re.sub(r'"([^"]*)"', replace_if_short, text)
    return text
```

**Step 4: Run tests**

```bash
pytest tests/test_copyright_check.py -v
```
Expected: 5 PASS.

**Step 5: Commit**

```bash
git add scripts/copyright_check.py tests/test_copyright_check.py
git commit -m "feat(stu-234): tokenize + mask_short_quotes — copyright check foundations"
```

---

### Task 2: Source index and violation detection

**Files:**
- Modify: `scripts/copyright_check.py`
- Modify: `tests/test_copyright_check.py`

**Step 1: Write the failing tests**

Add to `tests/test_copyright_check.py`:

```python
from scripts.copyright_check import build_source_index, find_violations


SOURCE_CHAPTERS = [
    {
        "id": "ch01",
        "content": (
            "David Martín prit le manuscrit entre ses mains tremblantes "
            "et le déposa sur la table en bois verni avec soin. "
            "Il referma les yeux et écouta le silence de la nuit."
        ),
    }
]


def test_build_source_index_creates_ngrams():
    index = build_source_index(SOURCE_CHAPTERS, n=5)
    tokens = [
        "david", "martín", "prit", "le", "manuscrit",
    ]
    assert tuple(tokens) in index


def test_build_source_index_maps_to_chapter_id():
    index = build_source_index(SOURCE_CHAPTERS, n=5)
    gram = ("david", "martín", "prit", "le", "manuscrit")
    assert index[gram] == "ch01"


def test_find_violations_detects_verbatim_match():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    # This is 15 words verbatim from SOURCE_CHAPTERS
    verbatim = (
        "david martín prit le manuscrit entre ses mains tremblantes "
        "et le déposa sur la table"
    )
    violations = find_violations(tokenize(verbatim), index, n=15)
    assert len(violations) == 1
    assert violations[0]["chapter"] == "ch01"
    assert violations[0]["consecutive_words"] >= 15


def test_find_violations_no_match_on_clean_text():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    clean = "Le personnage contemplait les étoiles depuis la fenêtre de sa chambre."
    violations = find_violations(tokenize(clean), index, n=15)
    assert violations == []


def test_find_violations_short_quote_exempted():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    # The source phrase embedded in a short quote — masked before tokenize
    text = 'Il répéta « prit le manuscrit » et s\'arrêta de parler.'
    masked = mask_short_quotes(text, max_words=5)
    violations = find_violations(tokenize(masked), index, n=15)
    assert violations == []
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_copyright_check.py -v -k "source_index or violations"
```
Expected: ImportError — functions not yet defined.

**Step 3: Implement the functions**

Add to `scripts/copyright_check.py`:

```python
def build_source_index(chapters: List[dict], n: int = 15) -> Dict[tuple, str]:
    """
    Build a dict mapping each n-gram tuple to the chapter id where it first appears.
    chapters: list of {"id": str, "content": str}
    """
    index: Dict[tuple, str] = {}
    for chapter in chapters:
        tokens = tokenize(chapter["content"])
        for i in range(len(tokens) - n + 1):
            gram = tuple(tokens[i : i + n])
            if gram not in index:
                index[gram] = chapter["id"]
    return index


def find_violations(
    wiki_tokens: List[str], source_index: Dict[tuple, str], n: int = 15
) -> List[dict]:
    """
    Scan wiki_tokens with a sliding window of size n.
    Returns list of violation dicts: {chapter, wiki_excerpt, consecutive_words}.
    Merges overlapping hits into a single violation.
    """
    violations = []
    i = 0
    while i <= len(wiki_tokens) - n:
        gram = tuple(wiki_tokens[i : i + n])
        if gram in source_index:
            chapter = source_index[gram]
            # Extend to find full run length
            end = i + n
            while end < len(wiki_tokens):
                next_gram = tuple(wiki_tokens[end - n + 1 : end + 1])
                if next_gram in source_index:
                    end += 1
                else:
                    break
            violations.append(
                {
                    "chapter": chapter,
                    "wiki_excerpt": " ".join(wiki_tokens[i:end]),
                    "consecutive_words": end - i,
                }
            )
            i = end
        else:
            i += 1
    return violations
```

**Step 4: Run tests**

```bash
pytest tests/test_copyright_check.py -v
```
Expected: all PASS.

**Step 5: Commit**

```bash
git add scripts/copyright_check.py tests/test_copyright_check.py
git commit -m "feat(stu-234): build_source_index + find_violations — n-gram detection"
```

---

### Task 3: Page checker + EPUB loader + main()

**Files:**
- Modify: `scripts/copyright_check.py`
- Modify: `tests/test_copyright_check.py`

**Step 1: Write the failing tests**

Add to `tests/test_copyright_check.py`:

```python
from scripts.copyright_check import check_page, format_output


WIKI_PAGES = [
    {
        "title": "David Martín",
        "content": (
            "David Martín prit le manuscrit entre ses mains tremblantes "
            "et le déposa sur la table en bois verni avec soin. "
            "Il referma les yeux et écouta le silence de la nuit.\n\n"
            "Il était un écrivain célèbre dans tout Barcelone."
        ),
        "importance": "principal",
    },
    {
        "title": "Barcelone",
        "content": "Barcelone est la capitale de la Catalogne.",
        "importance": "secondary",
    },
]


def test_check_page_detects_violation():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    violations = check_page(WIKI_PAGES[0], index, n=15)
    assert len(violations) >= 1
    assert violations[0]["page_title"] == "David Martín"
    assert violations[0]["chapter"] == "ch01"
    assert violations[0]["consecutive_words"] >= 15


def test_check_page_clean_page_returns_empty():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    violations = check_page(WIKI_PAGES[1], index, n=15)
    assert violations == []


def test_format_output_pass():
    result = format_output(pages_checked=10, violations=[])
    assert result["status"] == "pass"
    assert result["violations"] == []
    assert result["checked_pages"] == 10


def test_format_output_fail_includes_feedback():
    viol = [{"page_title": "David Martín", "chapter": "ch01",
              "wiki_excerpt": "...", "consecutive_words": 18}]
    result = format_output(pages_checked=10, violations=viol)
    assert result["status"] == "fail"
    assert "David Martín" in result["feedback"]
    assert len(result["violations"]) == 1
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_copyright_check.py -v -k "check_page or format_output"
```
Expected: ImportError.

**Step 3: Implement check_page + format_output + load_epub_chapters + main()**

Add to `scripts/copyright_check.py`:

```python
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup


def load_epub_chapters(epub_path: str) -> List[dict]:
    """Extract chapter text from EPUB file. Returns list of {id, content}."""
    book = epub.read_epub(epub_path, options={"ignore_ncx": True})
    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 100:  # skip nav/boilerplate
            chapters.append({"id": item.get_id(), "content": text})
    return chapters


def check_page(page: dict, source_index: Dict[tuple, str], n: int = 15) -> List[dict]:
    """Check a single wiki page for verbatim matches. Returns list of violation dicts."""
    masked = mask_short_quotes(page["content"], max_words=5)
    tokens = tokenize(masked)
    raw_violations = find_violations(tokens, source_index, n=n)
    return [
        {
            "page_title": page["title"],
            "chapter": v["chapter"],
            "wiki_excerpt": v["wiki_excerpt"],
            "consecutive_words": v["consecutive_words"],
        }
        for v in raw_violations
    ]


def format_output(pages_checked: int, violations: List[dict]) -> dict:
    """Format the hook output JSON."""
    if not violations:
        return {"status": "pass", "checked_pages": pages_checked, "violations": []}

    titles = sorted({v["page_title"] for v in violations})
    titles_str = ", ".join(f"[{t}]" for t in titles)
    feedback = (
        f"Violations copyright détectées dans : {titles_str}. "
        "Reformule ces passages en paraphrasant — "
        "ne reproduis pas les mots exacts du livre source."
    )
    return {
        "status": "fail",
        "checked_pages": pages_checked,
        "violations": violations,
        "feedback": feedback,
    }


def run_check(pages: List[dict], epub_path: str, threshold: int = 15) -> dict:
    """Full pipeline: load epub, build index, check all pages."""
    chapters = load_epub_chapters(epub_path)
    source_index = build_source_index(chapters, n=threshold)
    all_violations = []
    for page in pages:
        all_violations.extend(check_page(page, source_index, n=threshold))
    return format_output(pages_checked=len(pages), violations=all_violations)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--epub", help="Path to EPUB file")
    parser.add_argument("--test", action="store_true", help="Run with fixture data")
    parser.add_argument("--threshold", type=int, default=15, help="Min consecutive words for violation")
    args = parser.parse_args()

    if args.test:
        # Fixture test: inject known verbatim passage to verify detection
        fake_chapters = [
            {
                "id": "ch01",
                "content": (
                    "David Martín prit le manuscrit entre ses mains tremblantes "
                    "et le déposa sur la table en bois verni avec soin et précision."
                ),
            }
        ]
        fake_pages = [
            {
                "title": "Test — verbatim page",
                "content": (
                    "David Martín prit le manuscrit entre ses mains tremblantes "
                    "et le déposa sur la table en bois verni avec soin et précision."
                ),
                "importance": "principal",
            },
            {
                "title": "Test — clean page",
                "content": "Ce personnage est un auteur vivant à Barcelone.",
                "importance": "secondary",
            },
        ]
        source_index = build_source_index(fake_chapters, n=args.threshold)
        violations = []
        for page in fake_pages:
            violations.extend(check_page(page, source_index, n=args.threshold))
        result = format_output(pages_checked=len(fake_pages), violations=violations)
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)

        assert result["status"] == "fail", f"Expected fail, got: {result}"
        assert result["violations"][0]["page_title"] == "Test — verbatim page"
        print("\n✓ --test passed", file=sys.stderr)
        return

    if not args.epub:
        print("Error: --epub required (or use --test)", file=sys.stderr)
        sys.exit(1)

    payload = json.load(sys.stdin)
    pages = payload.get("pages", [])
    result = run_check(pages, args.epub, threshold=args.threshold)
    json.dump(result, sys.stdout, ensure_ascii=False)

    if result["status"] == "fail":
        sys.exit(1)


if __name__ == "__main__":
    main()
```

**Step 4: Run all tests**

```bash
pytest tests/test_copyright_check.py -v
```
Expected: all PASS. (Note: `load_epub_chapters` and `run_check` are not unit-tested here — they depend on a real epub file and are covered by --test mode.)

**Step 5: Smoke test --test mode**

```bash
python scripts/copyright_check.py --test
```
Expected: JSON output with `"status": "fail"` and one violation for "Test — verbatim page", and `✓ --test passed` on stderr.

**Step 6: Commit**

```bash
git add scripts/copyright_check.py tests/test_copyright_check.py
git commit -m "feat(stu-234): check_page + format_output + main() with --test mode"
```

---

### Task 4: Hook integration in pipeline

**Files:**
- Modify: `.studio/pipelines/wiki-pipeline.pipeline.yaml`

**Step 1: Read current pipeline state**

Open `.studio/pipelines/wiki-pipeline.pipeline.yaml` and locate the `wiki-generation` stage.

**Step 2: Add the hook**

Add a `hooks` block to `wiki-generation`:

```yaml
  - name: wiki-generation
    kind: analysis
    agent: writer
    contract: wiki-generation
    ralph:
      max_attempts: 3
    hooks:
      on_stage_complete:
        - command: "python scripts/copyright_check.py --epub {{input.file_path}}"
          on_failure: reject
    context:
      include:
        - input
        - previous_stage_output
```

> **Note:** The script reads pages from stdin. Studio's hook mechanism should pipe the stage output JSON to stdin automatically — verify this behavior during a live `studio run`. If Studio does not pipe output automatically, the command may need to be adjusted to pass pages explicitly, e.g.:
> ```yaml
> - command: "echo '{{output | tojson}}' | python scripts/copyright_check.py --epub {{input.file_path}}"
> ```
> Test both and use whichever works. The script's `main()` reads `payload = json.load(sys.stdin)` and expects `{"pages": [...]}`.

**Step 3: Verify pipeline YAML is valid**

```bash
studio run wiki-pipeline --provider mock --input-file .studio/inputs/book.input.yaml
```
Expected: pipeline runs without YAML parse error. The mock provider will skip actual LLM calls but the hook should execute (or at least be parsed without error).

**Step 4: Commit**

```bash
git add .studio/pipelines/wiki-pipeline.pipeline.yaml
git commit -m "feat(stu-234): add copyright-check hook on_stage_complete to wiki-generation"
```

---

### Task 5: Final verification + PR

**Step 1: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all PASS, no regressions.

**Step 2: Run --test mode one final time**

```bash
python scripts/copyright_check.py --test
python scripts/copyright_check.py --test --threshold 10
```
Expected: both pass with `✓ --test passed`.

**Step 3: Push and create PR**

```bash
git push -u origin arianedguay/stu-234-validateur-copyright-detection-de-verbatim-entre-output-wiki
gh pr create \
  --title "feat(stu-234): copyright validator — verbatim detection hook on wiki-generation" \
  --body "$(cat <<'EOF'
## Summary

- Adds `scripts/copyright_check.py`: deterministic n-gram sliding window detector (no LLM)
- Detects sequences of ≥15 consecutive words identical between wiki output and EPUB source
- Short quotes (≤5 words between guillemets) are exempt from checking
- Integrated as `hooks.on_stage_complete` on `wiki-generation` → violations trigger reject + retry feedback
- `--test` mode for local smoke testing without a real run

## Test plan

- [ ] `pytest tests/test_copyright_check.py -v` — all pass
- [ ] `python scripts/copyright_check.py --test` — outputs `fail` for verbatim page, `✓ --test passed`
- [ ] `pytest tests/ -v` — no regressions
- [ ] `studio run wiki-pipeline --provider mock` — no YAML parse errors

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" \
  --base main
```
