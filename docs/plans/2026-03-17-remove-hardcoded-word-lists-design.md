# Design: Remove All Hardcoded Word Lists from Scripts

**Date:** 2026-03-17
**Status:** Approved

## Problem

Several pipeline scripts define hardcoded vocabulary constants at module level. This makes the
codebase harder to maintain, mixes book-specific vocabulary with generic code, and makes it
impossible to support new languages or books without touching Python files.

Affected scripts and constants:

| Constant | Script | Issue |
|---|---|---|
| `_PATTERN_TEMPLATES` | alias_resolution.py | Language-specific regex — should be in cue_words |
| `_REVEAL_WORDS` | alias_resolution.py | Already in cue_words — just remove the hardcoded fallback |
| `_ACTION_CUES` | chapter_summary.py | Language-specific verbs — missing from cue_words |
| `_GEO_KEYWORDS` | entity_classification.py | Already in cue_words — remove hardcoded fallback |
| `_EVENT_KEYWORDS` | entity_classification.py | Already in cue_words — remove hardcoded fallback |
| `_CONCEPT_KEYWORDS` | entity_classification.py | Book-specific (wyrdmark, etc.) — already in ToG YAML but used as code fallback |
| `_ROLE_WORDS` | entity_classification.py | Mix of generic titles + ToG-specific words |
| `_ROLE_PATTERNS` | entity_classification.py | Generic regex patterns |
| `_GEO_SUFFIXES` | entity_classification.py | Language-agnostic structural geo tokens — missing from cue_words |
| `_KNOWN_WORLD_PLACES` | entity_classification.py | Purely ToG-specific (adarlan, eyllwe, rifthold…) — wrong file |

`_WINDOW_SIZE = 300` is an algorithmic constant (not vocabulary) and is left in place.

## Decision

- **Language-wide vocabulary** → `wiki_creator/cue_words/<lang>.json`
- **Book-specific vocabulary** → book YAML (`classification` section or `entity_overrides`)
- **No hardcoded fallback constants** in scripts
- **Graceful degradation**: if a key is absent from cue_words, use empty collection (consistent
  with existing behavior for `reveal_words`, `geo_keywords`, etc.)

## cue_words Changes

### New keys in `en.json` and `fr.json`

| Key | Replaces | Notes |
|---|---|---|
| `alias_pattern_templates` | `_PATTERN_TEMPLATES` | Language-specific regex strings with `{a}`/`{b}` placeholders |
| `action_cues` | `_ACTION_CUES` | Action verbs used for extractive summary sentence scoring |
| `geo_suffixes` | `_GEO_SUFFIXES` | Structural geo tokens used to retag PERSON→PLACE (mountains, sea, river…) |
| `role_words` | `_ROLE_WORDS` (generic subset) | Generic titles (captain, lord, lady, king, queen…) |
| `role_patterns` | `_ROLE_PATTERNS` (generic subset) | Generic regex role patterns |

Keys already present (`reveal_words`, `geo_keywords`, `event_keywords`) remain — their
hardcoded fallbacks are simply removed from the code.

`concept_keywords` is intentionally **not** added to cue_words — it is book/genre-specific and
belongs only in the book YAML `classification` section. No fallback.

### `_KNOWN_WORLD_PLACES` → ToG book YAML

The 9 ToG-specific place names move to `entity_overrides` in
`library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`:

```yaml
entity_overrides:
  Adarlan:
    force_type: PLACE
  Eyllwe:
    force_type: PLACE
  Erilea:
    force_type: PLACE
  Terrasen:
    force_type: PLACE
  Endovier:
    force_type: PLACE
  Rifthold:
    force_type: PLACE
  Anielle:
    force_type: PLACE
  Calaculla:
    force_type: PLACE
  Perranth:
    force_type: PLACE
  Oakwald:
    force_type: PLACE
```

## Script Changes

### `alias_resolution.py`

- Remove `_PATTERN_TEMPLATES` and `_REVEAL_WORDS` module-level constants
- Add `pattern_templates` parameter to `resolve_aliases()` (alongside existing `reveal_words=`)
- `main()` loads both from `load_lang_config(language)`:
  - `pattern_templates = lang_cfg.get("alias_pattern_templates", ())`
  - `reveal_words = lang_cfg.get("reveal_words", ())`
- All internal helpers that receive pattern templates updated accordingly

### `chapter_summary.py`

- Remove `_ACTION_CUES` module-level constant
- Add `action_cues` parameter to:
  - `_score_sentence(sentence, index, total, action_cues)`
  - `_summarize_chapter_extractive(chapter, cfg, ..., action_cues)`
  - `summarize_chapter(chapter, config, action_cues)`
  - `summarize_chapters(chapters, config, action_cues)`
  - `summarize_chapters_incrementally(chapters, ..., action_cues)`
- `main()` loads language from payload context, then `action_cues = lang_cfg.get("action_cues", ())`

### `entity_classification.py`

- Remove `_GEO_KEYWORDS`, `_EVENT_KEYWORDS`, `_CONCEPT_KEYWORDS`, `_ROLE_WORDS`,
  `_ROLE_PATTERNS`, `_GEO_SUFFIXES`, `_KNOWN_WORLD_PLACES`
- `geo_keywords` and `event_keywords`: already loaded from lang_config — remove `or _GEO_KEYWORDS` fallback lines
- `geo_suffixes`: load from `lang_cfg.get("geo_suffixes", frozenset())`; pass through to
  `_normalize_entity_type()`
- `role_words`: load from lang_config as default; book YAML `classification.role_words` overrides
- `role_patterns`: same pattern
- `concept_keywords`: only from book YAML `classification.concept_keywords`, empty if absent —
  remove the `or _CONCEPT_KEYWORDS` fallback

## CLAUDE.md Rule

Add to the **Gotchas** section:

> Never add hardcoded word lists to scripts. All vocabulary belongs in
> `wiki_creator/cue_words/<lang>.json` (language-wide) or the book YAML `classification`
> section (book-specific). No script should define a fallback vocabulary constant.
