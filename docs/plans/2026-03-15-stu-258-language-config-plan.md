# Language Config Externalization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove all hardcoded language word lists from scripts by externalizing them to `wiki_creator/cue_words/<lang>.json` (language-generic) or the book YAML `classification:` block (book-specific).

**Architecture:** New `wiki_creator/lang.py` provides `load_lang_config(language)` and `infer_language(spacy_model)` shared by all scripts. Existing `cue_words/*.json` files gain new top-level keys. Book YAML gains a `classification:` block for series-specific keyword lists. Scripts read language from `additional_context` and call the shared loader.

**Tech Stack:** Python, JSON, YAML (`yaml.safe_load`), pytest, existing `wiki_creator/cue_words/` pattern.

---

### Task 1: Create `wiki_creator/lang.py` with loader and language inference

**Files:**
- Create: `wiki_creator/lang.py`
- Create: `tests/test_lang.py`

**Step 1: Write the failing test**

```python
# tests/test_lang.py
from wiki_creator.lang import infer_language, load_lang_config


def test_infer_language_fr():
    assert infer_language("fr_core_news_lg") == "fr"
    assert infer_language("fr_core_news_sm") == "fr"


def test_infer_language_en():
    assert infer_language("en_core_web_lg") == "en"
    assert infer_language("") == "en"


def test_load_lang_config_en_has_required_keys():
    cfg = load_lang_config("en")
    for key in ("pronouns", "noise_words", "reveal_words", "geo_keywords",
                "event_keywords", "coordination_connectors",
                "first_person_artifact_tails", "false_positive_words"):
        assert key in cfg, f"missing key: {key}"


def test_load_lang_config_fr_has_required_keys():
    cfg = load_lang_config("fr")
    for key in ("pronouns", "noise_words", "reveal_words", "geo_keywords",
                "event_keywords", "coordination_connectors",
                "false_positive_words"):
        assert key in cfg, f"missing key: {key}"


def test_load_lang_config_fr_pronouns_contains_elle():
    cfg = load_lang_config("fr")
    assert "elle" in cfg["pronouns"]


def test_load_lang_config_unknown_falls_back_to_en():
    cfg = load_lang_config("xx")
    assert "pronouns" in cfg
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_lang.py -v
```
Expected: ImportError or AssertionError — `wiki_creator/lang.py` does not exist yet.

**Step 3: Write minimal implementation**

```python
# wiki_creator/lang.py
import json
from pathlib import Path

_CUE_WORDS_DIR = Path(__file__).parent / "cue_words"


def infer_language(spacy_model: str) -> str:
    """Infer language code from spaCy model name. Returns 'fr' or 'en'."""
    model = (spacy_model or "").strip().lower()
    if model.startswith("fr_core_news_"):
        return "fr"
    return "en"


def load_lang_config(language: str) -> dict:
    """Load wiki_creator/cue_words/<language>.json as a plain dict.

    Falls back to 'en' if the requested language file is not found.
    Values are plain lists (not frozensets) to stay JSON-round-trip friendly.
    """
    path = _CUE_WORDS_DIR / f"{language}.json"
    if not path.exists():
        path = _CUE_WORDS_DIR / "en.json"
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
```

**Step 4: Run test to verify it fails on missing JSON keys** (the JSON files don't have the new keys yet — that's Task 2)

```bash
pytest tests/test_lang.py -v
```
Expected: AssertionError on `missing key: pronouns` — correct, JSON not yet extended.

