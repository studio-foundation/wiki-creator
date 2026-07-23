# Adding a language

Wiki Creator processes a book in its own language: extraction, clustering, alias
resolution, classification, POV detection and the editorial-stance pass all read
their vocabulary from a **lang pack** — one `cue_words/<lang>.json` per language.
Adding a language is the contribution that lets the tool serve a new community,
and it is **data, not code**: you write a JSON file and validate it on a book. No
Python change is needed.

This guide is the task walkthrough. The companion reference,
[docs/lang-packs.md](lang-packs.md), documents the pack format and every key in
detail — keep it open beside this guide.

## What you need

- A working [dev setup](../CONTRIBUTING.md#dev-setup) (`pip install -e ".[dev]"`).
- A [spaCy model](#2-pick-a-spacy-model) for the target language.
- Optionally, an EPUB in the target language to validate on (any book will do —
  it does not have to ship with the repo).

## Steps

### 1. Create the lang pack

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

### 2. Pick a spaCy model

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

### 3. Validate the pack

Validation runs on load, so a missing required key surfaces immediately:

```bash
pytest tests/test_lang.py
```

`REQUIRED_KEYS` / `OPTIONAL_KEYS` in `wiki_creator/lang.py` are the source of
truth for what must be present; the test loads every shipped pack and fails on a
missing required key.

### 4. Validate on a book

The pack passing validation means it is *well-formed*, not that its vocabulary is
*right*. Prove it on a real book:

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
- Any `pyproject.toml` `[models]` addition if you wired a stock model.
- A note on how you validated it (which book, what you checked). Page generation
  and validation strings (`base.yaml`) also localize by output language — if your
  language needs generated pages, add its column to the relevant `base.yaml` maps
  too and see [adding a template](adding-a-template.md).
