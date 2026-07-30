# Adding a language

Wiki Creator processes a book in its own language, and writes the wiki in it too.
Both halves are **data, not code** — two files, no Python change:

| File | What it drives |
| -- | -- |
| `wiki_creator/cue_words/<code>.json` | **Detection vocabulary**: extraction, clustering, alias resolution, classification, POV detection, the editorial-stance pass. |
| `wiki_creator/templates/lang/<code>.yaml` | **Output strings**: section headings, infobox row labels, navigation and spoiler chrome, writing briefs, the few-shot example, validator messages. |

They are separate on purpose: a lowercased word list tuned against a NER model
and a message catalogue read by a translator are different jobs with different
reviewers. A book only needs the first to be *processed*; it needs the second for
its **generated pages** to be in the language.

This guide is the task walkthrough. The companion reference,
[docs/lang-packs.md](lang-packs.md), documents the cue-words format and every key
in detail — keep it open beside this guide.

## What you need

- A working [dev setup](../CONTRIBUTING.md#dev-setup) (`pip install -e ".[dev]"`).
- A [spaCy model](#3-pick-a-spacy-model) for the target language.
- Optionally, an EPUB in the target language to validate on (any book will do —
  it does not have to ship with the repo).

## Steps

### 1. Create the cue-words pack

Copy the English pack and rename it to your language code (the two-letter code
`book_language()` returns — `es` for Spanish, `de` for German, …):

```bash
cp wiki_creator/cue_words/en.json wiki_creator/cue_words/es.json
```

Translate and adapt every **required** key to the target language, keeping values
**lowercased** and matching the shape of the existing packs. Then fill the
**optional** keys your language needs and delete the rest (an absent optional key
degrades to an empty collection). The full key-by-key table — what each list
feeds and whether it is required — is in
[lang-packs.md](lang-packs.md#required-keys).

Two things worth stressing while you translate:

- **Translate the _function_, not the word.** `person_cue_words` are titles and
  honorifics that hint a token names a person (`king`, `sir`, `lady`); give your
  language's equivalents, not a literal gloss of the English list.
- **Gendered-title keys are how the clusterer keeps `M.`/`Mme` apart.** If your
  language marks a masculine/feminine honorific distinction (Spanish
  `don`/`doña`, `señor`/`señora`), fill `masculine_titles` / `feminine_titles` —
  otherwise a married couple can merge into one entity. See the French and
  Spanish packs for the pattern.

There is **no silent English fallback**. A book in a language with no pack stops
the run with an actionable error rather than being processed with English
cue-words (which would quietly corrupt POV, apposition and alias detection). This
is why the pack must be complete before you run anything.

### 2. Create the template pack

Same move, for the strings the reader sees. Copy the English pack:

```bash
cp wiki_creator/templates/lang/en.yaml wiki_creator/templates/lang/es.yaml
```

Translate every value. `en.yaml` is the **reference pack** — it documents what
each block feeds, and it is required to hold every key, so a key you delete is a
key that renders in English on your wiki. Two values are not translations:

- **`language_name`** stays in English (`Spanish`, `German`). It names the
  language to an English-instructed writer; the reader never sees it.
- **`few_shot.infobox_fields`** keys are the infobox keys you want the writer to
  emit, so they follow your language (`nom` in French, `name` in English) — the
  example is what teaches the model the output shape.

Everything reader-facing resolves **requested language → `en`**. There is no
French fallback and no third chain; a language with no pack at all renders an
English wiki rather than failing the run.

`wiki_creator/templates/base.yaml` needs **no edit** — it holds structure only
(slots, provenance, tiers, the classifier criteria), and those stay English
whatever the wiki's language. See [adding a template](adding-a-template.md) if you
are adding a *token*, not a language.

### 3. Pick a spaCy model

spaCy still does the tokenizing, POS tagging and sentence splitting even when
GLiNER finds the entities, so every language needs a model. Two cases:

- **A stock spaCy model exists** for your language (`es_core_news_lg`,
  `de_core_news_lg`, …). Reference it in the book YAML as `spacy_model:` and
  declare it in the `[models]` extra in `pyproject.toml` if you want it installed
  by the extra. `book_language()` infers `fr`/`en` from stock model name
  prefixes; for any other language, set a top-level **`language: <code>`** key in
  the book YAML so the right pack is loaded (a non-`fr`/`en` model name is not
  inferable, and the loader raises rather than defaulting to English — STU-453).

- **No stock model, or a community/local model** (a path like
  `models/wiki-ner-xx/model-best`, or `xx_solipcysme_lg`). `book_language()`
  cannot infer the language from the name, so the book YAML **must** declare
  `language: <code>`. The loader appends generic per-language stock fallbacks, so
  a smaller sibling can degrade gracefully if the requested model is missing.

### 4. Validate both packs

Validation runs on load, so a missing key surfaces immediately:

```bash
pytest tests/test_lang.py tests/test_template_packs.py
```

`REQUIRED_KEYS` / `OPTIONAL_KEYS` in `wiki_creator/lang.py` are the source of
truth for the cue-words pack; `test_lang.py` loads every shipped pack and fails on
a missing required key. For the template pack, `en.yaml` **is** the required-key
list: `test_template_packs.py` loads every shipped pack and fails on a key present
in `en.yaml` and missing from yours — or declared in yours and absent from
`en.yaml`.

### 5. Validate on a book

The packs passing validation means they are *well-formed*, not that the vocabulary
and the copy are *right*. Prove it on a real book:

1. Put an EPUB in the target language under `library/<author>/<series>/books/`
   with a minimal book YAML (`wiki book add path/to.epub` scaffolds one), setting
   `language: <code>`.
2. Run extraction on the first few chapters to keep it fast:

   ```bash
   WIKI_MAX_CHAPTERS=3 wiki book extraction <alias>
   ```

3. Inspect the extracted entities in
   `processing_output/<slug>/`. Look for the failure modes the vocabulary
   controls: common nouns leaking in as entities (tighten `noise_words` /
   `false_positive_words`), a title not being stripped from a name (`title_prefixes`
   / `person_cue_words`), places typed as people, POV misdetected. Adjust the pack
   and re-run.

A subset run answers a different question than a full one — never measure a
*premise* on `WIKI_MAX_CHAPTERS` (a cover-identity reveal, a late death). It is
fine for checking that the vocabulary catches the obvious cases.

## Submitting

Open a PR (see [CONTRIBUTING.md](../CONTRIBUTING.md#pull-requests)) with:

- The new `cue_words/<code>.json`.
- The new `templates/lang/<code>.yaml`.
- Any `pyproject.toml` `[models]` addition if you wired a stock model.
- A note on how you validated it (which book, what you checked).
