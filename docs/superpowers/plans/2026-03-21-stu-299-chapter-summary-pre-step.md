# STU-299: Extract chapter_summary.py as pre-step of wiki-resolution

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `chapter_summary.py` out of the `wiki-preparation` Studio pipeline and into `run_wiki.py` as a pre-step of `wiki-resolution`, so it runs immediately after `wiki-extraction` and is not re-run on `--restart wiki-resolution` or later.

**Architecture:** Four coordinated changes: (1) add `--book` CLI mode to `chapter_summary.py` so it can be invoked standalone like the other pre-step scripts; (2) remove the stage from `wiki-preparation.pipeline.yaml`; (3) wire it as a pre-step in the orchestrator with a new `clean_files()` function that separates "what to verify" from "what to delete on clean".

**Tech Stack:** Python, PyYAML (tests), pytest

---

## File Map

| File | Change |
|------|--------|
| `scripts/chapter_summary.py` | Add `--book` CLI mode (argparse); standalone entry point reads `chapters.json` from processing dir |
| `.studio/pipelines/wiki-preparation.pipeline.yaml` | Remove `chapter-summary` stage block |
| `run_wiki.py` | Add pre-step entry; add `clean_files()`; update `required_files()`; use `clean_files()` in `--clean` logic |
| `tests/test_chapter_summary.py` | Add test for `--book` CLI mode |
| `tests/test_pipeline_configs.py` | Drop `wiki-preparation.pipeline.yaml` from the timeout test |
| `tests/test_run_wiki.py` | New file — tests for `required_files()` and `clean_files()` |

---

## Task 1: Add `--book` CLI mode to `chapter_summary.py`

**Files:**
- Modify: `scripts/chapter_summary.py`
- Modify: `tests/test_chapter_summary.py`

`chapter_summary.py` currently reads a Studio JSON payload from `stdin`. To be invoked as a pre-step by `run_wiki.py` it needs a `--book` CLI mode, like `classify_relationships.py` and `generate_wiki_pages.py` already have.

The approach: add a `_main_from_book(book_path: str)` function that reads inputs directly from the filesystem (chapters from `paths.processing / "chapters.json"`, config from the book YAML), then refactor `main()` to dispatch to it when `--book` is present and fall back to the existing stdin path otherwise.

`chapters.json` is a plain JSON list written by `entity_extraction.py` — it has the same shape as `epub_data["chapters"]` from the Studio payload.

For config (`spacy_model`, language, `chapter_summary` generation settings), read the book YAML directly — same approach as `classify_relationships.py` uses for `novel_summary`.

`book_paths_from_yaml` is already in `wiki_creator/paths.py`; add it to the import line at the bottom of the existing imports block.

- [ ] **Step 1: Write a failing test for `--book` mode**

In `tests/test_chapter_summary.py`, add:

```python
def test_main_from_book_reads_chapters_json(tmp_path, monkeypatch):
    """--book mode must read chapters from chapters.json, not stdin."""
    import json
    from unittest.mock import patch, MagicMock

    # Minimal book YAML
    book_yaml = tmp_path / "book.yaml"
    book_yaml.write_text("title: Test\nspacy_model: en_core_web_sm\n")

    # Fake processing dir with chapters.json
    processing = tmp_path / "processing_output" / "test"
    processing.mkdir(parents=True)
    chapters = [{"id": "ch01", "title": "Chapter 1", "content": "Celaena ran."}]
    (processing / "chapters.json").write_text(json.dumps(chapters))

    # Patch book_paths_from_yaml to return a fake BookPaths
    from wiki_creator.paths import BookPaths
    fake_paths = BookPaths(
        epub=tmp_path / "book.epub",
        processing=processing,
        wiki_inputs=tmp_path / "wiki_inputs",
        output=tmp_path / "output",
    )

    with patch("scripts.chapter_summary.book_paths_from_yaml", return_value=fake_paths), \
         patch("scripts.chapter_summary.summarize_chapters_incrementally", return_value={}) as mock_sum:
        from scripts.chapter_summary import _main_from_book
        _main_from_book(str(book_yaml))

    mock_sum.assert_called_once()
    call_chapters = mock_sum.call_args[0][0]
    assert call_chapters == chapters
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/test_chapter_summary.py::test_main_from_book_reads_chapters_json -v
```
Expected: FAIL with `ImportError: cannot import name '_main_from_book'` or `AttributeError`

