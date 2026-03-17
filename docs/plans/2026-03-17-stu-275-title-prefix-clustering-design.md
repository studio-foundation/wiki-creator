# STU-275: Fix NER Clustering — Title+Surname Aliases (Captain Westfall / Chaol Westfall)

**Date:** 2026-03-17
**Issue:** https://linear.app/studioag/issue/STU-275

## Problem

"Captain Westfall" and "Chaol Westfall" are treated as distinct entities throughout the pipeline, producing a spurious `Captain Westfall ↔ Chaol Westfall` relationship. This pollutes the relationship-classifier with invalid pairs.

Two root causes:

1. `entity_clustering.py` has a hardcoded `TITLE_PREFIXES` frozenset that is French-only. "captain" is absent, so "Captain Westfall" tokenizes to `["captain", "westfall"]` instead of `["westfall"]`. Neither subset-match nor JW similarity fires against "Chaol Westfall" → separate clusters.

2. `alias_resolution.py` has `_detect_title_alias()` which correctly detects this pattern (its own docstring uses "Captain Westfall" as an example), but it requires `llm_confirmer` to not be `None` before merging. When LLM is unavailable or fails, the pair is silently logged as `ambiguous_pairs` and skipped — even when `use_llm: true` is set.

## Design

### Single source of truth: `cue_words/{lang}.json`

`person_cue_words` in `en.json` and `fr.json` already contains the right title words ("captain", "prince", "king", etc. / "capitaine", "prince", "roi", etc.). These files become the authoritative source for title prefixes, replacing the hardcoded frozenset.

### Change 1 — `entity_clustering.py`: dynamic `TITLE_PREFIXES`

In `main()`, read `additional_context` from the payload → `spacy_model` → `infer_language()` → load `cue_words/{lang}.json` → extend `TITLE_PREFIXES` with `person_cue_words` at runtime.

A helper `load_title_prefixes(language: str) -> frozenset[str]` merges the static hardcoded set with the language-specific `person_cue_words`.

For `--test` and `--live` modes (no payload / no language context), fall back to the existing hardcoded set unchanged.

Effect: "Captain Westfall" strips to `["westfall"]` → subset of `["chaol", "westfall"]` → deterministic merge, zero LLM.

### Change 2 — `alias_resolution.py`: auto-confirm title aliases

Remove the `if llm_confirmer is None: continue` guard from the `title_alias` branch in `resolve_aliases()`. A structural title-alias match (role_word prefix + exact surname substring) is high-confidence by definition — no LLM needed to confirm it.

The `_detect_title_alias()` function already produces `confidence: "medium"` and `method: "title_alias"`. The merged entity records this evidence, which is sufficient for auditability.

Additionally, in `main()`, merge `person_cue_words` from the language's cue_words JSON into `role_words` (union), so books that don't explicitly list every title in their YAML still get coverage.

### Data flow

```
book.yaml (spacy_model: en_core_web_lg)
  → infer_language() → "en"
  → load cue_words/en.json → person_cue_words: [prince, captain, king, ...]
        ↓                                  ↓
entity_clustering.py               alias_resolution.py
TITLE_PREFIXES |= person_cue_words  role_words |= person_cue_words
"Captain Westfall"                  _detect_title_alias auto-confirms
  → strips to ["westfall"]          without LLM (safety net)
  → subset of ["chaol", "westfall"]
  → same cluster ✓
```

## Acceptance criteria

- "Captain Westfall" clusters with "Chaol Westfall" in `entity_clustering.py`
- No `Captain Westfall ↔ Chaol Westfall` relationship in final output
- `alias_resolution` merges title aliases without requiring LLM (auto-confirm)
- `alias_resolution` uses `person_cue_words` as default `role_words` baseline
- All existing tests pass; new regression tests added for both stages

## Tests

- `test_entity_clustering.py`: `"Captain Westfall"` + `"Chaol Westfall"` → same cluster when language is "en"
- `test_alias_resolution.py`:
  - `_detect_title_alias` merges without `llm_confirmer` (confirmer=None)
  - "Captain Westfall" + "Chaol Westfall" fully resolved end-to-end
  - `person_cue_words` merged into `role_words` in `main()`

## Out of scope

- Changes to cue_words JSON files themselves (already correct)
- Changing canonical name selection logic
- Relationship co-occurrence count merging (separate concern)
