# Design: Language Config Externalization (STU-258)

## Context

Several scripts hardcode language-dependent word lists as `frozenset` constants.
This blocks multi-language support and makes word lists invisible to book authors.
The fix externalizes them to two destinations: `wiki_creator/cue_words/<lang>.json`
for language-generic lists, and the book YAML for book-specific classification hints.

## Two Destinations

### 1. `wiki_creator/cue_words/<lang>.json` — language-generic lists

Extend the existing `en.json` and `fr.json` with new top-level keys.

New keys added to **`en.json`**:

| Key | Replaces |
|-----|---------|
| `pronouns` | *(new — English pronouns for coref heuristic)* |
| `determiners` | *(new)* |
| `noise_words` | English subset of `_NOISE_WORDS` in `resolve_clusters.py` |
| `false_positive_words` | *(empty for English)* |
| `first_person_artifact_tails` | `FIRST_PERSON_ARTIFACT_TAILS_EN` in `entity_extraction.py` |
| `coordination_connectors` | English subset of `COORDINATION_CONNECTORS` |
| `reveal_words` | `_REVEAL_WORDS` in `alias_resolution.py` |
| `geo_keywords` | English subset of `_GEO_KEYWORDS` in `entity_classification.py` |
| `event_keywords` | English subset of `_EVENT_KEYWORDS` in `entity_classification.py` |

New keys added to **`fr.json`**:

| Key | Replaces |
|-----|---------|
| `pronouns` | `_FR_PRONOUNS` in `relationship_extraction.py` |
| `determiners` | *(new)* |
| `noise_words` | French subset of `_NOISE_WORDS` in `resolve_clusters.py` |
| `false_positive_words` | `FALSE_POSITIVE_WORDS` in `entity_extraction.py` |
| `coordination_connectors` | French subset of `COORDINATION_CONNECTORS` |
| `reveal_words` | French equivalents of `_REVEAL_WORDS` |
| `geo_keywords` | French subset of `_GEO_KEYWORDS` in `entity_classification.py` |
| `event_keywords` | French subset of `_EVENT_KEYWORDS` in `entity_classification.py` |

`first_person_artifact_tails` is English-only (the `I<verb>` OCR artifact is an English pattern).

### 2. Book YAML — book-specific classification hints

A new `classification:` block in the book YAML holds series-specific keyword lists
that are meaningless outside the book context.

```yaml
classification:
  concept_keywords: [wyrdmark, wyrdmarks, magic, marque, spell, sigil, symbol, système]
  role_words: [assassin, champion, "king's champion", "adarlan's assassin", queen, king, prince, princess, lady, lord, captain, guard]
  role_patterns:
    - '\b[a-z][a-z''\- ]*assassin\b'
    - '\b[a-z][a-z''\- ]*champion\b'
    - '\bking''?s champion\b'
```

`entity_classification.py` reads these from `additional_context` and uses them in
place of the hardcoded constants. Falls back to empty lists if the block is absent.

## Loader: `wiki_creator/lang.py`

New thin module with two public functions:

```python
def infer_language(spacy_model: str) -> str:
    """Infer language code from spaCy model name. Returns 'fr' or 'en'."""

def load_lang_config(language: str) -> dict:
    """Load wiki_creator/cue_words/<language>.json. Falls back to 'en' if not found."""
```

`infer_language` is moved from `entity_extraction.py` (`_infer_cue_words_language`)
so all scripts share the same detection logic.

Scripts obtain language from `additional_context`:
- Prefer `language` field (e.g. `export.categories.language: en`)
- Fall back to `infer_language(spacy_model)` if only `spacy_model` is present

## Script Changes

### `relationship_extraction.py`
- Read `language` and `spacy_model` from `additional_context`
- Call `load_lang_config(language)["pronouns"]` → replaces `_FR_PRONOUNS`
- Replace 3× hardcoded `"fr_core_news_lg"` with `spacy_model` from context
- Add `spacy_model` to `_coref_worker` args tuple (index 3)

### `entity_extraction.py`
- Import `load_lang_config`, `infer_language` from `wiki_creator.lang`
- Load `false_positive_words`, `first_person_artifact_tails`, `coordination_connectors`
  from lang config instead of module-level constants
- Remove `_infer_cue_words_language` (moved to `wiki_creator/lang.py`)

### `resolve_clusters.py`
- Accept optional `language: str` parameter in functions that use `_NOISE_WORDS`
- Load `noise_words` from lang config; fall back to current combined set if language unknown

### `alias_resolution.py`
- Read `language` from `additional_context`
- Load `reveal_words` from lang config → replaces `_REVEAL_WORDS`

### `entity_classification.py`
- Read `classification` block from `additional_context` (book YAML)
- Replace `_CONCEPT_KEYWORDS`, `_ROLE_WORDS`, `_ROLE_PATTERNS` with values from book YAML
- Load `geo_keywords`, `event_keywords` from lang config → replaces `_GEO_KEYWORDS`, `_EVENT_KEYWORDS`

## What Stays Hardcoded

- `_PATTERN_TEMPLATES` in `alias_resolution.py` — regex patterns, not word lists
- `_KNOWN_WORLD_PLACES` in `entity_classification.py` — if present, book-specific override handled separately

## Acceptance Criteria

- [ ] `wiki_creator/cue_words/en.json` has all new keys
- [ ] `wiki_creator/cue_words/fr.json` has all new keys
- [ ] `wiki_creator/lang.py` exists with `load_lang_config` and `infer_language`
- [ ] `relationship_extraction.py`: `_FR_PRONOUNS` removed, `fr_core_news_lg` not hardcoded, `spacy_model` in worker args
- [ ] `entity_extraction.py`: `FALSE_POSITIVE_WORDS`, `FIRST_PERSON_ARTIFACT_TAILS_EN`, `COORDINATION_CONNECTORS` loaded from lang config
- [ ] `resolve_clusters.py`: `_NOISE_WORDS` loaded from lang config
- [ ] `alias_resolution.py`: `_REVEAL_WORDS` loaded from lang config
- [ ] `entity_classification.py`: `_GEO_KEYWORDS`, `_EVENT_KEYWORDS` from lang config; `_CONCEPT_KEYWORDS`, `_ROLE_WORDS`, `_ROLE_PATTERNS` from book YAML
- [ ] `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml` has `classification:` block
- [ ] `pytest -q` passes
