# STU-299: Extract `chapter_summary.py` from Studio pipeline

**Date:** 2026-03-21
**Status:** Approved

## Problem

`chapter_summary.py` runs inside the Studio pipeline `wiki-preparation`, but it only depends on `chapters.json` (produced by `wiki-extraction`). It has no dependency on `wiki-resolution` or `wiki-preparation`. Running it inside `wiki-preparation` means it gets re-run — or worse, skipped due to restart logic — when it shouldn't be.

Correct dependency order:
```
wiki-extraction
  [pre-step] chapter_summary.py   ← depends only on chapters.json
wiki-resolution
wiki-preparation                   ← consumes chapter_summaries.json already present
pages-export
```

## Changes

### 1. `wiki-preparation.pipeline.yaml` — Remove `chapter-summary` stage

Delete the `chapter-summary` stage block. The pipeline becomes:
`epub-parse` → `entity-classification` → `wiki-preparation`

### 2. `run_wiki.py` — Add pre-step for `wiki-resolution`

```python
PRE_STEPS = {
    "wiki-resolution":  ["python", "scripts/chapter_summary.py", "--book"],
    "wiki-preparation": ["python", "scripts/classify_relationships.py", "--book"],
    "pages-export":     ["python", "scripts/generate_wiki_pages.py", "--book"],
}
```

### 3. `run_wiki.py` — `required_files()`: add `chapter_summaries.json` to `wiki-resolution`

```python
"wiki-resolution": [
    str(p.processing / "entities_classified.json"),
    str(p.processing / "chapter_summaries.json"),
],
```

This ensures the orchestrator verifies the pre-step produced its output before marking wiki-resolution as complete.

### 4. `run_wiki.py` — Add `clean_files()` function

Introduce a `clean_files(book_path)` function (parallel to `required_files`) used exclusively by the `--clean` logic. `chapter_summaries.json` is listed under `"wiki-extraction"` here — meaning it is only deleted when cleaning from `wiki-extraction` or earlier.

```python
def clean_files(book_path: str) -> dict[str, list[str]]:
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

The `--clean` block replaces `required_files(args.book)` with `clean_files(args.book)`.

**Behavior:**
- `--clean --restart wiki-extraction` → deletes `chapter_summaries.json` ✓
- `--clean --restart wiki-resolution` → does NOT delete `chapter_summaries.json` ✓

### 5. `tests/test_pipeline_configs.py` — Update timeout test

`test_chapter_summary_stage_has_effectively_unbounded_outer_timeout` checks that `wiki-preparation.pipeline.yaml` contains the `chapter-summary` stage with `timeout_ms=86400000`. Since the stage is removed from that pipeline, drop `wiki-preparation.pipeline.yaml` from `target_pipelines`, keeping only `wiki-generation.pipeline.yaml`.

## Acceptance Criteria

- Interrupt at chapter 30/55 → `--restart wiki-resolution` → skips chapters 1–30, resumes at 31
- `--restart wiki-preparation` → `chapter_summaries.json` untouched
- `--clean --restart wiki-extraction` → `chapter_summaries.json` deleted and recalculated
- `wiki-preparation.pipeline.yaml` no longer contains `chapter-summary` stage
- `pytest -q` passes
