# Remove Hardcoded Word Lists from Scripts — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate all hardcoded vocabulary constants from pipeline scripts; route every word list through `wiki_creator/cue_words/<lang>.json` (language-wide) or the book YAML (book-specific).

**Architecture:** Five tasks, each fully TDD. cue_words JSON files gain new keys; scripts lose module-level constants and load vocabulary via `load_lang_config(language)` already used elsewhere. Graceful degradation: missing keys → empty collection (no crash). Book-specific place names move to `entity_overrides` in the ToG YAML.

**Tech Stack:** Python 3.11+, pytest, `wiki_creator.lang.load_lang_config`

**Design doc:** `docs/plans/2026-03-17-remove-hardcoded-word-lists-design.md`

---

## Task 1 — Add new keys to `cue_words/en.json` and `cue_words/fr.json`

**Files:**
- Modify: `wiki_creator/cue_words/en.json`
- Modify: `wiki_creator/cue_words/fr.json`
- Modify: `tests/test_lang.py`

### Step 1: Write failing tests

Add to `tests/test_lang.py`:

```python
def test_load_lang_config_en_has_all_new_keys():
    cfg = load_lang_config("en")
    for key in ("alias_pattern_templates", "action_cues", "geo_suffixes", "role_words", "role_patterns"):
        assert key in cfg, f"missing key: {key}"
        assert len(cfg[key]) > 0, f"key is empty: {key}"


def test_load_lang_config_fr_has_all_new_keys():
    cfg = load_lang_config("fr")
    for key in ("alias_pattern_templates", "action_cues", "geo_suffixes", "role_words", "role_patterns"):
        assert key in cfg, f"missing key: {key}"
        assert len(cfg[key]) > 0, f"key is empty: {key}"


def test_en_alias_pattern_templates_contain_placeholder():
    cfg = load_lang_config("en")
    assert any("{b}" in t for t in cfg["alias_pattern_templates"])


def test_en_action_cues_contains_found():
    cfg = load_lang_config("en")
    assert "found" in cfg["action_cues"]


def test_en_geo_suffixes_contains_mountains():
    cfg = load_lang_config("en")
    assert "mountains" in cfg["geo_suffixes"]


def test_en_role_words_contains_captain():
    cfg = load_lang_config("en")
    assert "captain" in cfg["role_words"]
```

### Step 2: Run tests to verify they fail

```bash
pytest tests/test_lang.py -v -k "new_keys or alias_pattern or action_cues or geo_suffixes or role_words"
```

Expected: FAIL — keys not present yet.

### Step 3: Add new keys to `en.json`

In `wiki_creator/cue_words/en.json`, add after `"event_keywords"`:

```json
  "alias_pattern_templates": [
    "\\byou may call me {b}\\b",
    "\\balso known as {b}\\b",
    "\\bformerly known as {b}\\b",
    "\\bformerly {b}\\b",
    "\\bcalled (?:him|her|them) {b}\\b",
    "\\bknown as {b}\\b",
    "\\bnée {b}\\b",
    "\\b{a}[^.]{{0,80}}\\banother name[^.]{{0,80}}\\b{b}\\b",
    "\\b{a}[^.]{{0,80}}\\bunder another name[^.]{{0,80}}\\b{b}\\b"
  ],
  "action_cues": [
    "found", "discovered", "revealed", "warned", "reported", "followed",
    "attacked", "killed", "escaped", "met", "decided", "realized", "uncovered",
    "arrived", "left", "returned", "asked", "opened", "closed"
  ],
  "geo_suffixes": [
    "mountains", "mountain", "sea", "ocean", "river", "lake", "forest",
    "coast", "bay", "gulf", "isle", "island", "valley", "desert",
    "plains", "peak", "pass", "strait", "fjord", "cape"
  ],
  "role_words": [
    "captain", "guard", "queen", "king", "prince", "princess", "lady", "lord",
    "duke", "sir", "assassin", "champion"
  ],
  "role_patterns": [
    "\\b[a-z][a-z'\\- ]*assassin\\b",
    "\\b[a-z][a-z'\\- ]*champion\\b",
    "\\bking'?s champion\\b"
  ]
```

