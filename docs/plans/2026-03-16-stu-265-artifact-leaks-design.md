# STU-265 — Artifact Leaks Design

**Date:** 2026-03-16
**Ticket:** STU-265

## Problem

Three categories of internal artifacts leak into generated wiki pages:

1. **EPUB chapter IDs in content** — `context_by_chapter` keys (`C25.xhtml`) are formatted as `[C25.xhtml] mention` in the LLM prompt. The model cites them literally in output text.
2. **`_failed` stubs in export** — `wiki_export.py` has no filter; failed/stub pages are written as empty wiki files.
3. **`chapter_summary_context` always empty** — `build_chapter_summary_context` looks up summaries by raw EPUB key (`C25.xhtml`) but `chapter_summaries.json` uses human-readable keys (`Chapter 25`), so the lookup always misses.

Note: infobox internal-key leaks (`cooccurrence_count`, `entity_type`) were already fixed in STU-263 via `_clean_infobox_fields`.

## Fix 1 — Normalize chapter ID labels in prompt (`generate_wiki_pages.py`)

Add a helper `_label_chapter_key(key: str) -> str` that converts `C25.xhtml` → `Chapter 25` (regex: `^[Cc](\d+)\.xhtml$`). Falls back to the raw key for non-matching patterns.

Apply in `build_prompt` when formatting the context block:
```python
label = _label_chapter_key(chapter)
context_lines.append(f"  [{label}] {mention}")
```

Also add a prompt instruction:
```
Context labels like [Chapter N] are internal references — never mention them in your output.
```

Scope: `generate_wiki_pages.py` only. No batch data changes.

## Fix 2 — Filter `_failed` pages in export (`wiki_export.py`)

In the `for page in pages:` loop, skip failed stubs before writing:
```python
if page.get("_failed"):
    continue
```

Optionally log count of skipped pages to stderr.

## Fix 3 — Fix chapter summary context lookup (`wiki_preparation.py`)

`build_chapter_summary_context` currently only looks up `chapter_key` directly (raw EPUB ID). Add a fallback that normalizes the key:

```python
def _normalize_chapter_key_to_label(key: str) -> str:
    m = re.match(r'^[Cc](\d+)\.xhtml$', key)
    return f"Chapter {int(m.group(1))}" if m else key
```

In the lookup loop:
```python
summary = (
    chapter_summaries.get(chapter_key)
    or summaries_by_id.get(chapter_key)
    or chapter_summaries.get(_normalize_chapter_key_to_label(chapter_key))
)
```

This enables the chapter summary bullets to actually populate for throne-of-glass and other books with `C{N}.xhtml` naming.

## Acceptance Criteria

- No `*.xhtml` strings visible in wiki page content
- No `_failed` stubs written to output wiki files
- `chapter_summary_context` non-empty for entities present in chapters for throne-of-glass
- `pytest -q` passes