**Step 5: Commit the loader (tests still failing — that's expected)**

```bash
git add wiki_creator/lang.py tests/test_lang.py
git commit -m "feat(STU-258): add wiki_creator/lang.py with load_lang_config and infer_language"
```

---

### Task 2: Extend `cue_words/en.json` and `cue_words/fr.json` with new keys

**Files:**
- Modify: `wiki_creator/cue_words/en.json`
- Modify: `wiki_creator/cue_words/fr.json`

**Step 1: Add new keys to `wiki_creator/cue_words/en.json`**

Replace the file content with (keep existing keys, add new ones):

```json
{
  "place_cue_words": [
    "city", "town", "capital", "kingdom", "continent", "country",
    "castle", "palace", "camp", "mine", "mines", "forest", "woods",
    "river", "sea", "port", "harbor", "street", "road", "avenue"
  ],
  "person_cue_words": [
    "prince", "princess", "king", "queen", "duke", "lady", "lord",
    "captain", "sir", "mr", "mrs", "miss"
  ],
  "place_prepositions": [
    "in", "at", "from", "to", "into", "through", "within", "inside", "outside"
  ],
  "event_suffixes": [
    "ball", "festival", "feast", "ceremony", "celebration",
    "prayer", "prayers", "blessing", "blessings", "morning", "night", "eve"
  ],
  "pronouns": [
    "he", "she", "they", "him", "her", "them", "his", "hers", "their",
    "it", "its", "himself", "herself", "themselves", "itself"
  ],
  "determiners": ["the", "a", "an", "this", "that", "these", "those"],
  "noise_words": [
    "yes", "no", "ok", "the", "a", "an", "and", "or", "but",
    "here", "there", "it", "he", "she", "they", "we"
  ],
  "false_positive_words": [],
  "first_person_artifact_tails": [
    "am", "have", "had", "would", "will", "win", "can", "could", "do", "did",
    "know", "knew", "see", "saw", "like", "suppose", "think", "guess",
    "mean", "want", "need", "tell", "told", "say", "said", "feel", "felt",
    "look", "looked", "might", "must", "shall", "should"
  ],
  "coordination_connectors": ["and", "&"],
  "reveal_words": [
    "another name", "other name", "under another name",
    "true name", "real name", "hidden identity", "alias"
  ],
  "geo_keywords": [
    "kingdom", "country", "continent", "city", "town", "capital", "empire",
    "land", "lands", "coast", "sea", "mountains", "forest"
  ],
  "event_keywords": [
    "festival", "feast", "ceremony", "celebration", "ritual", "holiday", "eve"
  ]
}
```

**Step 2: Add new keys to `wiki_creator/cue_words/fr.json`**

Replace the file content with (keep existing keys, add new ones):

```json
{
  "place_cue_words": [
    "ville", "royaume", "continent", "pays", "château", "chateau", "palais",
    "camp", "mine", "forêt", "foret", "rivière", "riviere", "mer",
    "port", "rue", "route", "avenue"
  ],
  "person_cue_words": [
    "prince", "princesse", "roi", "reine", "duc", "dame", "seigneur",
    "capitaine", "sir", "monsieur", "madame", "mademoiselle"
  ],
  "place_prepositions": [
    "dans", "à", "a", "de", "depuis", "vers", "au", "aux", "en"
  ],
  "event_suffixes": [
    "bal", "festival", "fête", "fete", "cérémonie", "ceremonie",
    "célébration", "celebration", "prières", "prieres", "bénédiction",
    "benediction", "matin", "nuit", "veille"
  ],
  "pronouns": [
    "il", "elle", "ils", "elles", "lui", "leur",
    "le", "la", "les", "l'", "l\u2019", "y", "en",
    "se", "s'", "s\u2019"
  ],
  "determiners": ["le", "la", "les", "un", "une", "des", "du", "de"],
  "noise_words": [
    "oui", "non", "ah", "oh", "eh", "ok",
    "le", "la", "les", "un", "une", "des",
    "et", "ou", "mais", "donc", "or", "ni", "car",
    "ici", "là", "que", "qui", "quoi",
    "ça", "ce", "cet", "cette", "ces"
  ],
  "false_positive_words": [
    "cher", "chère", "chers", "chères",
    "monsieur", "madame", "mademoiselle",
    "excusez", "pardonnez", "intéressant",
    "merci", "bonjour", "bonsoir", "adieu"
  ],
  "coordination_connectors": ["et", "y"],
  "reveal_words": [
    "sous un autre nom", "vrai nom", "nom réel",
    "identité cachée", "alias", "également connu sous"
  ],
  "geo_keywords": [
    "royaume", "pays", "ville", "capitale", "empire", "continent",
    "côte", "mer", "montagne", "forêt"
  ],
  "event_keywords": [
    "fête", "fete", "cérémonie", "ceremonie",
    "célébration", "celebration", "rite", "rituel"
  ]
}
```

**Step 3: Run Task 1 tests — they should now pass**

```bash
pytest tests/test_lang.py -v
```
Expected: all PASS.

**Step 4: Run full suite to make sure nothing broke**

```bash
pytest -q
```
Expected: all previously-passing tests still pass.

**Step 5: Commit**

```bash
git add wiki_creator/cue_words/en.json wiki_creator/cue_words/fr.json
git commit -m "feat(STU-258): extend cue_words/en.json and fr.json with pronouns, noise_words, reveal_words, and other lang keys"
```

---

### Task 3: Move language inference to `wiki_creator/lang.py`; update `entity_extraction.py`

**Files:**
- Modify: `scripts/entity_extraction.py`
- Modify: `tests/test_entity_extraction.py`

The goal here is to:
1. Import `infer_language` from `wiki_creator.lang` instead of the private `_infer_cue_words_language`
2. Replace `FALSE_POSITIVE_WORDS`, `FIRST_PERSON_ARTIFACT_TAILS_EN`, `COORDINATION_CONNECTORS` with values loaded from lang config
3. Keep the public names as module-level variables (tests import them directly)

**Step 1: Check which tests import these constants**

```bash
grep -n "FALSE_POSITIVE_WORDS\|FIRST_PERSON_ARTIFACT\|COORDINATION_CONNECTORS\|_infer_cue_words_language\|_resolve_cue_words_language" tests/test_entity_extraction.py
```

Note the imports — we need to keep them working.

**Step 2: Update imports and constants in `entity_extraction.py`**

At the top of the file, add:
```python
from wiki_creator.lang import infer_language as _infer_lang, load_lang_config as _load_lang_config
```

Replace `_infer_cue_words_language` body to delegate:
```python
def _infer_cue_words_language(spacy_model: str) -> str:
    """Infer cue-word language from spaCy model name. Delegates to wiki_creator.lang."""
    return _infer_lang(spacy_model)
```

Replace the module-level constant definitions (lines ~281-303) with dynamic loading.
Use `"en"` as the default language for the module-level constants (English books are the common case for these particular constants; FR false_positive_words are loaded at runtime per book):

```python
# Load from lang config — populated at import time with English defaults.
# Scripts that process non-English books re-load these at runtime.
_en_lang = _load_lang_config("en")
_fr_lang = _load_lang_config("fr")

FALSE_POSITIVE_WORDS: frozenset[str] = frozenset(_fr_lang.get("false_positive_words", []))
COORDINATION_CONNECTORS: frozenset[str] = frozenset(
    _en_lang.get("coordination_connectors", []) | set(_fr_lang.get("coordination_connectors", []))
)
FIRST_PERSON_ARTIFACT_TAILS_EN: frozenset[str] = frozenset(
    _en_lang.get("first_person_artifact_tails", [])
)
```

**Step 3: Run the affected tests**

```bash
pytest tests/test_entity_extraction.py -v -k "false_positive or FIRST_PERSON or COORDINATION or infer_cue"
```
Expected: all PASS (public names still exist, values same as before).

**Step 4: Run full suite**

```bash
pytest -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add scripts/entity_extraction.py
git commit -m "feat(STU-258): load FALSE_POSITIVE_WORDS, COORDINATION_CONNECTORS, FIRST_PERSON_ARTIFACT_TAILS_EN from lang config"
```

---

### Task 4: Update `resolve_clusters.py` — replace `_NOISE_WORDS`

**Files:**
- Modify: `scripts/resolve_clusters.py`
- Modify: `tests/test_split_clusters.py` (check if noise words are tested; probably not directly)

**Step 1: Understand the call chain**

`is_relevant(name)` is called from `cluster_to_entity()` called from `resolve()` called from `main()`. The cleanest minimal change: add an optional `noise_words` param to `is_relevant`, `cluster_to_entity`, and `resolve`, defaulting to the current combined set. `main()` loads the language-specific set and passes it through.

**Step 2: Write a test for the new param signature**

Add to `tests/test_split_clusters.py` (or wherever `resolve_clusters` is tested):

```python
from scripts.resolve_clusters import is_relevant


def test_is_relevant_respects_custom_noise_words():
    custom = frozenset({"TESTWORD"})
    assert not is_relevant("TESTWORD", noise_words=custom)
    assert is_relevant("TESTWORD")  # not in default noise_words
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/ -v -k "test_is_relevant_respects_custom_noise_words"
```
Expected: TypeError — `is_relevant` takes 1 argument.

**Step 4: Update `resolve_clusters.py`**

Add import at top:
```python
from wiki_creator.lang import load_lang_config
```

Replace `_NOISE_WORDS` definition with a combined default (same words as today, loaded from JSON):

```python
def _default_noise_words() -> frozenset[str]:
    en = frozenset(load_lang_config("en").get("noise_words", []))
    fr = frozenset(load_lang_config("fr").get("noise_words", []))
    return en | fr

_NOISE_WORDS = _default_noise_words()
```

Update function signatures:

```python
def is_relevant(name: str, noise_words: frozenset[str] = _NOISE_WORDS) -> bool:
    ...
    if cleaned.lower() in noise_words:
    ...

def cluster_to_entity(cluster: dict, noise_words: frozenset[str] = _NOISE_WORDS) -> dict:
    ...
    "relevant": is_relevant(cluster.get("canonical_candidate", ""), noise_words),
    ...

def resolve(splits: dict, noise_words: frozenset[str] = _NOISE_WORDS) -> dict:
    ...
    entities.append(cluster_to_entity(cluster, noise_words))
    ...
```

Update `main()` to load language from `additional_context` and pass noise_words:

```python
def main() -> None:
    payload = json.load(sys.stdin)
    previous_outputs = payload.get("previous_outputs", {})
    splits = previous_outputs.get("split-clusters", {})

    if not splits:
        print("Warning: split-clusters output not found in previous_outputs", file=sys.stderr)

    # Load language-specific noise words if language is available
    noise_words = _NOISE_WORDS
    raw_context = payload.get("additional_context", "")
    if raw_context:
        try:
            ctx = yaml.safe_load(raw_context) or {}
            language = ctx.get("export", {}).get("categories", {}).get("language") or \
                       ctx.get("language") or "en"
            noise_words = frozenset(load_lang_config(language).get("noise_words", [])) or _NOISE_WORDS
        except Exception:
            pass

    result = resolve(splits, noise_words=noise_words)
    json.dump(result, sys.stdout, ensure_ascii=False)
```

Also add `import yaml` if not already present.

**Step 5: Run tests**

```bash
pytest tests/ -v -k "resolve_cluster or split_cluster or is_relevant"
```
Expected: all PASS.

**Step 6: Full suite**

```bash
pytest -q
```

**Step 7: Commit**

```bash
git add scripts/resolve_clusters.py tests/test_split_clusters.py
git commit -m "feat(STU-258): load _NOISE_WORDS from lang config in resolve_clusters.py"
```

---

### Task 5: Update `alias_resolution.py` — replace `_REVEAL_WORDS`

**Files:**
- Modify: `scripts/alias_resolution.py`
- Modify: `tests/test_alias_resolution.py`

**Step 1: Find where language is available in `alias_resolution.py`**

The script already parses `additional_context` in `_paths_from_payload`. Language can be read the same way as in Task 4.

**Step 2: Write a failing test**

Find in `tests/test_alias_resolution.py` the test for `detect_named_aliases` or similar. Add:

```python
def test_detect_named_aliases_uses_reveal_words_from_lang():
    """reveal_words can be customised per call."""
    from scripts.alias_resolution import detect_named_aliases
    entity_a = {"canonical_name": "Celaena", "aliases": ["Celaena"]}
    entity_b = {"canonical_name": "Laena", "aliases": ["Laena"]}
    context = "Celaena, sous un autre nom Laena, traversa la pièce."
    pairs = detect_named_aliases(
        [entity_a, entity_b],
        {"ch01": context},
        reveal_words=("sous un autre nom",),
    )
    assert any(p["entity_a"] == "Celaena" or p["entity_b"] == "Celaena" for p in pairs)
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/test_alias_resolution.py -v -k "reveal_words_from_lang"
```
Expected: TypeError — `detect_named_aliases` doesn't accept `reveal_words` kwarg.

**Step 4: Update `alias_resolution.py`**

Add import at top:
```python
from wiki_creator.lang import load_lang_config, infer_language
```

Change `detect_named_aliases` signature to accept optional `reveal_words`:

```python
def detect_named_aliases(
    entities: list[dict],
    mentions_by_entity: dict[str, list[str]],
    window_size: int = _WINDOW_SIZE,
    reveal_words: tuple[str, ...] | None = None,
) -> list[AliasPair]:
    if reveal_words is None:
        reveal_words = _REVEAL_WORDS
    ...
    # Replace all uses of _REVEAL_WORDS inside the function with reveal_words
```

In `main()`, after parsing `additional_context`, load reveal_words:

```python
raw_context = payload.get("additional_context", "")
ctx = yaml.safe_load(raw_context or "") or {}
spacy_model = ctx.get("spacy_model", "en_core_web_lg")
language = ctx.get("export", {}).get("categories", {}).get("language") \
           or infer_language(spacy_model)
lang_cfg = load_lang_config(language)
reveal_words = tuple(lang_cfg.get("reveal_words", _REVEAL_WORDS))
```

Pass `reveal_words` into `detect_named_aliases(...)` call.

**Step 5: Run tests**

```bash
pytest tests/test_alias_resolution.py -v
```
Expected: all PASS.

**Step 6: Full suite**

```bash
pytest -q
```

**Step 7: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-258): load _REVEAL_WORDS from lang config in alias_resolution.py"
```

---

### Task 6: Update `entity_classification.py` — lang config + book YAML `classification:` block

**Files:**
- Modify: `scripts/entity_classification.py`
- Modify: `tests/test_entity_classification.py`

**Step 1: Check how `classify_entities` is called and what tests exist**

```bash
grep -n "classify_entities\|_GEO_KEYWORDS\|_EVENT_KEYWORDS\|_CONCEPT\|_ROLE" tests/test_entity_classification.py | head -20
```

**Step 2: Write failing tests**

Add to `tests/test_entity_classification.py`:

```python
def test_classify_entities_uses_custom_geo_keywords():
    from scripts.entity_classification import classify_entities
    entities = [{"canonical_name": "Arendelle", "type": "PLACE", "relevant": True, "aliases": []}]
    # "glacière" is not in default geo_keywords — but if passed, should influence classification
    result = classify_entities(entities, {}, {}, {}, {}, geo_keywords=frozenset({"glacière"}))
    # Just verify it runs without error and returns entities
    assert isinstance(result, list)