- [ ] **Step 3: Add `book_paths_from_yaml` to imports in `chapter_summary.py`**

Change the existing import line:
```python
from wiki_creator.paths import BookPaths, book_paths_from_epub
```
to:
```python
from wiki_creator.paths import BookPaths, book_paths_from_epub, book_paths_from_yaml
```

- [ ] **Step 4: Add `_main_from_book()` and refactor `main()` in `chapter_summary.py`**

Add `import argparse` near the top with the other stdlib imports.

Add this function immediately before `main()`:

```python
def _main_from_book(book_path: str) -> None:
    """Standalone entry point: reads chapters.json from disk, runs summarization."""
    paths = book_paths_from_yaml(book_path)

    chapters_file = paths.processing / "chapters.json"
    if not chapters_file.exists():
        print(f"[ERROR] chapters.json not found: {chapters_file}", file=sys.stderr)
        sys.exit(1)
    chapters = json.loads(chapters_file.read_text(encoding="utf-8"))

    with open(book_path, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}

    spacy_model = book_cfg.get("spacy_model", "en_core_web_lg")
    export_categories = book_cfg.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    lang_config = load_lang_config(language)
    action_cues = tuple(lang_config.get("action_cues", ()))
    flashback_cues = tuple(lang_config.get("flashback_cues", ()))

    generation_cfg = book_cfg.get("generation", {})
    summary_cfg = generation_cfg.get("chapter_summary", {}) if isinstance(generation_cfg, dict) else {}
    config = ChapterSummaryConfig(
        max_bullets=int(summary_cfg.get("max_bullets", 8)),
    )

    out_file = paths.processing / "chapter_summaries.json"
    debug_dir = paths.processing / "chapter_summary_llm_debug"
    summarize_chapters_incrementally(
        chapters,
        output_file=out_file,
        debug_dir=debug_dir,
        config=config,
        action_cues=action_cues,
        flashback_cues=flashback_cues,
    )
```

Then replace `main()` to dispatch:

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Generate chapter summaries.")
    parser.add_argument("--book", help="Path to book YAML (standalone mode, reads chapters.json from disk)")
    args, _ = parser.parse_known_args()

    if args.book:
        _main_from_book(args.book)
        return

    # Studio stdin mode (legacy — called from wiki-preparation pipeline)
    payload = json.load(sys.stdin)
    epub_data = _epub_output_from_payload(payload)
    chapters = epub_data.get("chapters", [])
    config = _chapter_summary_config_from_payload(payload)

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    spacy_model = ctx.get("spacy_model", "en_core_web_lg")
    export_categories = ctx.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    lang_config = load_lang_config(language)
    action_cues = tuple(lang_config.get("action_cues", ()))
    flashback_cues = tuple(lang_config.get("flashback_cues", ()))

    paths = _paths_from_payload(payload)
    out_file = paths.processing / "chapter_summaries.json"
    debug_dir = paths.processing / "chapter_summary_llm_debug"
    chapter_summaries = summarize_chapters_incrementally(
        chapters,
        output_file=out_file,
        debug_dir=debug_dir,
        config=config,
        action_cues=action_cues,
        flashback_cues=flashback_cues,
    )
    out = {"chapter_summaries": chapter_summaries}
    json.dump(out, sys.stdout, ensure_ascii=False)
```

Note: `argparse` goes at the top with other stdlib imports — add `import argparse` there (Step 3), not inside the function.

- [ ] **Step 5: Run the test to confirm it passes**

```bash
pytest tests/test_chapter_summary.py::test_main_from_book_reads_chapters_json -v
```
Expected: PASS

- [ ] **Step 6: Run full test suite to confirm no regressions**

```bash
pytest -q
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add scripts/chapter_summary.py tests/test_chapter_summary.py
git commit -m "feat(chapter-summary): add --book CLI mode for standalone invocation (STU-299)"
```

---

## Task 2: Update pipeline config test

**Files:**
- Modify: `tests/test_pipeline_configs.py:37-50`

`test_chapter_summary_stage_has_effectively_unbounded_outer_timeout` asserts that both `wiki-preparation.pipeline.yaml` and `wiki-generation.pipeline.yaml` contain a `chapter-summary` stage with `timeout_ms=86400000`. Since we're removing the stage from `wiki-preparation`, the test must no longer check that file.

`wiki-generation.pipeline.yaml` is a legacy/deprecated pipeline (noted in CLAUDE.md) and is NOT modified in this ticket — its `chapter-summary` stage remains, keeping the test meaningful.

- [ ] **Step 1: Confirm the test currently passes**

```bash
pytest tests/test_pipeline_configs.py::test_chapter_summary_stage_has_effectively_unbounded_outer_timeout -v
```
Expected: PASS

- [ ] **Step 2: Update the test to drop `wiki-preparation.pipeline.yaml`**

In `tests/test_pipeline_configs.py`, change:
```python
    target_pipelines = {
        "wiki-preparation.pipeline.yaml",
        "wiki-generation.pipeline.yaml",
    }
