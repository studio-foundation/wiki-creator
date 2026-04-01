# STU-317: Forbidden Names Guard — Spoiler Prevention in Wiki Generation

## Problem

When generating wiki pages for Throne of Glass book 1, the LLM (mistral:7b-instruct) hallucinates "Aelin Galathynius" — a major spoiler revealed in later books. The character is known only as "Celaena Sardothien" in book 1. Prompt instructions alone ("Ignore any prior knowledge") do not reliably prevent this.

## Solution

Add a **deterministic post-generation guard** that detects forbidden (spoiler) names in LLM output, retries once with an augmented prompt, and falls back to a stub page if the retry still contains spoilers.

## Config

New key in the book YAML under `validation`:

```yaml
validation:
  series: Throne of Glass
  forbidden_series:
    - A Court of Thorns and Roses
    # ...existing...
  forbidden_names:
    - Aelin Galathynius
    - Aelin
```

- Each entry is matched case-insensitively as a substring.
- Haystack: `content` field + all `infobox_fields` values (same scope as `check_forbidden_series`).

## Detection

New function in `generate_wiki_pages.py`:

```
_check_forbidden_names(page: dict, forbidden_names: list[str]) -> list[str]
```

Returns list of matched forbidden names (empty = clean).

## Prompt Augmentation

`build_prompt` gains an optional `forbidden_names: list[str]` parameter. When non-empty, appends to the WRITING RULES section:

```
FORBIDDEN NAMES (spoilers from later books — NEVER use these):
- Aelin Galathynius
- Aelin
Use ONLY the entity's canonical name and listed aliases. Any output containing a forbidden name will be rejected.
```

This block is included in **both** the initial generation prompt (preventive) and the retry prompt (corrective).

## Retry Flow

Modified `_run_generation_for_entity`:

1. Call `_run_wiki_page_item` → get page
2. Strip relations section if needed (existing logic)
3. Run `_check_forbidden_names` on result
4. If forbidden names detected:
   - Log warning to stderr
   - Re-run `_run_wiki_page_item` (1 retry)
   - Check retry result
5. If retry still contains forbidden names → return `make_stub_page(entity, failed=True)` with `_spoiler_rejected = True`
6. If clean → return page

Max attempts: **2** (initial + 1 retry).

## Validator Alignment

Add `check_forbidden_names(page, meta)` to `wiki_page_validator.py`, reading from `validation.forbidden_names` in the YAML context. Mirrors existing `check_forbidden_series` pattern. This covers the Studio pipeline path.

## Data Flow

```
book YAML (forbidden_names)
    │
    ├──► generate_wiki_pages.py
    │      build_prompt() ← includes forbidden names block
    │      _run_generation_for_entity()
    │        ├── generate page
    │        ├── _check_forbidden_names()
    │        ├── if hit: retry once with same augmented prompt
    │        └── if still hit: stub with _spoiler_rejected
    │
    └──► wiki_page_validator.py (Studio pipeline)
           check_forbidden_names() ← same substring check
```

## Test Plan

1. `_check_forbidden_names` — returns hits when present, empty when clean
2. `_check_forbidden_names` — case-insensitive matching
3. `build_prompt` — includes forbidden names block when list is non-empty
4. `build_prompt` — no forbidden names block when list is empty
5. `_run_generation_for_entity` — triggers retry when forbidden name detected (mock `_run_wiki_page_item`)
6. `_run_generation_for_entity` — returns stub with `_spoiler_rejected` after failed retry
7. `_run_generation_for_entity` — returns clean page when retry succeeds
8. `wiki_page_validator.check_forbidden_names` — detects forbidden names in content + infobox
9. Config loading — `forbidden_names` read from book YAML `validation` section

## Files Modified

- `scripts/generate_wiki_pages.py` — detection, prompt augmentation, retry logic
- `scripts/wiki_page_validator.py` — new `check_forbidden_names` check
- `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml` — add `forbidden_names`
- `tests/test_generate_wiki_pages.py` (or equivalent) — new tests
- `tests/test_wiki_page_validator.py` — new tests