def test_classify_entities_uses_book_classification_block():
    from scripts.entity_classification import classify_entities
    entities = [{"canonical_name": "wyrdmark", "type": "OTHER", "relevant": True, "aliases": []}]
    result = classify_entities(
        entities, {}, {}, {}, {},
        concept_keywords=frozenset({"wyrdmark"}),
    )
    assert result[0]["type"] == "OTHER"  # concept → OTHER, not reassigned
```

**Step 3: Run tests to verify they fail**

```bash
pytest tests/test_entity_classification.py -v -k "custom_geo or book_classification"
```
Expected: TypeError — `classify_entities` doesn't accept these kwargs.

**Step 4: Update `entity_classification.py`**

Add imports:
```python
from wiki_creator.lang import load_lang_config, infer_language
```

Update `classify_entities` signature to accept optional overrides:

```python
def classify_entities(
    entities: list[dict],
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    events_full: dict,
    geo_keywords: frozenset[str] | None = None,
    event_keywords: frozenset[str] | None = None,
    concept_keywords: frozenset[str] | None = None,
    role_words: frozenset[str] | None = None,
    role_patterns: tuple[str, ...] | None = None,
) -> list[dict]:
    # Use passed values or fall back to module-level constants
    _geo = geo_keywords if geo_keywords is not None else _GEO_KEYWORDS
    _evt = event_keywords if event_keywords is not None else _EVENT_KEYWORDS
    _concept = concept_keywords if concept_keywords is not None else _CONCEPT_KEYWORDS
    _roles = role_words if role_words is not None else _ROLE_WORDS
    _patterns = role_patterns if role_patterns is not None else _ROLE_PATTERNS
    ...