```
to:
```python
    target_pipelines = {
        "wiki-generation.pipeline.yaml",
    }
```

- [ ] **Step 3: Confirm test still passes**

```bash
pytest tests/test_pipeline_configs.py::test_chapter_summary_stage_has_effectively_unbounded_outer_timeout -v
```
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_pipeline_configs.py
git commit -m "test(pipeline-configs): drop wiki-preparation from chapter-summary timeout check (STU-299)"
```

---

## Task 3: Remove `chapter-summary` stage from `wiki-preparation.pipeline.yaml`

**Files:**
- Modify: `.studio/pipelines/wiki-preparation.pipeline.yaml`

- [ ] **Step 1: Remove the `chapter-summary` stage block**

In `.studio/pipelines/wiki-preparation.pipeline.yaml`, delete this entire block:
```yaml
  - name: chapter-summary
    kind: extraction
    timeout_ms: 86400000
    executor: script
    runtime: python
    script: scripts/chapter_summary.py
    contract: chapter-summary
    context:
      include:
        - input
        - previous_stage_output
        - all_stage_outputs
```

The pipeline should now have three stages: `epub-parse`, `entity-classification`, `wiki-preparation`.

- [ ] **Step 2: Run all pipeline config tests**

```bash
pytest tests/test_pipeline_configs.py -v
```
Expected: all PASS

- [ ] **Step 3: Commit**

```bash
git add .studio/pipelines/wiki-preparation.pipeline.yaml
git commit -m "feat(wiki-preparation): remove chapter-summary stage from pipeline (STU-299)"
```

---

## Task 4: Write failing tests for `run_wiki.py` changes

**Files:**
- Create: `tests/test_run_wiki.py`

These tests will fail until Task 5 is implemented.

- [ ] **Step 1: Create `tests/test_run_wiki.py`**

```python
"""Tests for run_wiki.py orchestrator configuration."""

BOOK_PATH = "library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml"


def test_required_files_wiki_resolution_includes_chapter_summaries() -> None:
    from run_wiki import required_files
    files = required_files(BOOK_PATH)
    assert any("chapter_summaries.json" in f for f in files["wiki-resolution"]), (
        "required_files['wiki-resolution'] must include chapter_summaries.json"
    )


def test_clean_files_wiki_extraction_includes_chapter_summaries() -> None:
    from run_wiki import clean_files
    files = clean_files(BOOK_PATH)
    assert any("chapter_summaries.json" in f for f in files["wiki-extraction"]), (
        "clean_files['wiki-extraction'] must include chapter_summaries.json "
        "so --clean --restart wiki-extraction deletes it"
    )


def test_clean_files_wiki_resolution_excludes_chapter_summaries() -> None:
    from run_wiki import clean_files
    files = clean_files(BOOK_PATH)
    assert not any("chapter_summaries.json" in f for f in files.get("wiki-resolution", [])), (
        "clean_files['wiki-resolution'] must NOT include chapter_summaries.json "
        "so --clean --restart wiki-resolution preserves it"
    )


def test_pre_steps_wiki_resolution_runs_chapter_summary() -> None:
    from run_wiki import PRE_STEPS
    assert "wiki-resolution" in PRE_STEPS, "PRE_STEPS must have wiki-resolution entry"
    cmd = PRE_STEPS["wiki-resolution"]
    assert "chapter_summary.py" in " ".join(cmd), (
        "PRE_STEPS['wiki-resolution'] must invoke chapter_summary.py"
    )
```