### Step 4: Add new keys to `fr.json`

In `wiki_creator/cue_words/fr.json`, add after `"event_keywords"`:

```json
  "alias_pattern_templates": [
    "\\bvous pouvez m'appeler {b}\\b",
    "\\bégalement connu sous le nom de {b}\\b",
    "\\bautrefois connu sous le nom de {b}\\b",
    "\\bappelé {b}\\b",
    "\\bconnu sous le nom de {b}\\b",
    "\\bnée {b}\\b",
    "\\b{a}[^.]{{0,80}}\\bsous un autre nom[^.]{{0,80}}\\b{b}\\b"
  ],
  "action_cues": [
    "trouva", "découvrit", "révéla", "avertit", "signala", "suivit",
    "attaqua", "tua", "s'échappa", "rencontra", "décida", "réalisa",
    "arriva", "partir", "repartit", "demanda", "ouvrit", "ferma"
  ],
  "geo_suffixes": [
    "montagnes", "montagne", "mer", "océan", "rivière", "lac", "forêt",
    "côte", "baie", "golfe", "île", "vallée", "désert",
    "plaines", "pic", "col", "détroit", "fjord", "cap"
  ],
  "role_words": [
    "capitaine", "garde", "reine", "roi", "prince", "princesse", "dame", "seigneur",
    "duc", "sir", "assassin", "champion"
  ],
  "role_patterns": [
    "\\b[a-z][a-zàâéèêëîïôùûüç'\\- ]*assassin\\b",
    "\\b[a-z][a-zàâéèêëîïôùûüç'\\- ]*champion\\b"
  ]
```

### Step 5: Run tests to verify they pass

```bash
pytest tests/test_lang.py -v
```

Expected: All PASS.

### Step 6: Commit

```bash
git add wiki_creator/cue_words/en.json wiki_creator/cue_words/fr.json tests/test_lang.py
git commit -m "feat(STU-cue): add alias_pattern_templates, action_cues, geo_suffixes, role_words, role_patterns to cue_words"
```

---

## Task 2 — Refactor `alias_resolution.py`

**Files:**
- Modify: `scripts/alias_resolution.py`
- Modify: `tests/test_alias_resolution.py`

### Context

`_PATTERN_TEMPLATES` is used in `_detect_pattern_for_names()` via a nested loop. `_REVEAL_WORDS` is already accepted as a parameter in `resolve_aliases()` and loaded from lang_config in `main()` — it just still has the hardcoded fallback. The default value `resolve_aliases(..., reveal_words=_REVEAL_WORDS)` must change to `()`.

`_detect_pattern_for_names(name_a, name_b, snippets)` and `_detect_pattern_match(entity_a, entity_b, persons_full)` both need a `pattern_templates` parameter. `resolve_aliases()` needs it too so it can pass down.

### Step 1: Write failing tests

Add to `tests/test_alias_resolution.py`:

```python
def test_resolve_aliases_accepts_pattern_templates_kwarg():
    """pattern_templates kwarg must be accepted (not crash)."""
    result = resolve_aliases(
        [PERSON_A, PERSON_B],
        persons_full={},
        pattern_templates=("\\byou may call me {b}\\b",),
    )
    assert "entities" in result


def test_pattern_templates_empty_means_no_pattern_merges():
    persons_full = {
        "entity_001": {"mentions_by_chapter": {"ch01": ["You may call me Lillian Gordaina."]}},
        "entity_002": {"mentions_by_chapter": {}},
    }
    result = resolve_aliases(
        [PERSON_A, PERSON_B],
        persons_full=persons_full,
        pattern_templates=(),   # empty → no pattern detection
    )
    assert result["stats"]["merges_applied"] == 0
```

### Step 2: Run tests to verify they fail

```bash
pytest tests/test_alias_resolution.py::test_resolve_aliases_accepts_pattern_templates_kwarg tests/test_alias_resolution.py::test_pattern_templates_empty_means_no_pattern_merges -v
```