```

Replace all internal uses of `_GEO_KEYWORDS`, `_EVENT_KEYWORDS`, `_CONCEPT_KEYWORDS`, `_ROLE_WORDS`, `_ROLE_PATTERNS` with the local `_geo`, `_evt`, `_concept`, `_roles`, `_patterns` variables inside the function.

Do the same for `_normalize_entity_type` and `_is_role_entity_name` — they use `_GEO_KEYWORDS`, `_EVENT_KEYWORDS`, `_CONCEPT_KEYWORDS`, `_ROLE_WORDS`, `_ROLE_PATTERNS`. You can either:
- Thread params through each helper, OR
- Inline the logic into `classify_entities` using the local vars

Simplest: thread as keyword-only args through the private helpers that need them.

In `main()`, after parsing `additional_context`:

```python
additional_ctx = payload.get("additional_context", "")
book_input = yaml.safe_load(additional_ctx) if additional_ctx else {}
# ... existing thresholds/entity_overrides parsing ...

# Load language-specific keyword sets
spacy_model = book_input.get("spacy_model", "en_core_web_lg")
language = book_input.get("export", {}).get("categories", {}).get("language") \
           or infer_language(spacy_model)
lang_cfg = load_lang_config(language)

geo_keywords = frozenset(lang_cfg.get("geo_keywords", []))
event_keywords = frozenset(lang_cfg.get("event_keywords", []))

