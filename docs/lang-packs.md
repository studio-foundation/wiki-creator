# Lang packs (`cue_words/<lang>.json`)

A **lang pack** is the per-language detection vocabulary the deterministic
pipeline runs on. One JSON file per language lives in
`wiki_creator/cue_words/` — `en.json`, `fr.json`, … — keyed by the language
code returned by `book_language()` (the book YAML `language:` key, else
inferred from `spacy_model`, else `fr`).

Everything language-specific in extraction, classification, resolution, POV
detection and the editorial-stance pass reads from here. **No vocabulary lives
in Python** (see `CLAUDE.md`): a script that needs words looks them up in the
pack and degrades to an empty collection if an *optional* key is absent.

## Loading and validation

`wiki_creator.lang.load_lang_config(language, *, allow_en_fallback=False)`
loads and validates the pack. It **fails loudly** — raising `LangPackError`
with an actionable message — when:

- the file `cue_words/<language>.json` does not exist,
- it is not readable JSON / not a JSON object,
- a **required** key (below) is missing.

There is **no implicit English fallback**. A book in an unsupported language
stops the run instead of being silently processed with English cue-words
(which would corrupt POV, type retagging, apposition and alias detection with
no error). The English fallback still exists but is **opt-in per call**: pass
`allow_en_fallback=True` to deliberately process a book with `en.json`.

## Adding a language

1. Copy `cue_words/en.json` to `cue_words/<code>.json` (e.g. `es.json`).
2. Translate/adapt every **required** key below to the target language. Keep
   the values lowercased, matching the existing packs.
3. Fill the **optional** keys your language needs (skip the rest — they default
   to empty).
4. Set `language: <code>` in the book YAML (or use a matching `spacy_model`).
5. Run `pytest tests/test_lang.py` — validation runs on load, so a missing key
   surfaces immediately.

You should not need to read pipeline code: the tables below say what each list
feeds. All values are plain JSON lists **except** `editorial_stance_markers`,
which is an object of three lists.

## Required keys

Present in every pack; a missing one is a hard error at load time.

| Key | Feeds | Role |
| --- | --- | --- |
| `place_cue_words` | extraction | Common nouns that hint a token names a place (`city`, `castle`). |
| `person_cue_words` | extraction, clustering, alias resolution | Titles/honorifics that hint a person (`king`, `sir`, `lady`). |
| `place_prepositions` | extraction | Prepositions preceding a location (`in`, `at`, `from`). |
| `event_suffixes` | extraction | Trailing nouns marking a named event (`ball`, `festival`, `eve`). |
| `pronouns` | POV, coref, relationship extraction, chapter summary | Full pronoun set of the language; excluded from entity names, used for coref. |
| `determiners` | chapter summary, alias resolution | Articles/demonstratives (`the`, `a`, `this`) stripped from name spans. |
| `noise_words` | chapter summary, cluster resolution | Filler words that must never survive as an entity name. |
| `coordination_connectors` | extraction | Words joining coordinated names (`and`, `&`) so they split correctly. |
| `reveal_words` | alias resolution | Phrases signalling a name reveal (`true name`, `alias`). |
| `geo_keywords` | classification | Geography nouns that push a PLACE toward the geographic sense. |
| `event_keywords` | classification | Nouns that classify an entity as an EVENT (`ceremony`, `feast`). |
| `alias_pattern_templates` | alias resolution | Regex templates (with `{a}`/`{b}` placeholders) matching "X also known as Y". |
| `action_cues` | event layer, chapter summary | Verbs that mark a narrative action, seeding event detection. |
| `geo_suffixes` | classification | Toponym suffixes (`mountains`, `river`, `isle`). |
| `role_words` | classification, facts, preparation, chapter summary, alias resolution | Role nouns (`captain`, `champion`) used for role facts and titles. |
| `role_patterns` | classification | Regexes capturing role phrases (`king's champion`). |
| `flashback_cues` | chapter summary | Phrases marking a flashback, setting `temporal_context`. |
| `first_person_pronouns` | POV (`parse_epub`) | First-person pronouns used to detect first-person narration. |
| `third_person_thought_markers` | POV, chapter summary | Phrases (`he thought`) marking third-person interiority. |
| `name_connectors` | grounding, clustering, alias resolution | Particles inside multi-word names (`of`, `de`, `van`). |
| `editorial_stance_markers` | consolidation (STU-508) | Object with `meta_narrative` / `reader_address` / `author` lists driving the editorial-stance drift pass. |

## Optional keys

A pack may omit these; the consumer degrades to an empty collection.

| Key | Feeds | Role |
| --- | --- | --- |
| `false_positive_words` | extraction, chapter summary | Words wrongly captured as entities in this language (empty for English). |
| `first_person_prefixes` | POV (`parse_epub`) | Elided first-person prefixes (French `j'`, `m'`); empty for English. |
| `elision_prefixes` | grounding | Elision prefixes stripped when matching names (French `l'`, `d'`); empty for English. |
| `first_person_artifact_tails` | extraction | Verb tails that flag a false "I …" entity artifact; language-specific. |
| `language_id_markers` | wiki page validator | Copula phrases (`is the`, `was a`) used to sanity-check generated prose language. |
| `placeholder_markers` | page generation | Prompt-placeholder phrases (`si connu`, `if known`) that flag a leaked template when echoed into a page. |

## The required/optional split

Required = the keys populated in **both** shipped packs (`en.json`, `fr.json`),
i.e. the vocabulary a working language genuinely needs. Optional = keys that are
empty or absent in at least one shipped pack because the language doesn't need
them or the list is advisory. `REQUIRED_KEYS` and `OPTIONAL_KEYS` in
`wiki_creator/lang.py` are the source of truth; the tables above mirror them.