- [ ] **Step 2: Run the tests to confirm they all fail**

```bash
pytest tests/test_run_wiki.py -v
```
Expected: 3–4 FAIL (ImportError on `clean_files`, assertion failures on others)

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_run_wiki.py
git commit -m "test(run-wiki): add failing tests for STU-299 — clean_files, required_files, PRE_STEPS"
```

---

## Task 5: Implement changes in `run_wiki.py`

**Files:**
- Modify: `run_wiki.py`

- [ ] **Step 1: Add `chapter_summary.py` to `PRE_STEPS["wiki-resolution"]`**

Change:
```python
PRE_STEPS = {
    "wiki-preparation": ["python", "scripts/classify_relationships.py", "--book"],
    "pages-export": ["python", "scripts/generate_wiki_pages.py", "--book"],
}
```
to:
```python
PRE_STEPS = {
    "wiki-resolution":  ["python", "scripts/chapter_summary.py", "--book"],
    "wiki-preparation": ["python", "scripts/classify_relationships.py", "--book"],
    "pages-export":     ["python", "scripts/generate_wiki_pages.py", "--book"],
}
```

- [ ] **Step 2: Add `chapter_summaries.json` to `required_files()["wiki-resolution"]`**

Change:
```python
        "wiki-resolution": [
            str(p.processing / "entities_classified.json"),
        ],
```
to:
```python
        "wiki-resolution": [
            str(p.processing / "entities_classified.json"),
            str(p.processing / "chapter_summaries.json"),
        ],
```

- [ ] **Step 3: Add `clean_files()` function after `required_files()`**

Insert after the closing `}` of `required_files()`:

```python

def clean_files(book_path: str) -> dict[str, list[str]]:
    """Files to delete per pipeline when --clean is used.

    Intentionally differs from required_files(): chapter_summaries.json is
    owned by wiki-extraction (only depends on its output) so it is cleaned
    when restarting from wiki-extraction, but NOT when restarting from
    wiki-resolution or later.
    """
    p = book_paths_from_yaml(book_path)
    return {
        "wiki-extraction": [
            str(p.processing / "splits.json"),
            str(p.processing / "epub_data.json"),
            str(p.processing / "chapter_summaries.json"),
        ],
        "wiki-resolution": [
            str(p.processing / "entities_classified.json"),
        ],
        "wiki-preparation": [
            str(p.processing / "relationships_classified.json"),
            str(p.wiki_inputs),
        ],
        "pages-export": [
            str(p.processing / "wiki_pages.json"),
        ],
    }
```

- [ ] **Step 4: Update `--clean` block to use `clean_files()` instead of `required_files()`**

In `main()`, change:
```python
    if args.clean:
        outputs = required_files(args.book)
        for pipeline in PIPELINES[start_idx:]:
            for path_str in outputs.get(pipeline, []):
```
to:
```python
    if args.clean:
        outputs = clean_files(args.book)
        for pipeline in PIPELINES[start_idx:]:
            for path_str in outputs.get(pipeline, []):
```

- [ ] **Step 5: Run the new tests — all 4 must pass**

```bash
pytest tests/test_run_wiki.py -v
```
Expected: all 4 PASS

- [ ] **Step 6: Run full test suite**

```bash
pytest -q
```
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add run_wiki.py
git commit -m "feat(run-wiki): extract chapter_summary.py as pre-step of wiki-resolution (STU-299)

- Add chapter_summary.py to PRE_STEPS['wiki-resolution']
- Add chapter_summaries.json to required_files['wiki-resolution']
- Introduce clean_files() to separate ownership from completion-checking
- --clean --restart wiki-extraction deletes chapter_summaries.json
- --clean --restart wiki-resolution preserves chapter_summaries.json"
```

---

## Final Verification

- [ ] **Full test suite green**

```bash
pytest -q
```
Expected: all pass, no regressions

- [ ] **pipeline YAML has no chapter-summary stage**

```bash
grep "chapter-summary" .studio/pipelines/wiki-preparation.pipeline.yaml
```
Expected: no output

- [ ] **Pre-step wiring is correct**

```bash
python -c "from run_wiki import PRE_STEPS; print(PRE_STEPS)"
```
Expected output includes `'wiki-resolution': ['python', 'scripts/chapter_summary.py', '--book']`