# Load book-specific classification hints
classification = book_input.get("classification", {})
concept_keywords = frozenset(classification.get("concept_keywords", [])) or _CONCEPT_KEYWORDS
role_words = frozenset(classification.get("role_words", [])) or _ROLE_WORDS
role_patterns = tuple(classification.get("role_patterns", [])) or _ROLE_PATTERNS
```

Pass all these into `classify_entities(...)`.

**Step 5: Run tests**

```bash
pytest tests/test_entity_classification.py -v
```

**Step 6: Full suite**

```bash
pytest -q
```

**Step 7: Commit**

```bash
git add scripts/entity_classification.py tests/test_entity_classification.py
git commit -m "feat(STU-258): load geo/event keywords from lang config and concept/role words from book YAML in entity_classification.py"
```

---

### Task 7: Update `relationship_extraction.py` — replace `_FR_PRONOUNS` and hardcoded `fr_core_news_lg`

**Files:**
- Modify: `scripts/relationship_extraction.py`
- Modify: `tests/test_relationship_extraction.py`

**Step 1: Understand the 3 hardcoded `fr_core_news_lg` locations**

There are 3 places: in `enrich_mentions_with_heuristic` (~line 259), in `enrich_mentions_with_fastcoref` sequential path (~line 545), and in `_coref_worker` (~line 468).

`_coref_worker` is a top-level function called by `ProcessPoolExecutor`, receiving args as a tuple `(chapter_id, text, name_to_canonical)`. The `spacy_model` must be added as element 3.

**Step 2: Write failing tests**

In `tests/test_relationship_extraction.py`, add:

```python
def test_enrich_mentions_heuristic_accepts_pronouns_param():
    from scripts.relationship_extraction import enrich_mentions_with_heuristic
    import spacy
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    entities = [{"canonical_name": "Alice", "type": "PERSON", "relevant": True, "aliases": []}]
    mentions = {"Alice": {"ch01": ["Alice walked in."]}}
    chapters = {"ch01": "Alice walked in. She smiled."}
    # Should not raise even with custom pronouns
    result = enrich_mentions_with_heuristic(
        chapters, entities, mentions, nlp=nlp, pronouns=frozenset({"she"})
    )
    assert isinstance(result, dict)