Expected: FAIL — `resolve_aliases` does not accept `pattern_templates`.

### Step 3: Implement the changes

In `scripts/alias_resolution.py`:

1. **Delete** the module-level constants `_PATTERN_TEMPLATES` and `_REVEAL_WORDS` (lines 39–59).

2. **Update `_detect_pattern_for_names`** — add `pattern_templates` parameter:

```python
def _detect_pattern_for_names(
    name_a: str,
    name_b: str,
    snippets: list[str],
    pattern_templates: tuple[str, ...] = (),
) -> str | None:
    if name_a.lower() == name_b.lower():
        return None
    pattern_a_b = [
        t.format(a=re.escape(name_a.lower()), b=re.escape(name_b.lower()))
        for t in pattern_templates
    ]
    pattern_b_a = [
        t.format(a=re.escape(name_b.lower()), b=re.escape(name_a.lower()))
        for t in pattern_templates
    ]
    for snippet in snippets:
        lowered = snippet.lower()
        for pattern in pattern_a_b + pattern_b_a:
            if re.search(pattern, lowered):
                return snippet
    return None
```

3. **Update `_detect_pattern_match`** — add `pattern_templates` parameter and pass through:

```python
def _detect_pattern_match(
    entity_a: dict,
    entity_b: dict,
    persons_full: dict,
    pattern_templates: tuple[str, ...] = (),
) -> dict | None:
    contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for name_a in names_a:
        for name_b in names_b:
            snippet = _detect_pattern_for_names(name_a, name_b, contexts, pattern_templates)
            if snippet:
                return {"method": "pattern", "confidence": "high", "snippet": snippet}
    return None
```

4. **Update `detect_named_aliases`** — add `pattern_templates` parameter, replace the internal call:

```python
def detect_named_aliases(
    mentions: dict[str, list[str]],
    text: str,
    reveal_words: tuple[str, ...] | None = None,
    pattern_templates: tuple[str, ...] = (),
) -> list[AliasPair]:
```

Inside the loop, change:
```python
evidence = _detect_pattern_for_names(name_a, name_b, all_snippets)
```
to:
```python
evidence = _detect_pattern_for_names(name_a, name_b, all_snippets, pattern_templates)
```

5. **Update `resolve_aliases`** — add `pattern_templates` parameter, pass to `_detect_pattern_match`:

```python
def resolve_aliases(
    entities: list[dict],
    persons_full: dict,
    narrator=None,
    llm_confirmer=None,
    reveal_words: tuple[str, ...] = (),
    role_words: list[str] | None = None,
    pattern_templates: tuple[str, ...] = (),
) -> dict:
```

Inside the loop, change:
```python
evidence = _detect_pattern_match(entity, candidate, persons_full)
```
to:
```python
evidence = _detect_pattern_match(entity, candidate, persons_full, pattern_templates)
```

6. **Update `main()`** — load `pattern_templates` from lang_config and pass to `resolve_aliases`:

```python
pattern_templates = tuple(load_lang_config(language).get("alias_pattern_templates", ()))
reveal_words = tuple(load_lang_config(language).get("reveal_words", ()))

result = resolve_aliases(
    entities, persons_full=persons_full, narrator=narrator,
    llm_confirmer=llm_confirmer, reveal_words=reveal_words,
    role_words=role_words, pattern_templates=pattern_templates,
)
```

(The double `load_lang_config` call can be collapsed into one — load once, read both keys.)

### Step 4: Run the full test suite

```bash
pytest tests/test_alias_resolution.py -v
```

Expected: All PASS.

### Step 5: Commit

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "refactor(alias): remove _PATTERN_TEMPLATES and _REVEAL_WORDS, load from cue_words"
```

---

## Task 3 — Refactor `chapter_summary.py`

**Files:**
- Modify: `scripts/chapter_summary.py`
- Modify: `tests/test_chapter_summary.py`

### Context

`_ACTION_CUES` is used only in `_score_sentence()`. The function is called by `_summarize_chapter_extractive()`, which is called by `summarize_chapter()`, `summarize_chapters()`, and `summarize_chapters_incrementally()`. All public functions get an optional `action_cues` parameter (default `()`). `main()` gains language inference and passes `action_cues` from lang_config.

### Step 1: Write failing tests

Add to `tests/test_chapter_summary.py`:

```python
from scripts.chapter_summary import _score_sentence, _summarize_chapter_extractive