def test_coref_worker_accepts_spacy_model_in_args():
    from scripts.relationship_extraction import _coref_worker
    # Worker must unpack 4 elements: (chapter_id, text, name_to_canonical, spacy_model)
    result = _coref_worker(("ch01", "", {}, "en_core_web_sm"))
    assert result == []  # empty text → empty result
```

**Step 3: Run tests to verify they fail**

```bash
pytest tests/test_relationship_extraction.py -v -k "pronouns_param or spacy_model_in_args"
```

**Step 4: Update `relationship_extraction.py`**

Add imports near the top:
```python
from wiki_creator.lang import load_lang_config, infer_language
```

Remove `_FR_PRONOUNS` module-level constant.

Update `enrich_mentions_with_heuristic` signature:
```python
def enrich_mentions_with_heuristic(
    chapters: dict[str, str],
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    nlp=None,
    silence_window: int = 3,
    pronouns: frozenset[str] | None = None,
) -> dict[str, dict[str, list[str]]]:
    if pronouns is None:
        pronouns = frozenset(load_lang_config("fr").get("pronouns", []))
    ...
    # Replace all uses of _FR_PRONOUNS with pronouns
```

Update `_coref_worker` to unpack 4-tuple:
```python
def _coref_worker(args: tuple) -> list[tuple[str, str, str]]:
    chapter_id, text, name_to_canonical, spacy_model = args
    ...
    nlp = spacy.load(
        spacy_model,
        exclude=["parser", "lemmatizer", "ner", "textcat"],
    )