def test_score_sentence_accepts_action_cues_kwarg():
    score = _score_sentence("Dorian found the letter.", 0, 5, action_cues=("found",))
    assert isinstance(score, float)


def test_score_sentence_action_cue_increases_score():
    base = _score_sentence("Dorian walked into the room.", 0, 5, action_cues=())
    boosted = _score_sentence("Dorian found the letter.", 0, 5, action_cues=("found",))
    assert boosted > base


def test_summarize_chapter_accepts_action_cues_kwarg():
    chapter = {
        "id": "ch01",
        "title": "Chapter 1",
        "content": "Celaena arrived at the castle. She found the hidden door.",
    }
    result = summarize_chapter(chapter, action_cues=("arrived", "found"))
    assert len(result["summary_bullets"]) > 0


def test_summarize_chapters_accepts_action_cues_kwarg():
    chapters = [{"id": "ch01", "title": "Chapter 1", "content": "Dorian met Chaol."}]
    result = summarize_chapters(chapters, action_cues=("met",))
    assert "Chapter 1" in result
```

### Step 2: Run tests to verify they fail

```bash
pytest tests/test_chapter_summary.py::test_score_sentence_accepts_action_cues_kwarg tests/test_chapter_summary.py::test_summarize_chapters_accepts_action_cues_kwarg -v
```

Expected: FAIL.

### Step 3: Implement the changes

In `scripts/chapter_summary.py`:

1. **Delete** the module-level `_ACTION_CUES` constant (lines 53–57).

2. **Add imports** at the top (if not already present):
```python
from wiki_creator.lang import load_lang_config, infer_language
```

3. **Update `_score_sentence`** — add `action_cues` parameter:

```python
def _score_sentence(sentence: str, index: int, total: int, action_cues: tuple[str, ...] = ()) -> float:
    tokens = re.findall(r"[A-Za-zÀ-ÿ']+", sentence)
    token_count = len(tokens)
    if token_count == 0:
        return float("-inf")
    proper_nouns = sum(1 for t in tokens if t and t[0].isupper())
    unique_ratio = len({t.lower() for t in tokens}) / token_count
    position_bonus = max(0.0, 1.0 - (index / max(total, 1)))
    lowered = sentence.lower()
    action_bonus = 0.0
    for cue in action_cues:
        if cue in lowered:
            action_bonus += 0.15
    dialogue_penalty = 0.75 if _looks_dialogue_heavy(sentence) else 0.0
    return (proper_nouns / token_count) * 2.0 + unique_ratio + position_bonus * 0.25 + action_bonus - dialogue_penalty
```

4. **Update `_summarize_chapter_extractive`** — add `action_cues` parameter and pass to `_score_sentence`:

```python
def _summarize_chapter_extractive(
    chapter: dict,
    cfg: ChapterSummaryConfig,
    method: str = "extractive",
    seed_flags: list[str] | None = None,
    action_cues: tuple[str, ...] = (),
) -> dict:
```

Inside the function, change the `sorted(candidates, key=lambda item: _score_sentence(...))` call to pass `action_cues`:

```python
ranked = sorted(
    candidates,
    key=lambda item: _score_sentence(item[1], item[0], len(sentences), action_cues),
    reverse=True,
)[: cfg.max_bullets]
```

5. **Update `summarize_chapter_from_item_result`** — add `action_cues` parameter and pass to `_summarize_chapter_extractive`:

```python
def summarize_chapter_from_item_result(
    chapter: dict,
    item_result: dict | list[str],
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
) -> dict:
```

In the fallback call:
```python
return _summarize_chapter_extractive(chapter, cfg, ..., action_cues=action_cues)
```

6. **Update `summarize_chapter`** — add `action_cues` parameter:

```python
def summarize_chapter(
    chapter: dict,
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
) -> dict:
    cfg = config or ChapterSummaryConfig()
    if cfg.mode == "llm":
        llm_result = _call_llm_summary(...)
        return summarize_chapter_from_item_result(chapter, llm_result, config=cfg, action_cues=action_cues)
    return _summarize_chapter_extractive(chapter, cfg, action_cues=action_cues)
```

7. **Update `summarize_chapters`** — add `action_cues` parameter and pass to `summarize_chapter`:

```python
def summarize_chapters(
    chapters: list[dict],
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for chapter in chapters:
        if _is_frontmatter_chapter(chapter):
            continue
        key = _chapter_key(chapter)
        if not key:
            continue
        result[key] = summarize_chapter(chapter, config=config, action_cues=action_cues)
    return result
```

8. **Update `summarize_chapters_incrementally`** — add `action_cues` parameter and pass through:

```python
def summarize_chapters_incrementally(
    chapters: list[dict],
    *,
    output_file: Path,
    debug_dir: Path | None = None,
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
) -> dict[str, dict]:
```

In the extractive branch:
```python
result[key] = summarize_chapter(chapter, config=config, action_cues=action_cues)
```

In the LLM branch (`summarize_chapter_from_item_result`):
```python
result[key] = summarize_chapter_from_item_result(chapter, item_result, config=config, action_cues=action_cues)
```

9. **Update `main()`** — add language inference and load `action_cues`:

```python
def main() -> None:
    payload = json.load(sys.stdin)
    epub_data = _epub_output_from_payload(payload)
    chapters = epub_data.get("chapters", [])
    config = _chapter_summary_config_from_payload(payload)

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    spacy_model = ctx.get("spacy_model", "en_core_web_lg")
    export_categories = ctx.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    lang_cfg = load_lang_config(language)
    action_cues = tuple(lang_cfg.get("action_cues", ()))

    paths = _paths_from_payload(payload)
    out_file = paths.processing / "chapter_summaries.json"
    debug_dir = paths.processing / "chapter_summary_llm_debug"
    chapter_summaries = summarize_chapters_incrementally(
        chapters,
        output_file=out_file,
        debug_dir=debug_dir,
        config=config,
        action_cues=action_cues,
    )
    json.dump({"chapter_summaries": chapter_summaries}, sys.stdout, ensure_ascii=False)
```

(Also add `import yaml` if not already imported — it is already present in the file.)

### Step 4: Run the full test suite

```bash
pytest tests/test_chapter_summary.py -v
```

Expected: All PASS.

### Step 5: Commit

```bash
git add scripts/chapter_summary.py tests/test_chapter_summary.py
git commit -m "refactor(chapter-summary): remove _ACTION_CUES, load from cue_words via action_cues param"
```

---

## Task 4 — Refactor `entity_classification.py`

**Files:**
- Modify: `scripts/entity_classification.py`
- Modify: `tests/test_entity_classification.py`

### Context

Constants to remove and their new sources:

| Constant | New source |
|---|---|
| `_GEO_KEYWORDS` | already loaded from lang_config — just remove `or _GEO_KEYWORDS` fallback |
| `_EVENT_KEYWORDS` | already loaded from lang_config — just remove `or _EVENT_KEYWORDS` fallback |
| `_CONCEPT_KEYWORDS` | book YAML only — remove `or _CONCEPT_KEYWORDS` fallback, use empty if absent |
| `_ROLE_WORDS` | lang_config default; book YAML `classification.role_words` can override |
| `_ROLE_PATTERNS` | lang_config default; book YAML `classification.role_patterns` can override |
| `_GEO_SUFFIXES` | add to lang_config load; add parameter to `_normalize_entity_type` |
| `_KNOWN_WORLD_PLACES` | remove check entirely (replaced by entity_overrides in ToG YAML, Task 5) |

### Step 1: Write failing tests

Add to `tests/test_entity_classification.py`:

```python
def test_normalize_entity_type_accepts_geo_suffixes_kwarg():
    entity = {"canonical_name": "Iron Mountains", "type": "PERSON", "source_ids": []}
    result = _normalize_entity_type(
        entity, {}, {}, {}, {},
        geo_suffixes=frozenset({"mountains"}),
    )
    assert result == "PLACE"


def test_normalize_entity_type_geo_suffixes_empty_does_not_retag():
    entity = {"canonical_name": "Iron Mountains", "type": "PERSON", "source_ids": []}
    result = _normalize_entity_type(
        entity, {}, {}, {}, {},
        geo_suffixes=frozenset(),
    )
    # Without geo_suffixes hint, should NOT retag just from name alone
    assert result == "PERSON"


def test_is_role_entity_name_empty_role_words_returns_false():
    assert _is_role_entity_name("captain", role_words=frozenset(), role_patterns=()) is False


def test_classify_entities_empty_concept_keywords_does_not_crash():
    entities = [{"canonical_name": "Magic", "type": "OTHER", "source_ids": [], "relevant": True}]
    result = classify_entities(entities, {}, {}, {}, "auto", concept_keywords=frozenset())
    assert result[0]["importance"] in ("principal", "secondary", "figurant", "ignored")
```

### Step 2: Run tests to verify they fail

```bash
pytest tests/test_entity_classification.py::test_normalize_entity_type_accepts_geo_suffixes_kwarg tests/test_entity_classification.py::test_is_role_entity_name_empty_role_words_returns_false -v
```

Expected: FAIL.

### Step 3: Implement the changes

In `scripts/entity_classification.py`:

1. **Delete** all 7 module-level constants (lines 47–81):
   `_GEO_KEYWORDS`, `_EVENT_KEYWORDS`, `_CONCEPT_KEYWORDS`, `_ROLE_WORDS`, `_ROLE_PATTERNS`, `_KNOWN_WORLD_PLACES`, `_GEO_SUFFIXES`.

2. **Update `_normalize_entity_type`** signature — add `geo_suffixes` parameter and remove `_KNOWN_WORLD_PLACES` check:

```python
def _normalize_entity_type(
    entity: dict,
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    events_full: dict,
    geo_keywords=None,
    event_keywords=None,
    concept_keywords=None,
    geo_suffixes=None,
) -> str:
    _geo = geo_keywords if geo_keywords is not None else frozenset()
    _evt = event_keywords if event_keywords is not None else frozenset()
    _concept = concept_keywords if concept_keywords is not None else frozenset()
    _geo_sfx = geo_suffixes if geo_suffixes is not None else frozenset()
    # ... rest of function unchanged except:
```

Replace the two PERSON-retag lines that used `_KNOWN_WORLD_PLACES` and `_GEO_SUFFIXES`:
```python
    if current_type == "PERSON":
        name_tokens = set(re.split(r"[\s'\-]+", lowered))
        if name_tokens & _geo_sfx:
            return "PLACE"
        geo_patterns = (
            rf"\b(?:kingdom|country|continent|empire)\s+of\s+{re.escape(lowered)}\b",
            rf"\b(?:royaume|pays|continent|empire)\s+(?:d'|de )?{re.escape(lowered)}\b",
            rf"\b{re.escape(lowered)}\s+(?:kingdom|country|continent|empire)\b",
        )
        if any(re.search(pattern, text) for pattern in geo_patterns):
            return "PLACE"
        return current_type
```

(Note: the `lowered in _KNOWN_WORLD_PLACES` check is simply removed — Task 5 adds entity_overrides to the ToG YAML instead.)

3. **Update `_is_role_entity_name`** — change default fallback from module constants to empty:

```python
def _is_role_entity_name(name: str, role_words=None, role_patterns=None) -> bool:
    _roles = role_words if role_words is not None else frozenset()
    _patterns = role_patterns if role_patterns is not None else ()
    # ... rest unchanged
```

4. **Update `classify_entities`** — change function signature defaults to empty:

```python
def classify_entities(
    entities: list[dict],
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    thresholds_config: str | dict,
    events_full: dict | None = None,
    geo_keywords=None,
    event_keywords=None,
    concept_keywords=None,
    role_words=None,
    role_patterns=None,
    geo_suffixes=None,
) -> list[dict]:
```

Inside `classify_entities`, wherever `_normalize_entity_type` is called, pass `geo_suffixes`:
```python
entity["type"] = _normalize_entity_type(
    entity, persons_full, places_full, orgs_full, events_full or {},
    geo_keywords=geo_keywords,
    event_keywords=event_keywords,
    concept_keywords=concept_keywords,
    geo_suffixes=geo_suffixes,
)
```

5. **Update `run_studio_mode()`** — load `geo_suffixes`, `role_words`, `role_patterns` from lang_config; remove fallback `or _CONSTANT` for concept_keywords:

```python
geo_keywords = frozenset(lang_cfg.get("geo_keywords", []))
event_keywords = frozenset(lang_cfg.get("event_keywords", []))
geo_suffixes = frozenset(lang_cfg.get("geo_suffixes", []))

classification = book_input.get("classification", {})
concept_keywords = frozenset(classification.get("concept_keywords", []))
role_words = frozenset(classification.get("role_words", [])) or frozenset(lang_cfg.get("role_words", []))
role_patterns = tuple(classification.get("role_patterns", [])) or tuple(lang_cfg.get("role_patterns", []))
```

Pass `geo_suffixes` through all downstream calls:
- In the normalization loop: `entity["type"] = _normalize_entity_type(..., geo_suffixes=geo_suffixes)`
- In `_canonicalize_role_entities`: already receives `role_words`/`role_patterns`
- In `classify_entities(...)`: add `geo_suffixes=geo_suffixes`

### Step 4: Run the full test suite

```bash
pytest tests/test_entity_classification.py -v
```

Expected: All PASS.

### Step 5: Commit

```bash
git add scripts/entity_classification.py tests/test_entity_classification.py
git commit -m "refactor(classification): remove all hardcoded word list constants, load from cue_words"
```

---

## Task 5 — Move `_KNOWN_WORLD_PLACES` to ToG book YAML

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

### Context

The 9 ToG-specific place names that were in `_KNOWN_WORLD_PLACES` now move to `entity_overrides`. `entity_overrides` with `force_type: PLACE` achieves the same result (retagging these as PLACE) at the override phase, which runs after type normalization.

### Step 1: No test needed

This is a config-only change. The existing `test_entity_classification.py` tests for `_apply_entity_overrides` with `force_type` already cover this behavior — no new test required.

### Step 2: Add to `entity_overrides` in the ToG YAML

In `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`, expand `entity_overrides`:

```yaml
entity_overrides:
  Nothung:
    force_type: OTHER
    exclude: true
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

### Step 3: Run the full test suite to verify nothing broke

```bash
pytest -q
```

Expected: 288+ passed (same as baseline, plus new tests).

### Step 4: Commit

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "chore(throne-of-glass): move known world places from hardcoded constant to entity_overrides"
```

---

## Task 6 — Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

### Step 1: Add rule to the Gotchas section

In `CLAUDE.md`, add to the **Gotchas** section:

```markdown
- Never add hardcoded word lists to scripts. All vocabulary belongs in
  `wiki_creator/cue_words/<lang>.json` (language-wide) or the book YAML `classification`
  section (book-specific). No script may define a fallback vocabulary constant — if a key
  is absent from cue_words, degrade gracefully to an empty collection.
```

### Step 2: Run full test suite one final time

```bash
pytest -q
```

Expected: All PASS.

### Step 3: Commit

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): rule against hardcoded word lists in scripts"
```

---

## Verification Checklist

After all tasks:

```bash
# No remaining hardcoded word-list constants in scripts
grep -n "_GEO_KEYWORDS\|_EVENT_KEYWORDS\|_CONCEPT_KEYWORDS\|_ROLE_WORDS\|_ROLE_PATTERNS\|_GEO_SUFFIXES\|_KNOWN_WORLD_PLACES\|_ACTION_CUES\|_PATTERN_TEMPLATES\|_REVEAL_WORDS" scripts/*.py
# Expected: no matches (only comments in design docs are acceptable)

# Full test suite
pytest -q
# Expected: all pass
```