```

Update `enrich_mentions_with_fastcoref` to pass `spacy_model` in the args tuple and to use it in the sequential path:
```python
def enrich_mentions_with_fastcoref(
    chapters, entities, mentions_by_entity, workers=1, spacy_model="fr_core_news_lg"
):
    ...
    # Sequential path:
    nlp = spacy.load(spacy_model, exclude=[...])
    ...
    # Parallel path — build args with spacy_model:
    args_list = [(cid, text, name_to_canonical, spacy_model) for cid, text in ...]
```

In `main()`, read language/spacy_model from `additional_context`:
```python
additional = yaml.safe_load(raw_context) or {}
spacy_model = additional.get("spacy_model", "fr_core_news_lg")
language = additional.get("export", {}).get("categories", {}).get("language") \
           or infer_language(spacy_model)
lang_cfg = load_lang_config(language)
pronouns = frozenset(lang_cfg.get("pronouns", []))
```

Pass `pronouns` to `enrich_mentions_with_heuristic(...)` and `spacy_model` to `enrich_mentions_with_fastcoref(...)`.

**Step 5: Run tests**

```bash
pytest tests/test_relationship_extraction.py -v
```

**Step 6: Full suite**

```bash
pytest -q
```

**Step 7: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-258): load pronouns from lang config, replace hardcoded fr_core_news_lg with spacy_model param in relationship_extraction.py"
```

---

### Task 8: Add `classification:` block to the Throne of Glass book YAML

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Step 1: Add the block**

After the `export:` block, add:

```yaml
classification:
  concept_keywords:
    - wyrdmark
    - wyrdmarks
    - magic
    - marque
    - marques
    - spell
    - spells
    - sigil
    - sigils
    - symbol
    - symbols
    - système
    - systeme
    - system
  role_words:
    - assassin
    - champion
    - "king's champion"
    - "adarlan's assassin"
    - queen
    - king
    - prince
    - princess
    - lady
    - lord
    - captain
    - guard
  role_patterns:
    - '\b[a-z][a-z''\- ]*assassin\b'
    - '\b[a-z][a-z''\- ]*champion\b'
    - '\bking''?s champion\b'
```

**Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml'))"
```
Expected: no output (no error).

**Step 3: Run full suite**

```bash
pytest -q
```
Expected: all pass.

**Step 4: Commit**

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(STU-258): add classification block with concept_keywords, role_words, role_patterns to Throne of Glass book YAML"
```

---

### Task 9: Final verification

**Step 1: Run the full test suite**

```bash
pytest -q
```
Expected: all tests pass (same count as before, no regressions).

**Step 2: Confirm no hardcoded language words remain in scripts**

```bash
grep -n "fr_core_news_lg\|_FR_PRONOUNS\|FALSE_POSITIVE_WORDS\s*=\s*frozenset\|FIRST_PERSON_ARTIFACT_TAILS_EN\s*=\s*frozenset\|COORDINATION_CONNECTORS\s*=\s*frozenset\|_NOISE_WORDS\s*=\s*frozenset\|_REVEAL_WORDS\s*=\s*(" scripts/*.py
```
Expected: no matches (all replaced by config loading).

**Step 3: Commit**

No code changes — this is just verification. If issues are found, fix and commit per the relevant task above.
