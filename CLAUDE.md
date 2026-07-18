# CLAUDE.md

## Project Snapshot

- Repo: `wiki-creator-by-studio`
- Purpose: extract entities from EPUB novels, classify them, generate wiki pages, export wikitext
- Current verified state on 2026-07-15: `pytest -q` => `1604 passed, 1 skipped`
  (skip count depends on which optional models/extras are installed; see `tests/_markers.py`)

## Commands

```bash
pip install -e ".[dev]"      # test suite: carries en_core_web_sm
pip install -e ".[models]"   # to run a book: the lg models the books declare (~1 GB)
pytest -q
mypy wiki_creator/

make run
make run-extraction
make run-resolution
make run-preparation
make generate-pages
make generate-pages-dry
make generate-synopsis
make generate-synopsis-dry
make consolidate-stance
make pages-export
make run-generation
make run-from-resolution
make run-from-preparation
make run-from-generation
make run-status
make smoke        # e2e smoke test on the committed fixture novella
make golden       # golden regression run: chained resolution stages vs committed goldens (~2s, no spaCy/LLM)
make golden-update  # regenerate goldens after an INTENTIONAL behavior change, then review the diff
```

Default `BOOK` in the `Makefile`:

```bash
library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
```

## Actual Pipeline Layout

Primary workflow:
1. `wiki-extraction`
2. `wiki-resolution`
3. `wiki-preparation`
4. `python scripts/generate_wiki_pages.py --book <book.yaml>`
5. `pages-export`

Important:
- `.studio/pipelines/wiki-generation.pipeline.yaml` still exists, but the repo-level workflow uses the split path above.
- **Disk is the bus across pipelines (STU-455).** A stage reads an artifact written
  by an *earlier pipeline* from disk, never from Studio's context — those are
  separate `studio run` invocations, so `previous_outputs`/`all_stage_outputs`
  are empty of it by construction. Studio's context is only for stages that
  really do chain in memory inside one pipeline (resolve-clusters →
  merge-entities, chapter-summary → wiki-preparation).
  Four `load_*.py` stages existed to fake the difference: they re-read a JSON the
  previous pipeline had already written and re-emitted it as a stage output, so
  the YAML declared a graph the filesystem was actually carrying. Three were pure
  passe-plat and are deleted; their consumers (`resolve_clusters`,
  `chapter_summary`, `wiki_preparation`, `wiki_export`) read the artifact
  themselves — which several already did as a fallback, and that fallback was the
  only path that ever ran.
  The fourth, `load_wiki_pages.py`, was **not** a loader and is renamed
  `assemble_wiki_pages.py`: it assembles the export's page set from four
  artifacts, drops `_failed` pages, and does the STU-506 title disambiguation.
  Deleting the stage would have dropped its `wiki-page` contract check — the
  point was to stop lying about propagation, not to lose validation.
  The ticket proposed a second model — Studio context carrying artifact
  *references* (path + schema). Rejected: `paths_from_payload` already derives
  every path from `additional_context`, so a reference is a layer transporting
  what the payload transports, and it needs a Studio capability nobody needs.
  **A wiring test pins each disk read against a contradictory in-memory payload**
  (`test_main_reads_splits_from_disk_not_from_stage_context`) — without it, a
  reinstated loader passes the whole suite green, goldens included: the golden
  chain spans pipelines and hands `previous_outputs` to every stage.
  Reading the artifact also puts it through STU-447 validation, which the
  in-memory path skipped — an entity missing `total_mentions` now fails at
  wiki-preparation instead of reaching a page.

## Path Model

Paths are derived from the book yaml/epub using [wiki_creator/paths.py](/home/arianeguay/dev/src/wiki-creator-by-studio/wiki_creator/paths.py).

For a book like:

```text
library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
```

the project writes to:

```text
library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/
library/sarah_j_maas/throne-of-glass/wiki_inputs/01-throne-of-glass/
library/sarah_j_maas/throne-of-glass/output/01-throne-of-glass/
```

## Files To Know

- [Makefile](/home/arianeguay/dev/src/wiki-creator-by-studio/Makefile): command entrypoints
- [run_wiki.py](/home/arianeguay/dev/src/wiki-creator-by-studio/run_wiki.py): local orchestrator
- [scripts/entity_extraction.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_extraction.py): writes per-book `*_full.json`, `chapters.json`
- [scripts/relationship_extraction.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/relationship_extraction.py): co-occurrence graph, optional coref, CLI/live mode
- [scripts/chapter_summary.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/chapter_summary.py): chapter summaries used during preparation
- [scripts/wiki_preparation.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/wiki_preparation.py): batch generation
- [scripts/generate_wiki_pages.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_wiki_pages.py): standalone generation (shells out to `studio run wiki-page-item` per entity)
- [scripts/generate_book_synopsis.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_book_synopsis.py): book synopsis page from `events.json` (SP4/STU-482), writes `book_synopsis.json`; pure logic in `wiki_creator/synopsis.py`
- [scripts/generate_event_pages.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_event_pages.py): one `EVENT` page per high-salience event from `events.json` (SP3/STU-481), writes `event_pages.json`; pure logic in `wiki_creator/event_pages.py`
- [scripts/consolidate_editorial_stance.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/consolidate_editorial_stance.py): post-generation editorial-stance consolidation pass (STU-508), writes `editorial_stance_report.json`; pure logic in `wiki_creator/consolidation.py`
- [scripts/entity_status.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_status.py): per-tome character status pre-step (STU-488), writes `entity_status.json`; pure logic in `wiki_creator/entity_status.py`
- [scripts/wiki_export.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/wiki_export.py): Markdown -> wikitext
- [scripts/resolve_clusters.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/resolve_clusters.py): resolves NER clusters
- [scripts/merge_entities.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/merge_entities.py): merges cluster outputs into unified entity list
- [scripts/alias_resolution.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/alias_resolution.py): conservative PERSON alias merging, runs after merge-entities
- [scripts/entity_classification.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_classification.py): classifies entities, reads from alias-resolution output

## Script Executor Conventions

Most Studio scripts:
- read JSON from `stdin`
- read YAML input from `additional_context`
- write JSON to `stdout`

Typical payload shape:

```json
{
  "additional_context": "<yaml string>",
  "previous_outputs": {},
  "all_stage_outputs": {}
}
```

## wiki-resolution Stage Order (as of STU-539)

Inside `wiki-resolution`, order matters:
1. `merge-entities` + `relationship-extraction` run first
2. `alias-resolution` runs after — reads entities from merge-entities output (STU-276)
3. `alias-adjudication` runs after that — re-emits alias-resolution's payload with
   contextual merges applied; the only stage here that needs the network (STU-539)
4. `entity-classification` reads entities from alias-adjudication (falling back to
   alias-resolution), relationships from relationship-extraction

## Chapter Summary: temporal_context (as of STU-271)

- Each chapter summary carries `temporal_context: present | flashback`
- Detected by `_detect_temporal_context` using flashback cues from `cue_words/<lang>.json`
- Prompt is split into two blocks (present vs backstory) depending on this value
- `build_chapter_summary_context` propagates `temporal_context` to the context dict

## Gotchas

- spaCy models are extras, not a manual download (STU-522): `pip install -e
  ".[models]"` installs the models the books declare (`en_core_web_lg`,
  `fr_core_news_lg`) as pinned wheel URLs. Models are not PyPI deps, so nothing
  used to install them: 14 of 15 books declared `en_core_web_lg` and ran the
  `en_core_web_sm` fallback (with a `[WARN]`) on every machine that followed the
  README, and CI shelled out to `spacy download`. `[dev]` now carries
  `en_core_web_sm` — the test suite's model — so a fresh clone reproduces the
  documented `pytest -q` state with no tribal step. The wheels pin spaCy 3.8: a
  spaCy minor bump fails the install instead of resolving a mismatched model.
  The loader fallback is deliberately untouched — it exists so a local path or a
  community model can degrade (STU-453) — so skipping `[models]` still warns and
  runs rather than failing. `tests/test_spacy_model_extras.py` pins that every
  stock model a book declares is installed by an extra; a new book declaring an
  uninstalled model fails it.
- GLiNER NER backend (STU-521, STU-537): the book YAML `ner` block picks who
  finds the entities — `invented_names: true` (GLiNER) | absent/`false` (spaCy,
  pre-STU-521 behavior), plus `model`/`threshold`. The key names a property of
  the **book**, not a backend: a book YAML is configured by people who know the
  novel, not the pipeline, so it states what is true of the novel and the code
  derives the mechanism. Pure config in `wiki_creator/ner.py`; an unknown key
  **raises** rather than degrading, because a backend silently falling back is
  the STU-470 bug itself — `backend:` is one such key now, so a stale config
  fails instead of quietly reverting to spaCy. **spaCy does not go away**: it still tokenizes,
  tags and splits sentences (`_is_valid_span` needs POS, the extractor needs
  `doc.sents`), so `spacy_model` keeps its meaning — GLiNER replaces the *entity*
  step only. `wiki_creator/nlp/gliner_ner.py` does it as a spaCy component
  registered in the **`ner` pipe slot** and exposing `.labels`, so `log_pipeline`
  /`_audit_ner_labels`/`_warn_if_no_pos_tagger` introspect it with no GLiNER
  branch. It emits **taxonomy types as spaCy labels** (not the natural-language
  labels it asked for): `base.yaml` declares each type's own name among its
  `ner_labels`, so `ner_label_map` types them to themselves and all six
  downstream filters are untouched — the same trick wiki-ner-en relied on. That
  assumption is invisible and load-bearing (drop `PERSON` from PERSON's
  `ner_labels` and GLiNER silently extracts nothing); a test pins it. Labels live
  in `base.yaml#entity_types.<TYPE>.gliner_label` — the type vocabulary is a
  prompt now, so adding `ARTIFACT` is a YAML edit, not a retrain. Wording is
  load-bearing and swept, not guessed (`research/ner-eval/sweep_labels.py`,
  jointly on typing F1 — re-run it before changing a label). Chapters exceed
  GLiNER's window, so text is cut into sentence-aligned windows that are verbatim
  `doc.text` slices: STU-489 persists mention offsets into the chapter text, so a
  window that didn't map back exactly would corrupt them. `gliner` is an optional
  extra (it pulls torch, like `coref`), so a book declaring `invented_names`
  needs `pip install -e ".[gliner]"`. `throne-of-glass` was the only book flipped
  by STU-521 and the only wiki-ner-en consumer, which is why its 0.105 detection
  F1 on an unseen book stayed invisible; `models/wiki-ner-en` is retired
  (gitignored, so the flip *is* the retirement). STU-537 flipped the 6
  `inheritance` tomes, STU-535 `narnia`. EVENT ships with no accuracy claim
  (n=2 gold).
- Invented names break spaCy's typing (STU-537): spaCy's NER only recognises the
  proper nouns it memorised, and types the rest **ORG**. On Eragon that is not a
  tail case — `Garrow` (112 mentions, the uncle whose death launches the plot) is
  ORG in **111 of 113** mentions, `Cadoc` 42/42 ORG, `Katrina` 17/17 EVENT,
  `Varden` (a faction) 147/147 PERSON. So this is **not** a majority-vote bug and
  no vote fixes it: the model is consistently wrong, not noisy, and
  `extract_entities` freezing the type at the first mention's label is a
  non-issue. It is also invisible from inside the pipeline — the book YAML
  `entity_overrides` patch `Varden`/`Empire` at *classification*, long after
  relation discovery filtered `type == "PERSON"` and dropped Garrow. Measured
  against an LLM oracle roster (103 entities, `research/relation-eval/retype_roster.py`
  on the STU-467 spike branch): typing accuracy **50/103 spaCy → 84/103 GLiNER**,
  PERSON roster precision 61% → 92%, recall 80% → 94%. The fix is a config flip
  per book, not code — GLiNER types by prompt so an unseen name costs it nothing.
  Only `inheritance` was flipped by STU-537: no oracle existed for the other 14
  books, and a book of real-world names should not pay GLiNER's runtime.
  **`_retag_entity_type_from_context` is skipped
  under `invented_names`**: it exists to repair spaCy's ORG typing, and on a
  prompt-typed model it only misfires (it retyped Eragon's `Empire` ORG→PERSON;
  83/103 with it vs 84/103 without). It stays on for spaCy books, where its
  measured value is +1/103 — noise, but noise nobody has an oracle to remove
  safely. `Cadoc`/`Snowfire` (horses) are a real judgment call left as the oracle
  ruled them (PERSON): a named animal is a character, and dropping them would
  drop Saphira.
- `invented_names` is about the world, not the cast (STU-535): STU-537 read the
  property off the characters and concluded Narnia — Peter, Lucy, Edmund, Susan —
  was a real-names book with no spaCy problem. It is the opposite. The cast is
  English, the *world* is invented, and `en_core_web_lg` types **`Narnia` PERSON**
  on all 40 mentions it finds (a character page for the world, listed as a
  participant in an event), `Cair Paravel` ORG, and left the shipped run with
  **30 PERSON against 1 PLACE** — and that 1 was `Queens`. Same failure as Garrow,
  different half of the novel: a place name spaCy never memorised falls to PERSON
  as readily as a person's does to ORG. So the question the key asks is "are this
  novel's proper nouns invented", and one invented toponym is enough — a book can
  look like Peter and Lucy on the cover and still need the flip.
  Measured by `research/ner-eval/{run_arms,oracle_types}.py` (the STU-537 oracle
  generalised: an LLM types the union of the arms' candidates at the book's own
  `min_mentions_absolute`, 51 entities): typing accuracy **22/51 spaCy → 32/51
  GLiNER at 0.3**, PERSON precision 22/30 → 24/28, PLACE **0/1 → 3/5 precision and
  0/3 → 3/3 recall**. Narnia, Cair Paravel and the Stone Table type PLACE;
  `Turkish` (from *Turkish Delight*), `Son`, `Kings`, `Queens`, `House` — spaCy
  PERSON/ORG noise — are gone, and the Professor, Father Christmas and Maugrim
  arrive. **The rubric names no entity under test**: writing "Narnia is a PLACE"
  into the oracle prompt (the first draft did, and the numbers #164 shipped came
  from it) scores the arms against the author's verdict on the one entity in
  dispute. Neutral rubric, same verdict.
  **`threshold: 0.3`, not the 0.5 default**, and it was measured, not felt: 0.5
  scores 26/51 and finds no Fauns, Centaurs or Sons of Adam at all. Two caveats
  the method cannot lift: an entity **no** arm found is invisible to it (that is
  STU-470's gold corpus' job), and GLiNER's borderline spans are not
  deterministic — the counts move by ±1 entity between runs.
  The gap this does not close is GLiNER's weakness on a common noun used as a
  name: the antagonist is "the Witch" 80 times, and GLiNER detects `Witch` **20 of
  116** at 0.3 where spaCy gets 72 (`gliner_label: person name` asks for *names*).
  It costs no tier here — 72 was already below the book's own p90 principal cut, so
  the Witch is `secondary` under either arm — and it is not worth re-sweeping the
  label on Eragon's gold to chase, but it is the reason total mentions drop
  1327 → 1194.
- Non-standard spaCy models (STU-453): `lang.infer_language` returns `fr`/`en`
  only for stock-model name prefixes (`fr_core_news_`/`fr_dep_news_`/
  `en_core_web_`) and `None` for anything else — a local path
  (`models/wiki-ner-en/model-best`) or a community model (`fr_solipcysme_lg`).
  `lang.book_language` no longer defaults a non-inferable model to `en`: it
  **raises** unless the book YAML declares a top-level `language:` (throne-of-glass
  now sets `language: en`). It's validated at stage 1 (`parse_epub` calls
  `book_language`), so a misconfig fails at config, not run 16. `entity_extraction`
  resolves cue-words via `book_language` (not model-name inference), so English
  cue-words can't silently run on French text. `nlp/loader.spacy_model_candidates`
  takes an optional `language` to append generic per-language stock fallbacks
  (`fr_core_news_lg`/`sm`, `en_core_web_sm`) for non-standard requested models;
  `load_spacy_model`/`load_spacy_model_with_fallback` thread it. `nlp/loader.log_pipeline`
  logs components + NER labels at load and WARNs on a missing/empty NER
  (half-disconnected model, STU-439), complementing `entity_extraction`'s
  KEPT_LABELS audit.

- Pattern alias merging is gone (STU-538): `alias_pattern_templates` and
  `_detect_pattern_match` are deleted, not fixed. The templates named only `{b}`
  (`\byou may call me {b}\b`), so a hit was a property of **one** entity's context
  and merged it with whatever entity happened to be paired first — Solembum the
  werecat says "you may call me Solembum" *to* Eragon, and NER pools both entities'
  snippets, so Eragon absorbed him at `confidence: high`. The measurement is the
  whole argument: over the 6 books with cached extraction the templates fired **340
  times, with 0 true positives** (Solembum matched all 70 PERSONs of Eragon,
  including `Christopher Paolini` off the copyright page; Hoid swallowed Way of
  Kings). Anchoring `{a}` was tried first and is not enough — it cuts 340 to 1, and
  that 1 is still false (`"queen, and her own people called her queen lucy"`), because
  `{a}[^.]{0,80}` buys adjacency, not apposition: *"Eragon looked at the man known as
  Solembum"* still matches. **Every real hit in the library has `{b}` = the speaker
  naming themselves**, which is no alias at all; the shape only pays when the speaker
  is already known by another name (`"Wit will suffice—or if you must, you may call
  me Hoid"`), and that needs dialogue attribution, not a regex. The two paths that
  do find aliases (`_detect_title_alias`/`_detect_pure_title_in_context`, and
  reveal-words → LLM) are untouched. **This costs no recall**: the phrases nobody
  says in these books were never found — Throne of Glass's Celaena/Lillian is real
  and was never merged by pattern (its evidence is 2nd-person address, `"your name is
  Lillian Gordaina"`, and pronouns), and no signal even proposes that pair today
  (`role_symmetric` needs `_names_share_token`, `reveal_words` are absent, embeddings
  were falsified in STU-468). Finding it is contextual adjudication, a separate
  ticket. The golden diff is one always-zero counter; no entity moved.
  `detect_named_aliases` has no production caller — it lost its pattern strategy here
  but is dead API either way (deleted in STU-539).

- An honorific is not a role (STU-541): `_detect_title_alias` merged **Mr Beaver and
  Mrs Beaver into one Narnia entity**. The rule is written for `Captain Westfall` →
  `Chaol Westfall`, where the role designates one person, so the remainder
  (`westfall`) discriminates. `mr`/`mrs`/`miss` reach `role_words` through
  `person_cue_words` like any other title, and a married couple differs **only** by
  the honorific — the surname is the very part that cannot tell the spouses apart, so
  a matching remainder identifies nobody. A merge is refused when both entities bear
  titles that never overlap. **Titles are compared per entity, not per name**: once
  bare `Beaver` has absorbed `Mr Beaver`, it *is* Mr Beaver, and a per-name check
  would let it match `Mrs Beaver` and remarry the couple transitively. The remainder
  matches **whole tokens** (`_contains_token_run`), never a substring — `Beavers` is
  the couple, and `beaver` sitting inside it is an accident of spelling. What still
  merges and must keep merging: `Mr Tumnus` → `Tumnus` (one side titled, no conflict),
  `Captain Westfall` → `Chaol Westfall`.

- A species is not a role (STU-559): `pure_title` merged **the Shade into a sword
  and the Urgals into a mountain** on Eragon. Its premise — a bare role name
  designates a named character — is true only of a role exactly one character
  wears, and it read that off `role_words`, where `01_eragon.yaml` declares
  `rider`, `elf`, `urgal`, `shade` beside `king` and `queen`. So the book YAML
  now declares the property directly: `classification.roles_naming_one_character`
  lists the roles **this novel** uses, bare, as a name for one character — the
  "Config Is Read By People Who Know Books" rule, since a reader of Eragon knows
  without hesitation that `king` designates a man and `urgal` a species. An
  undeclared book merges nothing here (STU-539's asymmetry: a false merge invents
  a character and deletes a real one; a false negative leaves two pages that are
  each still correct), so only `throne-of-glass` declares it — `crown prince` and
  `captain`, its two measured true positives. `_detect_pure_title_in_context` no
  longer takes `role_words` **at all**: the two vocabularies being confusable is
  the defect, so the parameter is gone rather than filtered. That also drops
  STU-471's head-noun inference from this path — a declared phrase is matched
  whole (`_is_pure_title` keeps it, for `_pick_canonical_name`).
  **The config gate is not enough, and the second cause is separately measured.**
  `_is_apposition` took a comma for apposition: between `Zar'roc` and `Shade` in
  *"As for Zar'roc, the Shade might have it"* sit only `,` and `the`, so
  adjacency was declared apposition — the STU-536/STU-538 shape one layer down.
  A reader would plausibly declare `shade` (the Shade *is* Durza), which brings
  the sword merge straight back, so `_tokens_between_are_connective` now refuses
  **a comma plus a determiner**: apposition renames without re-determining
  (`Dorian Havilliard, Crown Prince of Adarlan`), while a comma followed by a
  fresh determined noun phrase opens a phrase that heads its own clause (`the
  Shade might have`, `the Urgals ceased`). **The comma is the gate, not the
  determiner** — `Brullo — the Master —` is the appositive dash form STU-281 was
  built for and keeps merging. Measured by replaying the deterministic chain on
  full rosters (ToG 60 ch, Eragon 67 ch, Narnia 20 ch — the 5-chapter caches
  answer a different question, per STU-539): **5 fires / 2 true → 2 fires / 2
  true**, both true positives kept. `alias-adjudication` is not a substitute: it
  runs *after* this stage (so a false merge is already baked into the roster it
  reads) and returned `merge: null` on every cached book.
  **`Queen` → `Lucy` is not the true positive STU-559 recorded**, which is why
  Narnia declares nothing: the novel writes `Queen Lucy` 5 times and `Queen
  Susan` 4, so bare `Queen` names neither sister and the merge steals Susan's
  mentions — STU-541's Mr/Mrs Beaver, reached through the other detector. The
  question `roles_naming_one_character` asks is "does this word, bare, name one
  character in **this** novel", not "is it a title": `king` is a title in ToG and
  still names nobody there (Adarlan's king and Brannon both wear it), which is
  why splitting `role_words` into titles-vs-species — the shape the ticket
  proposed — would have kept `King` → `Brannon`.

- Contextual alias adjudication (STU-539): the alias pair no rule proposes is
  decided by one `studio run alias-adjudication-item` per book, over the **whole
  PERSON roster** — the `section-filter` shape (STU-529), with the opposite bias:
  every failure path (missing CLI, timeout, unparseable verdict, hallucinated name)
  **merges nothing** and warns, because STU-538's asymmetry runs the other way from
  STU-529's. A false merge invents a character, deletes a real one, and
  `Registry.accumulate` carries it into every later tome; a false negative leaves two
  pages that are each still correct. `scripts/alias_adjudication.py` runs between
  `alias-resolution` and `entity-classification`, re-emitting the former's payload
  with merges applied (so `entity_classification` prefers `alias-adjudication` and
  falls back); pure logic in `wiki_creator/alias_adjudication.py`. It is a **separate
  stage on purpose** — `alias-resolution` stays deterministic and offline, so `make
  golden`/`make smoke` stay LLM-free by construction, not by mocking. The cache
  (`processing_output/<slug>/alias_adjudication.json`) is keyed on the roster rows
  themselves, so `WIKI_MAX_CHAPTERS` or any upstream extraction fix cannot replay a
  verdict made for a different roster.
  **The ticket's premise was measured false, and that is what made this cheap.**
  STU-539 was written believing Celaena/Lillian's evidence is only 2nd-person address
  and pronouns, so adjudication would need dialogue attribution (with `coref: true`
  queued as a possible source). It was written against a **5-chapter** cached
  extraction, where the cover identity has not yet been revealed. Re-extract the full
  book and two snippets name both outright: *"Lillian Gordaina was Celaena Sardothien,
  the world's most notorious assassin"* (C40) and *"'Lillian Gordaina doesn't exist,'
  Celaena said"* (C43). No attribution needed, no coref, no embeddings. **Re-measure a
  ticket's premise against a full artifact before designing for it** — a subset run
  (STU-497) answers a different question than the one asked.
  Two consequences for the design. (1) **No candidate generation.** The ticket feared
  `n²` pairs × one LLM call; the roster is 21–71 PERSON entities across the library
  (38 on Throne of Glass), so the whole thing goes in one call and the model does the
  `n²` internally — exactly as `section-filter` reasons over 60 sections at once. A
  co-mention pre-filter was measured and rejected: it cuts 703 pairs to 222 and ranks
  the target **28th**, behind every ordinary co-occurring pair, so it buys a threshold
  nobody could set. (2) **The snippets are filtered, not the pairs.**
  `select_snippets` keeps the ≤5 snippets that name *another roster character* — a
  sentence naming nobody else can only confirm the entity exists. That is what fits a
  38-entity roster into ~14k tokens while keeping the C40 reveal for **both** sides of
  the pair. **A merge must quote text we showed the model** (`parse_merge_verdict`
  drops any pair whose quote is not verbatim in its own snippets): these novels are in
  the model's training data, so without the check a merge sourced from its memory of
  the plot and one sourced from this run's text are indistinguishable afterwards. It
  is the anti-theatre rule applied to a claim rather than a tool call. Merges do not
  chain: A=B then B=C is skipped, because the classifier judged the roster it was
  shown and was never asked for a transitive claim.

- Adjudication is worth **0.83 precision**, and its errors are one shape (STU-543):
  measured over all 15 books, full text, rosters 17–174 (`research/alias-eval`, run
  it with `HF_HUB_OFFLINE=1`). **18 merges, 15 true, 3 false.** Four are judged
  without an oracle — the ground-truth corpora already write down both halves, every
  name book 1 calls a character (`canonical_aliases_book1`) and the confusions a page
  must never make (`identity_confusion_forbidden: ["alias: Daughter of Eve"]` under
  Lucy). **Roster size is not the failure axis STU-543 expected**: 174 entities works
  (Way of Kings), and the 3 false positives come from rosters of 49, 90 and 101.
  It earns its keep on the pair the lexical rules cannot reach: `Wit = Hoid` is found
  from the very sentence STU-538 quoted as *out* of a regex's reach, plus `Brom = Neal`
  / `Eragon = Evan` (the false names they travel under), `Saphira = Bjartskular`,
  `The Witch = White Witch`.
  **All 3 false positives are a character merged into a title held by more than one
  person** — `Nausicaä = Fury` (there are three: Alecto, Tisiphone, Megaera),
  `Glaedr = Ebrithil` ("master": Arya says it to Oromis, Saphira to Glaedr),
  `Eragon = Uluthrek` (Uluthrek is **Angela** — *"Farewell, Firesword. Farewell,
  Uluthrek"*, two people in sequence; the cited quote is *"why did Garzhvog call
  **you** Uluthrek?"*, Eragon asking *her*, which is Solembum with the arrow
  reversed). Each quote is verbatim in the snippets, so the STU-539 grounding check
  passed all three — **presence was all it ever measured** (STU-544). This is
  STU-541's rule from the other end: a title designating **one** person
  (`Captain of the Guard`, `Argetlam`, `Bjartskular`) is most of what the stage buys;
  a title shared by **many** has no referent to merge into.
  Recall is the cost of STU-538's anti-merge bias: 6 pairs the gold names go unmerged,
  all `Eragon`/`Shadeslayer`/`Argetlam` across tomes — `Argetlam` merges in 02_eldest
  and not in 03_brisingr, because the snippets differ per tome.
  **The measurement's first finding was that there was nothing to measure**: 5 of the
  first 8 books produced no verdict at all. STU-561 (argv `E2BIG`, fixed in Studio)
  and STU-564 (truncated-echo recovery) each fail safe, so the stage warned, merged
  nothing, and every pipeline stayed green — the feature did not exist on the large
  books and no reading of the prompt would have said so.
  One loose thread, measured and reversed (STU-573): with STU-564 fixed, Throne of
  Glass yields **0 adjudication merges**, which looks like the deterministic upstream
  now folds `Celaena`/`Lillian Gordaina` on its own — it does not. `entity-clustering`
  is **seeded** from the series registry (`Registry.load_seed_table`), and a re-run of
  tome 1 self-seeds from its own prior `registry.json`, so the pair arrives at
  clustering already joined. Rebuild the cluster with `seed=None` and it splits back
  into `Celaena/Sardothien` + `Lillian Gordaina/Lady Lillian/Lillian`:
  `Celaena Sardothien` and `Lillian Gordaina` share no token, so jaro-winkler keeps
  them apart, and `alias-resolution`'s lexical rules cannot bridge them either
  (`role_symmetric` needs `_names_share_token`; `reveal_words` — `true name`, `real
  name`, `alias` — are absent from *"Lillian Gordaina **was** Celaena Sardothien"*, so
  `_detect_reveal_signal` never fires). The identity in the seed traces to a **prior
  adjudication verdict** (registry decision `strategy: context_adjudication`, the C40
  quote), cached by `write-registry` and replayed by seeding. So STU-539's premise —
  "no deterministic signal proposes that pair" — is **still true**; the `0 merges` is
  seed-replay of the LLM verdict adjudication earned once, not a rule discovering it.
  Adjudication is not redundant. The fold does not survive a cold (registry-less) run.

- A quote that is present is not a quote that proves (STU-544): the STU-539 grounding
  check verifies the cited quote is verbatim in the snippets — *did this come from the
  text or your memory of the plot* — not that the text *supports* the merge. STU-543's
  3 false positives are one shape it cannot see: a character merged into a title held
  by more than one person. The fix is in the **prompt**, not a code gate — proof that a
  quote binds two names to one person is semantic and undecidable deterministically.
  `alias-adjudication.agent.yaml`'s `THE TEST` now reads the quote for the relationship
  (`"A was B"` merges; `"A, a B"` / `"A as a B"` / `"call you B"` do not), and two
  `NEVER merge` rules name the failure modes: a title/class several characters hold
  (`Ebrithil`="master", `Fury` is one of three, `Daughter of Eve`), and a name used to
  **address or ask about a second person** (`"why did they call you X"` — Solembum with
  the arrow reversed). Live on `claude-haiku-4-5`, the new prompt rejects all three
  traps and keeps a genuine cover identity, stable across runs.
  **The deterministic filter STU-544 floated second — refuse a quote naming a third
  roster character — was measured and dropped**: over the 18 verdicts it catches 0 of
  the 3 false positives (their quotes name no roster third) and kills 6 true positives
  whose quotes legitimately name a bystander (`Eragon = Argetlam` names Saphira,
  `The Witch = White Witch` names Aslan). Option 1 only.
  Scoreability: `Eragon = Uluthrek` is now `false_positive` in `score.py` via a
  `identity_confusion_forbidden` entry under Eragon (Uluthrek is Angela's, a
  later-book name hosted on a book-1 character). `Ebrithil`/`Fury` stay human-judged —
  the gold is book-1-scoped and neither has a book-1 host, so scoring them would mean
  inventing hand-written truth. The verdict cache is keyed on the roster, not the
  prompt, so re-measuring the fix requires re-extraction (which regenerates it), not
  just a re-run.

- Entity status (STU-488): the `status` infobox slot was declared `MIN` with
  `fallback: unknown` in STU-504 and never populated. It is filled by one
  `studio run entity-status-item` per book over the PERSON roster — the
  STU-529/STU-539 shape — as a **pre-step to wiki-preparation**, not a
  wiki-resolution stage: it changes no identity (unlike `alias-adjudication`,
  which entity-classification reads), and resolution is the chain `make golden`
  runs, so it stays LLM-free by construction. Enum is the fandom-wiki convention
  (`alive | deceased | missing | unknown | undead`), labels in
  `base.yaml#chrome.status_*`. **The marker vocabulary retrieves, it does not
  decide** (`cue_words/<lang>.json#status_markers`): that is the whole
  difference from STU-538, which measured 340 fires and 0 true positives when a
  pattern *was* the verdict. "Eragon watched Brom die" carries a death marker in
  both characters' contexts and kills one; the model reads the subject, the
  regex cannot. A marker missing from the vocabulary means a death is never
  surfaced, which means `unknown` — the forgiving direction. Snippet selection
  is two-source because the enum asks two questions: marker-bearing snippets
  prove `deceased`/`missing`/`undead`, the **latest** snippets prove `alive` (a
  novel never says "Eragon is alive"). Both are latest-first — status is the
  state at the *end* of the tome. **A verdict must quote text we showed the
  model** (`parse_status_verdict` rejects any quote not verbatim in that
  entity's *own* snippets): these novels are in the model's training data, so a
  verdict from its memory of the plot and one from this run's text are
  otherwise indistinguishable. **Every failure path renders `unknown`**, the
  slot's own declared fallback: a false `deceased` kills a living character on
  a page nobody will reread and `Registry.accumulate` would carry it forward; a
  false `unknown` says "we don't know". The cache
  (`processing_output/<slug>/entity_status.json`) is keyed on the roster rows,
  so `WIKI_MAX_CHAPTERS` cannot replay a verdict made for a different roster —
  STU-539's premise was measured false precisely because it was measured on a
  5-chapter extraction.
  **The series registry does not carry status**: the wiki is per-tome
  (`output/<slug>/`) while the registry is per-series, so "dead in tome 2 without
  erasing tome 1" is true by construction — tome 1 is never regenerated. The
  ticket's "series page" does not exist (STU-553 decides whether it should, and
  it conflicts with STU-232). `affiliation` is NOT a third slot of this shape:
  `FACTION` is an entity type since STU-505, so a faction change is a dated edge,
  not a scalar (STU-551).
  **The `death` slot (rendering the chapter the verdict quotes) shipped
  alongside `status` and was removed**: measured on Eragon's 4 verified
  verdicts, 3 of 4 derived chapters were wrong — Brom dies around chapter 37 but
  his death slot read "Chapter 61" (where a character later *says* he was
  killed), and Morzan/Marian both died before the book begins and have no death
  chapter at all. The place where the text states a fact is not the place where
  the fact happens, so deriving a chapter from the quoting snippet does not
  work. The in-universe circumstance ("Tué par Durza à Farthen Dûr") replaced it in
  STU-552, and **not as prose**: the ticket proposed the STU-481 `## Déroulement`
  shape, but free prose in an infobox slot is the one non-grounded field, which
  is what `_extracted_fact_value` exists to prevent. It is two optional fields —
  `agent`, `place` — on the verdict this same call already returns, so it costs
  no stage and no LLM call, and there is **no `cause` enum**: an agent means
  someone killed them, a place means they died there, and a death by illness
  renders "Mort à X", which stays true whatever the cause. Each field clears
  three gates: `status == "deceased"`, the name is on the **type-scoped** roster
  (PERSON for `agent`, PLACE for `place`, alias → canonical), and it is
  **verbatim in that verdict's own quote**. The quote gate is the load-bearing
  one and is deliberately stricter than "somewhere in the entity's snippets":
  the slot asserts a link between two facts, and "they rode to Farthen Dûr" one
  sentence from "Durza's blade took Brom" would render where he rode, not where
  he died. A field failing a gate is dropped and the verdict survives — a wrong
  `agent` costs the circumstance, never the `status`. Names render **plain, never
  wikilinked** (`event_infobox_fields`'s precedent): a collated entity has no
  page, so a link would be red, and no edge is drawn, so the STU-501 rule never
  engages. The cache gained a `CACHE_VERSION` because the rows did **not** change
  — same roster, new question — so roster-keying alone would have replayed a
  pre-STU-552 verdict forever and silently. The infobox leaked the death exactly
  as `Statut : Décédé` already did, until STU-567 gated it (below).

- The infobox is spoiler-gated per-row (STU-567): `content_units` still skips the
  infobox by construction (it is not a section), so `wiki_export.render_page`
  gates it directly — `gate_infobox_spoilers` wraps the `status` (unless
  `unknown`) and `death` values in an inline `mw-collapsible` span when
  `generation.spoiler.collapse_after_chapter` is set (byte-identical output
  otherwise). This is the Fandom convention: the value collapses behind a reveal
  toggle, the `Statut`/`Décès` label stays. **No reveal chapter is computed** —
  STU-488 measured deriving one from the quoting snippet 3/4 wrong (the text
  *states* a death nowhere near where it *happens*), and a whole-tome status
  verdict has no sound intra-tome chapter, so the rows are treated as revealed at
  end-of-tome and gated unconditionally. A reader past the death point pays one
  click; the alternative leaks it. Only PERSON declares `status`/`death` infobox
  tokens, so keying on them is inherently scoped. `unknown` is not a spoiler and
  stays open. Toggle chrome is chapter-less: `chrome.reveal_spoiler`.

- Affiliation is a scalar, not a dated edge (STU-551): the `affiliation` slot is
  filled by one `studio run entity-affiliation-item` per book over the PERSON
  roster — the STU-488 shape, a pre-step to wiki-preparation so resolution stays
  LLM-free. The ticket asked for a **dated edge** and three findings refused it.
  (1) Its own acceptance test — tome 3's faction on tome 3's page, tome 1's on
  tome 1's — is true **by construction** under a per-tome wiki, exactly as for
  `status`. (2) The intra-tome date is what STU-488 measured unbuildable: its
  `death` slot derived the chapter from the snippet its verdict quoted and got 3
  of 4 wrong, because the place where the text states a fact is not the place
  where the fact happens; a dated edge has no other date source. (3) There is no
  edge to date — `relationship_extraction.py` filters the co-occurrence graph to
  `type == "PERSON"` in hard code, so no PERSON-ORG edge exists in any artifact.
  Snippet selection is **single-source** where `status` is two-source: nothing
  proves the *absence* of an affiliation, so there is no `alive`-analogue proved
  by acting late. Marker-bearing snippets, latest-first — the latest-first is what
  makes the scalar mean "end of tome" and absorbs an intra-tome switch without
  dating it. **A third rejection rule exists here that `status` does not need**:
  `status` returns an enum member, so verifying the quote verifies the verdict;
  `affiliation` returns a **name**, so the model can quote a real sentence and
  infer the wrong faction from it. The rendered value must appear in the quote,
  verbatim, and **as whole tokens** — a raw substring test accepted `Order` off
  "he ordered the villagers" (STU-541's rule, STU-541's reason).
  **The slot was never "inert", and that nearly shipped a lie.** `base.yaml`
  tells the writer to fill `affiliation` (the infobox brief names it; the
  few-shot demonstrates one), and `_bind_batch_fields` only *overwrites* an
  extracted-fact token when the pipeline has a value — so an undecided character
  rendered the **writer's** inference, which with this stage's ~0 recall is
  almost every character. `status` is immune only by accident of being
  `MIN`/`fallback: unknown`, so `status_label` always returns a string. A
  pipeline-owned fact with no value is now **cleared**
  (`_PIPELINE_OWNED_FACTS`); `species`/`location`/`leaders` are declared
  extracted-fact with nothing computing them, and `titles` has the same hole —
  STU-572. Shared roster plumbing lives in
  `wiki_creator/roster.py` (`normalize`, `has_marker`, `latest_first`,
  `render_roster`, `is_quoted`, `load_cache`, `save_cache`), extracted from
  `entity_status` rather than copied — `normalize`'s typographic folding is the
  `99a6a71` fix and must exist once.
  **A marker names the relation, never the group.** The first vocabulary included
  `side`, `order`, `band`, `army`, `ranks`, `guild`: `side` alone fired on 28 of
  the ~70 selected snippets ("his side burned sharply", "at her side"), crowding
  real statements out of the 5-snippet budget. Group nouns are what the *value*
  contains; only the relation (joining, serving, swearing, betraying) proves
  membership. Prose-ambiguous single verbs go too — `join` also matches "where its
  neck and shoulders joined", which was Eragon's only marker snippet.
  **Measured: 0 false positives over 2 runs on 47 characters, and ~0 recall —
  because of the book.** `01_eragon` is near worst-case: `join*` pairs with
  `Varden` in five sentences of 907k chars and **none states an affiliation** (two
  are questions; one is Eragon considering it and refusing). **Eragon does not
  join the Varden in book 1** — that is Eldest. The design predicted he did, from
  memory of the series rather than book 1's text: the exact error the agent prompt
  forbids by name, made by the prompt's author in its own measurement plan. So the
  slot rendering nothing there is correct, and the feature **has not been shown
  useful** — a later tome (`02_eldest`, `05_murtagh`) is the measurement that
  would decide, and it is not done. Narnia's species red-flag check is also
  outstanding. Recall is unstable run to run (Brom's one true hit moved on
  identical evidence); precision is not — STU-488 recorded the same asymmetry.

- Species is an attribute, not the collective entity (STU-574): the `species`
  PERSON infobox slot (declared, `genre_gated: true`, inert since STU-504) is
  filled by one `studio run entity-species-item` per book over the PERSON roster
  — the STU-551 shape: single-source marker snippets, and a verdict survives only
  when its species is verbatim in a quote from that entity's own snippets
  (`quote_names_value`, lifted to `roster.py` and shared with `affiliation`; it is
  the companion of `is_quoted` — one checks the quote is real, the other that the
  quote names the value). STU-571 assumed the value was already collected into the
  FACTION bucket (`Elves`, `Dwarves`) and a typing fix would feed it: `Elves` the
  collective noun is an *entity* with its own page; Eragon's `human` is an
  *attribute* of the Eragon PERSON, so extracting the collective says nothing about
  the character. **Genre-gated on `ner.invented_names`**, checked before any
  registry read — a real-world-cast book has no species to attribute, skips the
  stage, and the OPT slot clears (STU-572). Pure logic in
  `wiki_creator/entity_species.py`; pre-step to wiki-preparation, so resolution
  stays LLM-free.
  **Measured precision 7/7, 0 false positives, over the 3 books with a cached
  registry** (Eragon 6/6: dragon/dwarf/Ra'zac; Narnia 1/1: Tumnus=Faun; ToG 0,
  human cast). Precision is the invariant — a wrong species reads as fact on a page
  nobody rereads — and it is the STU-543/551 anti-false bias, 0-FP.
  **Recall is structurally low, two buckets.** (1) The unmarked human default: a
  novel never says "Eragon was a human", so the slot fills for marked species and
  stays empty on humans — correct for a fantasy infobox. (2) A species absent from
  the language-wide `species_markers` (`cue_words/<lang>.json`): Narnia misses
  `Aslan`=lion, `Beavers`=beaver, `Maugrim`=wolf — those words are not in the
  retrieval net. That is STU-535/537's lesson from the other side: `invented_names`
  is a property of the *world*, but the species *vocabulary* is a property of the
  *book*. A language list covers fantasy staples (elf/dwarf/dragon/faun/giant/
  centaur), not a given novel's named animals; chasing lion/beaver/wolf into
  `en.json` would put book-specific vocab in a language list, which STU-559 forbids.
  The recall lever is per-book species markers in the book YAML (STU-559 shape), a
  fast-follow — not the language net. Shipped precision-first, like `affiliation`
  and `status` before it. Measurement runs the standalone stage on cached
  registries (1 LLM call/book, no re-extraction); no species gold exists, so
  precision is human-judged against canon like STU-543.

- Name-collision policy (STU-506): `registry.py::_merge_duplicate_canonicals`
  used to fold two entities on `canonical_name.casefold()` alone — a PERSON and
  a PLACE homonym became one false entity. Policy is now declared in the book
  YAML `naming` block (pure logic in `wiki_creator/naming.py`):
  `collision_policy: disambiguate` (default) | `merge` (legacy fold) | `fail`
  (raise on cross-type homonym), `merge_requires_same_type` (default true — puts
  `entity_type` in the merge key so homonyms coexist), `disambiguator.template`
  (`"{name} ({type_label})"`) and `alias_arbitration.order` (`[canonical_owner,
  mention_count, first_seen]`). Invariant 1 went from "true by construction" to
  "true by policy": `Registry.validate()` keys alias ownership on
  `(casefold, entity_type)`, so two records with the same `canonical_name` and
  different types validate; `_resolve_alias_collisions` buckets per type and
  arbitrates via the configured order. `from_artifacts(..., policy=)` defaults to
  the safe posture (goldens unchanged — the fixture has no cross-type homonym);
  `write_registry.py` passes `naming_policy(book_cfg)`. Title disambiguation runs
  once in `assemble_wiki_pages.py` (the `wiki-page` stage the `unique-page-title`
  validator checks and export renders): different-type pages that would share a
  `page_filename` get the type label appended, so the flat MediaWiki namespace
  stays collision-free. Scope is `from_artifacts` only — cross-tome type
  arbitration in `Registry.accumulate` is governed by the STU-512 canon policy,
  not this one. The 11 Throne-of-Glass `entity_overrides` are `force_type`
  (classification), not collision rustines, so removing them needs a real spaCy
  run to verify — left in place.

- Markup corpus (STU-525): `tests/fixtures/markup/` is the parser's regression
  record — one `<publisher>-<shape>.html` per real convention (tags, classes,
  charrefs, whitespace byte-exact from the publisher's file; prose swapped for
  filler), paired with a `.txt` holding the text the parser must produce.
  `tests/test_markup_corpus.py` parametrizes over it. Three things are
  load-bearing. (1) **The `.txt` is hand-written, never generated** — deriving it
  from `parse_epub` asserts only that the parser agrees with itself, the
  circularity STU-524 removed from the e2e fixture. It caught a wrong prediction
  of mine on the first pass: `eragon-epigraph-em-split` really does render
  `elit .`, because the source really is `</em>&#13;\n .` — the publisher's
  space, not our bug. (2) **Shapes are keyed on tag names, never classes**
  (`tests/fixtures/markup/harvest.py`, re-runs the survey against a local
  library): the parser only sees tags, and Brisingr does its small-caps with a
  bare `<small>` while Eragon uses `<span class="small1">` — same shape.
  Classes stay in the snippet as provenance. (3) **The harvest writes nothing** —
  a new shape is a prompt for a human (swap the prose, hand-write the `.txt`),
  not a patch. Reverting `_flatten_inline_markup` reds 9 of the 15 snippets.
  The corpus found two bugs on its first run, both invisible to markup we wrote
  ourselves: STU-531 (`\r`) and STU-532 (block-level dropcap), both since fixed.
  A shape recorded but not fixed gets a `strict=True` xfail naming its issue —
  never an expected text edited down to what the parser happens to emit.
- Block dropcaps (STU-532): a dropcap can be its own **block**, not its own span
  — `<p>I</p><p>n a hole…</p>`, The Hobbit's opening sentence. Inline flattening
  cannot reach it, so `_mark_paragraph_breaks` used to put a paragraph break
  inside the word. `_merge_block_dropcaps` rejoins it, between
  `_flatten_inline_markup` (so `<p><span>I</span></p>` has already collapsed) and
  `_mark_paragraph_breaks` (whose mark would outlive the block it decomposes).
  This is **not** the STU-519 regex coming back: that one guessed from flat text,
  where `P`+`edro` and `A`+`silvery` are indistinguishable. This reads markup
  while the tree still stands — a block holding one capital, followed by one
  resuming lowercase. A lone capital is a legal word; a lone capital as an entire
  paragraph, with the next paragraph resuming mid-sentence, is typesetting. The
  gate that matters is the lowercase one: drop it and `<p>A</p><p>Silvery
  cloud…</p>` welds, which is exactly the 7361-token corruption STU-519 deleted.
  Verified by re-parsing all 16 EPUBs: it fires **once**, on the Hobbit sentence,
  nowhere else. It also removes a paragraph break, so it shifts every STU-489
  mention offset downstream of it in that chapter — no book in the library but
  The Hobbit is affected, and the fixture novella has no such shape (goldens
  unchanged).
- Carriage returns (STU-531): `clean_chapter_text` normalizes `\r` like `\n`.
  It never comes from line endings — not one EPUB in the library holds a `\r`
  byte — but from **`&#13;` charrefs**, which `html.parser` resolves at parse
  time. 6 of 16 books ship them (le-jeu-de-lange 11249, Murtagh 7506, Eragon
  7057, Brisingr 6055, hollow-star 4655, Narnia 970). Most sit between blocks and
  die as whitespace-only strings under `get_text(strip=True)`; the ones inside a
  block reached the output, leaving a raw `\r` in **1192 blocks** of chapter text
  and titles like `PALANCAR\r VALLEY`. So "no HTML entities reach here" was true
  and still not enough: charrefs resolve *to characters*, and the cleaner has to
  handle the character.
- Dropcaps (STU-519): word-splitting markup is rejoined in `parse_epub` by
  `_flatten_inline_markup` — inline tags (`span`, `em`, `sup`, `a`, …) are
  unwrapped and `soup.smooth()` merges the adjacent strings, *before*
  `get_text(separator="\n")` can turn a tag edge into a word boundary. That is the
  only correct place: once the text is flat, a dropcap fragment (`P`+`edro`) and a
  real one-letter word (`A`+`silvery`) are indistinguishable — no regex and no
  lexical-frequency check separates them (`wordfreq` scores `ove` and `ather` as
  valid English, so it misses `M`+`ove` / `F`+`ather`, the library's only real
  dropcaps). The old `clean_chapter_text` step 5b regex merged *any* isolated
  capital + lowercase word and was pure corruption: 7361 distinct bogus tokens
  across the 16 EPUBs (`Asilvery` — NER-tagged PLACE and eligible for a wiki page —
  plus `Smajuscule`, `Aà`). STU-519 recorded "only two markup shapes in the
  library actually split a word, both span-based" (Eragon's small-caps chapter
  openers `D<span>ISCOVERY</span>` and Hollow Star's `f_dropcapital`) — the
  STU-525 harvest falsified that on both counts. Twelve conventions split words
  across 13 of 16 books, `<small>`/`<em>`/`<sup>`/`<b>`/`<i>` as well as `<span>`
  (see `tests/fixtures/markup/`), and the shape STU-519 called absent from the
  library — the block-level dropcap — is the first sentence of The Hobbit, now
  handled by `_merge_block_dropcaps` (STU-532). The survey found what it went
  looking for; the number was never a census.
  `first_person_artifact_tails` (`entity_extraction.py`, kills `Iwould`/`Ihave`) is
  NOT dead — it now catches only genuine source typos (throne-of-glass has one real
  `Isay`), which is what it was reduced to, not what it was written for. Note
  `ebooklib` pretty-prints XHTML on `write_epub`, inserting whitespace between
  sibling spans — an epub round-trip in a test cannot reproduce real dropcap markup,
  so test `_flatten_inline_markup` on the markup string directly.
- `clean_chapter_text` is audited, not accumulated (STU-519): every step was
  disabled in turn and the whole library re-parsed to see what it actually did.
  Five of ten did nothing. Three were deleted because they are **unreachable** given
  the function's only production caller (`get_text(separator="\n", strip=True)` over
  BS4-parsed HTML): `html.unescape` (html.parser resolves charrefs at parse time —
  and on already-unescaped text it would eat a literal `&nbsp;` an author wrote),
  and the two paragraph steps (that `get_text` returns `"\n".join` of non-empty
  stripped strings, so `\n\n` could not occur — chapter text had no paragraph
  structure at all; STU-523 restored it, see below). Two more are inert on this corpus (NFC, ligatures: 0/1102) but
  kept — they are not structurally unreachable, another publisher plausibly ships
  NFD or `ﬁ`. Two were deleted as **actively harmful** band-aids over the markup
  split `_flatten_inline_markup` now fixes at the root: `Àla`→`À la` only ever undid
  step 5b's own damage and broke the real toponym `Plaza dels Àngels` into
  `À ngels`; the `I 'll`→`I'll` repair had one genuine target (an inline split, now
  fixed upstream) against two corruptions of Eldest dialect (`I 'ope` → `I'ope`).
  When a step here looks dead, measure before deleting — and when it looks alive,
  check it is not just undoing a neighbour.
- Paragraph structure (STU-523): `chapters.json` content carries block boundaries
  as `\n\n`. `get_text(separator="\n", strip=True)` drops whitespace-only strings,
  so a break cannot ride on whitespace: `_mark_paragraph_breaks` inserts a NUL
  (`_PARAGRAPH_MARK`) after every `_BLOCK_TAGS` element and `clean_chapter_text`
  turns each run of marks into one `\n\n`. Three constraints are load-bearing and
  each has a test. (1) The mark goes *after* the tag, not inside it, so
  `_extract_chapter_title`'s `heading.get_text()` stays clean. (2) It runs *after*
  `_flatten_inline_markup` — both mutate the same tree, and marking a tag about to
  be unwrapped strands its mark mid-word (STU-519). (3) Marks come from markup
  only, never from source whitespace, so the blank lines pretty-printed XHTML
  sprinkles inside a `<p>` are not paragraph breaks. `<br>` is deliberately not a
  block tag: it is a soft line break (verse, addresses) and stays a space.
  Every `\n\n` is +1 char over the space it replaced, so **it shifts every STU-489
  mention offset** — the seed (`gen_seed.py`, which rebuilds the chapter text
  itself and must mirror parse_epub's joining) and the goldens were regenerated.
  Offsets survived because every consumer is self-consistent: extraction computes
  them from the same text, `Mention.window` and `gliner_ner.windows` slice
  `doc.text` verbatim. `research/ner-eval/chunking.py` still splits on `\s+` and
  is paragraph-blind — it is eval scaffolding for the retired `wiki-ner-en`, so it
  was left alone; paragraph-aware chunking and dialogue attribution are the
  follow-ups this unblocks.
- Section filtering (STU-529): what counts as front/back matter is **classified**,
  not matched. The two `chapters.py` frozensets are gone; `is_frontmatter_chapter`
  is a dict lookup on a `frontmatter: true` tag, and the `section-filter` stage
  (`scripts/section_filter.py`, between `epub-parse` and `entity-extraction`) sets
  it from one `studio run section-filter-item` per book. They were tuned on the 16
  library EPUBs and failed silently elsewhere — the wiki-ner-en shape (STU-521) one
  layer down; they also leaked 11 sections titled `Copyright`/`Dedication`/`Contents`
  because those words were only in the *ID* set while real EPUBs use opaque ids
  (`cop`, `ded`, `id_4`). Four things are load-bearing. (1) **The stage is not inside
  `parse_epub`** — extraction stays deterministic/offline, and `make golden`/`make
  smoke` are LLM-free *by construction*, not by mocking; move the call into
  `parse_epub` and both need an API key. (2) **The `opening` snippet** (200 chars,
  `section_filter.OPENING_CHARS`) — with only `id | title | chars` the model cannot
  tell Murtagh's in-world `Argument` ("Behold, the land of Alagaësia") from a
  marketing synopsis and drops both; it decides on one axis, inside vs outside the
  fiction (the STU-507 `editorial_stance` lens). Way of Kings' `index_split_001.html`
  is ACKNOWLEDGMENTS, not a chapter — judging by title and length alone gets it
  backwards. (3) **Bias toward keep**: every failure path (missing CLI, timeout,
  unparseable verdict, hallucinated id) keeps every section and warns. A false keep
  is one visible junk entity; a false drop deletes a real chapter silently, in a book
  we will never read. (4) **The cache is keyed on the rows themselves**
  (`processing_output/<slug>/section_filter.json`), so `WIKI_MAX_CHAPTERS` can't
  replay a verdict made for a different section list. It is tags, never removal —
  `chapters.json` stays complete and the STU-489 offsets don't move.
- `entity_extraction.py` keys chapter mentions by chapter ID, not chapter title.
- `merge_entities.py` passes through only the current `resolve-clusters` output shape (runs before `alias-resolution` per the STU-276 pipeline order; STU-447 dropped the older `split-clusters` + `entity-resolution-*` compat branch and a vestigial `alias-resolution` priority check that predated STU-276 and never fired in production).
- `split_clusters.py`, `relationship_extraction.py`, and `verify_entity_types.py` are intentionally tolerant of missing `file_path` in unit-test mode.
- `generate_wiki_pages.py` must run after `wiki-preparation`; it consumes `wiki_inputs/<slug>/batch_*.json`.
- `generate_book_synopsis.py` (SP4) consumes `events.json` (SP0) and writes `processing_output/<slug>/book_synopsis.json`; `assemble_wiki_pages.py` appends that page to the export flow and `wiki_export.py` renders it at the wiki root (`Synopsis.wiki`, no infobox/categories, `entity_type: SYNOPSIS`). If `events.json` is absent, the stage warns and skips — it never fails the run.
- `generate_event_pages.py` (SP3/STU-481, STU-502) consumes `events.json` (SP0) and writes `processing_output/<slug>/event_pages.json` — one `EVENT` page per event with `salience >= threshold` (default `0.7`, raised from `0.6` in STU-502 to drop the low-value long tail) that has ≥1 participant. Title and infobox `{participants, lieu, chapitre, issue}` are built deterministically from the event; the writer LLM only authors the `## Déroulement` prose (grounded, spoiler-safe via forbidden_names). To stop the writer paraphrasing the title (STU-502), `build_event_prompt` injects the `DEFAULT_CONTEXT_WINDOW` (=3) neighbouring events before/after in narrative order as **read-only** NARRATIVE CONTEXT — background to situate the event (what leads up to it / what it brings about), never facts to attribute to it; `neighbor_context` windows the full events list, so context spans below-threshold neighbours too. `assemble_wiki_pages.py` appends the pages; `wiki_export.py` renders each under `output/wiki/events/` with `Infobox_event` + `[[Category:Événements]]`. Thresholds are configurable via book YAML `generation.event_pages` (`salience_threshold`, `max_pages`, `max_tokens`). Absent/empty `events.json` warns and skips — never fails the run. Titles are the full event description (grounded, unique) — LLM-named events are a possible fast-follow.
- Notability tiers (STU-509): the book YAML `notability` block is the single source
  for importance thresholds — it replaced `thresholds: auto`, whose explicit form
  (`characters`/`locations`/`organizations`, keyed by domain nouns) was deleted. That
  form was dead (every book said `auto`; the explicit shape only ever existed as a YAML
  comment) and was the root of two defects: it had no key for `EVENT`, so switching to
  explicit thresholds dropped every event to `figurant`, and its documented `min_chapters`
  was never parsed. `notability` is keyed by real entity types, so `per_type.EVENT` is
  reachable by construction. `compute_thresholds` resolves `{type: {tier: {min_mentions,
  min_chapters}}}`; a tier needs BOTH gates, and failing one falls through to the tier
  below (`min_chapters` absent → 0 → never binds). `strategy: percentile` (default) cuts
  thresholds from the book's own distribution, so tiers are NOT comparable across tomes —
  a series wanting stable tiers pins `strategy: absolute`. Below
  `min_entities_for_percentile` (default 4) entities of a type, percentiles are
  meaningless and `fallback_absolute` is used instead. Defaults reproduce the old
  percentile behavior exactly; the only golden change was the stat rename
  `thresholds_used: auto` → `strategy_used: percentile`.
- Absolute notability on the multi-tome series (STU-513): `inheritance` and
  `hollow_star_saga` pin `strategy: absolute`; every other book keeps the
  percentile default. The cuts are the 0.90/0.60/0.10 percentiles of the
  **series-pooled** mention distribution (inheritance PERSON `41/9/3` from 527
  entities over 6 tomes; hollow_star_saga `40/10/3` from 280 over 4), so a
  mention count means the same tier in every tome. `PLACE`/`ORG` get `per_type`
  cuts because their distributions differ from PERSON's (inheritance PLACE
  `48/16/3`, ORG `63/6/3`); `EVENT`/`OTHER` take `fallback_absolute` — 7 pooled
  EVENT entities across 6 tomes is too few to cut a threshold from, and on this
  series every one of them is a misclassification (`Katrina`, a PERSON).
  The metric that justifies the change is **inversions** — the same character
  ranked LOWER in the tome where it is mentioned MORE. Percentile produced 11
  in inheritance (`Elva` 52 mentions → `secondary` vs 12 → `principal`) and 4 in
  hollow_star_saga; absolute produces 0 by construction. Tier *changes* are not
  the defect and must not be "fixed": Brom goes 128 mentions → 6 between tomes
  because he dies, and dropping to `figurant` is correct. Absolute cannot reach
  zero tier changes at comparable mention counts either (19 → 7 in inheritance)
  — a step function always has a boundary, and two close counts can straddle it.
  `04.5_tales-of-alagaesia` is an anthology (top character peaks at 29 mentions
  where the novels reach 310) and takes the series cuts like every other tome,
  which leaves it `0/5/41` on PERSON — no principal page. Exempting it to
  `percentile` was tried and reverted: its own p90 sits at 8, so it promoted
  entities the novels rank lower and **re-introduced 9 inversions**, all against
  it (`Angela` 12 mentions → `principal` there vs 40 → `secondary` in
  `04_inheritance`). Nothing is lost by not exempting it — those characters hold
  their principal pages from the tomes where they carry the story, and STU-488
  (one accumulated entity across tomes) needs the tomes to agree on a tier.
- `classify_relationships.py` (pre-step to `wiki-preparation`) folds the co-occurrence graph onto canonical entities via `registry.alias_table()` before classifying (STU-435). The graph is built at mention level (pre alias-resolution), so surface forms of one entity (`Chaol Westfall` / `Captain Westfall`) are collapsed, counts summed, `chapters`/`sample_contexts` unioned — one classification per canonical pair. Requires `registry.json` (written by `write-registry`); degrades to unfolded edges if absent. Fold logic is pure in `wiki_creator/relationship_fold.py`.
- Mention offsets (STU-489): extraction persists `mention_spans_by_chapter` in
  `*_full.json` — one `{surface, start, end}` per occurrence (uncapped, unlike the
  3-per-chapter context cap), character offsets into the chapter content saved to
  `chapters.json`. `Registry.from_artifacts` rebuilds one `Mention` per span with
  non-`None` `start`/`end` (`Mention.window(chapter_text)` extracts a centered
  context window); artifacts without the field degrade to the legacy
  one-Mention-per-context-sentence rebuild with `None` offsets. `write_registry.py`
  unwraps the per-type wrapper key (`persons_full`, …) when reading full files —
  before STU-489 it didn't, so real-run registries carried no mentions at all.
- Multi-tome (STU-485): `write_registry.py` accumulates each tome's registry into the
  series registry `library/<author>/<series>/registry.json` (`Registry.accumulate`,
  decisions `strategy="series_accumulation"`, delta in `processing_output/<slug>/registry_delta.json`).
  `entity_clustering.py` and `alias_resolution.py` seed tome N's resolution from it
  (`Registry.load_seed_table`) — absent/unreadable series registry degrades to unseeded.
  Re-running a tome replaces its mention contribution (idempotent); prior tomes are never re-resolved.
- Series orchestration (STU-487): `run_wiki.py --series library/<author>/<series>`
  (`make run-series SERIES=...`) runs every tome under `books/` in reading order,
  one full pipeline per tome. Tome order comes from the numeric filename prefix
  (`wiki_creator/series.py`, reuses `tome_labels.tome_number` — `04.5_` sorts
  between `04_` and `05_`; non-numbered tomes sort last). No series manifest.
  Accumulation/seeding are already wired per-tome (write-registry accumulates,
  clustering/alias seed from the series registry), so series mode is a pure
  sequential loop — each tome must finish before the next seeds from it. Per-tome
  run state (`.wiki_runs/`) is reused, so a re-run skips already-completed tomes.
- Collation (STU-511): a tier can trade its dedicated pages for one collective
  page, or none at all. Book YAML `generation.collation.<tier>.mode` =
  `dedicated` (default, pre-STU-511 behavior) | `collective` | `drop`, with
  `promote_if.appears_in_event_salience_above: N` keeping an entity dedicated
  when it takes part in an event more salient than `N` (participants **or**
  places, matching `events_for_entity`). `wiki_preparation.py` partitions right
  after identity binding — collated entities never reach a batch, so they cost
  no LLM call — and writes one deterministic `COLLATION` page per entity type to
  `processing_output/<slug>/collation_pages.json` (rewritten every run, deleted
  when empty, so flipping back to `dedicated` can't resurrect stale pages).
  Entries are name + aliases + mention/chapter counts, zero LLM; prose entries
  are a possible fast-follow. `assemble_wiki_pages.py` appends the pages,
  `wiki_export.py` renders them at the wiki root body-only (like `SYNOPSIS`) and
  `main_page_content` links them under Navigation — they carry no category, so
  that link is their only entry point. Titles come from
  `export.categories.labels.{minor_persons,minor_locations,minor_organizations,minor_other}`.
  Pure logic in `wiki_creator/collation.py`; `COLLATION` is declared in
  `templates/base.yaml`, the STU-504 page-type vocabulary.
- `export.index.{principals_shown, places_shown}` sizes the Main_Page showcase
  lists (STU-511, was `[:8]`/`[:5]` hardcoded in `export_helpers.py`). `0` empties
  a section; absent/negative/unparseable falls back to the 8/5 defaults.
- The co-occurrence window is the chapter's (STU-536): `build_cooccurrence_graph`
  takes `chapters` (the text) and slides over `split_sentences(text)`, so
  `_MAX_DIRECT_INTERACTION_GAP` means what its name says. It used to take
  `mentions_by_entity` and stitch a per-chapter list by iterating that dict —
  each entity's ≤3 context sentences, entity block after entity block. Sentence
  *i* and *i+1* were then two different entities' samples, pages apart (median
  4151 chars on Eragon; 7% were really adjacent prose), and since the entity
  order decided adjacency, it decided the graph: shuffling the roster moved
  28–33% of it (`research/relation-eval/diagnose_baseline.py`, now 0% by
  construction, pinned by `test_graph_does_not_depend_on_entity_order`). Against
  a 109-pair gold on Eragon the fix took detection F1 0.200 → 0.507, almost all
  of it precision (0.122 → 0.415) — level with the GLiREL that STU-467 was
  considering buying, which is why STU-536 blocked it: a third of the baseline's
  output was iteration-order noise, so beating it proved nothing.
  Two consequences. (1) **Coref only starts working here now.** It attributes a
  pronoun sentence to an entity, but the graph read the *sentence text* and
  matched names by regex, so an attributed sentence carried no name and only ever
  padded the pool — the attribution was never read. It is now the optional
  `mentions_by_entity` presence index: a listed sentence counts the entity
  present but yields no context (no name to quote). It matches by string, so the
  stage speaks one splitter — `split_sentences` and coref's
  `_find_sentence_containing` share `_sentence_spans`.
  (2) **The splitter is a blank sentencizer**, not the book's spaCy model: punct
  rules only, no model to install, so `make golden` stays hermetic (~4s for
  Eragon's 900k chars). It costs some boundary quality — a chapter title glues to
  the first sentence, a closing quote starts the next one — which is why contexts
  moved in the goldens.
- A chapter's number is its position (STU-546): `event_layer._chapter_numbers`
  numbers the ordered `chapter_summaries` 1..N. It used to regex the number out
  of the chapter's own text (`^(?:chapter\s+|c\.?h?\.?\s*)(\d+)`), which demands
  the book print `Chapter 12` — **1 of the 6 cached books does**. Narnia words
  them (`CHAPTER ONE`), le-jeu-de-lange writes `1. Un écrivain…`, and **Eragon
  prints no chapter number at all** (`DISCOVERY`, `PALANCAR VALLEY`), so a word
  numeral branch — the obvious fix — buys Narnia and nothing else. The number was
  never in the prose to recover: `parse_epub` emits an ordered list and
  `section_filter` tags the front matter, so position is the only universal
  source, and it *is* the printed number on both books that had one (Narnia 1-17,
  throne-of-glass 1-55, byte-identical 447 events). Narnia went 0 → 136.
  The failure was total and silent — no `event_pages.json`, no synopsis events,
  no participant-importance signal — because `build_events` returned `[]` and
  every downstream stage reads "no events" as an answer; it now warns when
  summaries produced none.
  Two consequences. (1) **A prologue takes number 1**, so a prologue book's
  numbers sit one below the printed ones — deliberate (a `prologue` word list is
  the same shape as the bug being closed) and it regresses nothing, since those
  books built zero events. (2) **The `chapter_id` fallback is deleted, not
  fixed**: a section id numbers spine items, so Narnia's `bookcontent2_0` is
  chapter *one* — it would have renumbered every chapter had it ever matched.
  `chapters.chapter_number` (first digit run) carries the same id hazard for its
  own callers; out of scope here.
  The `key_moments` path keeps its marker regex but the number must now name a
  real chapter of the book. The marker is the classifier's guess — it is handed
  chapter *ids* in `relationships.json`, so it prefixes `ch16:` on
  throne-of-glass and the chapter *title* (`EDMUND AND THE WARDROBE:`) on Narnia,
  and **43 of ~50 resolve on neither book**. That path is low-yield by
  construction and is not what fixes Narnia; matching markers against titles is a
  separate ticket.
- The number is assigned once, in `section_filter` (STU-550): `chapters.number_chapters`
  stamps `chapter_number` on each narrative chapter right after the front-matter
  verdict — the only place both the reading order and that verdict are known. It
  reaches `epub_data.json`, and `chapter_number_index` (ids **and** titles, since
  `chapter_summaries` is title-keyed on some books) resolves a reference to it.
  This closes STU-546's shape in the two places it was still live.
  **`sorted(context_by_chapter)` was sorting section ids as strings, not chapters**
  — `bookcontent10_0` before `bookcontent2_0`. Above
  `chapter_summary_max_chapters_per_entity` (8) chapters per entity, i.e. exactly
  the principals, the truncation then kept the lexicographic middle: Lucy's page was
  written from Narnia's chapters 9-16, never the wardrobe. Whether it fired was
  decided by the publisher's zero-padding (throne-of-glass `C01.xhtml` is padded and
  is the book we look at, so it was invisible), and nothing warned — the prompt
  looked full.
  **The bundle is the boundary.** `wiki_preparation` resolves every chapter
  reference it emits (`relationships[].chapters`, the new `context_chapters`,
  `chapter_summary_context[].revealed_at_chapter`), so `provenance`,
  `spoiler_blocks` and `generate_wiki_pages` read numbers and no longer call
  `chapter_number` at all. That is what makes the STU-492 gate honest: it compares
  the book YAML's `collapse_after_chapter: N` — set by someone who read the novel
  and means "chapter 20" — against a number in the same unit, where `x101.xhtml`
  used to yield 101. Latent (no book sets the key today), but a config key silently
  in a different unit than the code is the defect.
  **An unresolvable reference warns and is dropped**, never numbered by whatever
  digits it carries — `resolve_chapter_number` is the whole point, and falling back
  to digits is the bug being closed. `chapters.chapter_number` survives for
  `entity_status`, which sorts snippets by id digits: digits are monotone with
  position on every book in the library, so that use is accidentally safe, like
  `generate_wiki_pages`' relation ordering was. `event_layer._chapter_numbers` also
  stays — it numbers the ordered summaries 1..N, which already *is* the position,
  and it is handed no chapter records to read the field off.
- `workers` in relationship/coref config directly impact RAM usage.
- `.studio/config.yaml` and `.studio/runs/` must not be committed.
- Never add hardcoded word lists to scripts. All vocabulary belongs in `wiki_creator/cue_words/<lang>.json` (language-wide) or the book YAML `classification` section (book-specific). No script may define a fallback vocabulary constant — if a key is absent from cue_words, degrade gracefully to an empty collection.
- English is the default and the only language allowed in code. Nothing user-visible may be hardcoded in another language — no French (or any non-English) string literals in `.py`. Anything that needs translation is data, not code: it lives in YAML (`wiki_creator/templates/base.yaml` for template/output strings — `labels`, `briefs`, `few_shot`, `length_by_tier`, `chrome`, `language_names`; cue_words for detection vocabulary) keyed by language, and is read via helpers (`slot_label`, `section_brief`, `chrome_label`, …). Prompt *scaffolding* (instructions, grounding labels) stays English regardless of output language; only output-anchoring content (section titles, briefs, few-shot, the write-in-`<language>` directive) and reader-facing chrome follow `output_language(book_config)` (STU-510).
- `tests/test_e2e_golden.py` chains all deterministic resolution stages on the fixture novella and compares every stage output to goldens in `tests/fixtures/e2e/golden/stages/`. Any intentional behavior change in those stages requires `make golden-update` and a review of the golden diff in the same PR. The extraction seed is committed (`golden/seed/`, regenerate with `gen_seed.py`); a `@requires_en_sm` test keeps it shape-compatible with real extraction in CI.
- Spoiler blocks (STU-492): `wiki_export.render_page` wraps chapter-gated sections
  in native `mw-collapsible` divs and injects a dated relationship index under the
  Relations section. Gating is per-section via `content_units.revealed_at_chapter`
  (the min-chapter provenance from STU-491), matched to headings by normalized
  title. Enabled only when the book YAML sets `generation.spoiler.collapse_after_chapter: N`
  — unset keeps output byte-identical (goldens safe). The relationship index uses
  language-neutral fields only (names, French `relationship_type`, chapter numbers);
  the classifier's English `evolution`/`key_moments` are never surfaced. The index
  injects only under an exactly-`Relations` heading (an LLM-drifted heading is
  silently skipped, same tolerance as collapsible gating). Pure logic in
  `wiki_creator/spoiler_blocks.py`; section→heading map in `wiki_creator/sections.py`.
- Extraction is keyed on its config (STU-560): `entity_extraction.py` writes the
  resolved `ner` block to `processing_output/<slug>/extraction_config.json`
  (`ner.extraction_fingerprint`), and `run_wiki.py` re-runs `wiki-extraction`
  when it diverges from the book YAML (`extraction_config_changed`, also true
  when the file is absent — an artifact that names no backend is stale by
  definition). Extraction has no cache of its own; the orchestrator's skip was
  `status == "completed"` + `required_files` present, so a correct `ner` flip was
  read, applied to nothing, and never reported: the **three** books with an
  extraction cache were all rendering spaCy-typed entities while configured for
  GLiNER — Garrow ORG again, the STU-537 bug verbatim. Same rule as the STU-529/
  539/488 caches, one layer down: a cache is keyed on the config that produced
  it. The fingerprint holds only `ner` because that is what the class of bug is
  about — widen it when another config key silently outlives its artifact, not
  before. `make run-extraction` shells `studio run` directly and always
  re-extracts, so this only ever bites through `run_wiki.py`.
- GLiNER device placement (STU-570): `WIKI_NER_DEVICE=auto|cpu|cuda` (default
  `auto` — the pre-STU-570 behavior, take the GPU when there is one) picks where
  `gliner_ner.py` runs. It is **not** a book YAML key — the device is a property
  of the machine and the moment, not the novel, and a reader cannot answer "which
  device". Without it GLiNER always grabbed the GPU, so concurrent extractions
  across worktrees (a normal state here — a worktree per task) OOM each other on
  one 6 GB GPU, and the loser burns its 3 RALPH attempts. `cpu` *places* the
  second run instead of hiding the GPU with `CUDA_VISIBLE_DEVICES=""` (which only
  worked by accident, via `torch.cuda.is_available()` going False). Same root as
  the coref device bug, mirror image: device hardcoded, no config. An unknown
  value **raises** — a silently ignored device is the `ner`-block degradation rule
  one layer down. Env var, so it propagates to `studio run` subprocesses like
  `WIKI_MAX_CHAPTERS`; no CLI flag.
- Subset test runs (STU-497): two independent axes make any feature cheap to exercise.
  (1) Chapters — `WIKI_MAX_CHAPTERS=N` caps extraction to the first N chapters
  (`parse_epub._env_max_chapters` → truncation, the single source of truth); every
  downstream stage just consumes the shrunk `chapters.json`/`splits.json`, so the
  whole pipeline runs in seconds. Front doors: `run_wiki.py --max-chapters N` (sets
  the env for all stages) and `make run ... MAX_CHAPTERS=N` (the Makefile `export`s
  it, so `run-extraction`/`run-from-*` honor it too). Unset = full run, no behavior
  change (goldens safe). To re-slice an already-completed run, pair with
  `--restart wiki-extraction --clean`. (2) Entities — `generate_wiki_pages.py
  --entities NAME... [--force]` (STU-497/#110, `make generate-pages-entity ENTITY=...`)
  regenerates only a slice of pages without wiping the rest.
- Relation confidence is graded, not counted (STU-476): `confidence.py` used to
  read evidence *presence* — a type plus a verbatim quote was `explicit`, and the
  writer stated it as fact. Presence is not strength: Chaol is typed `amoureux`
  off "Their eyes met, and Chaol didn't hide his smile as she grinned at him",
  quoted word for word and indistinguishable from Dorian's intimate gesture. Only
  the classifier reads the excerpts, so **it** grades the tier; the vocabulary
  lives in `base.yaml#relationships.confidence` and travels with the payload like
  the STU-477 type vocabulary, injected in `_run_studio_classifier_item` — the one
  point both callers cross. `TIER_ORDER` stays in `confidence.py`, not on
  base.yaml's key order: it decides what over-grading *is*. Two rules are
  load-bearing. (1) **The floor no grade may lift**: an ungrounded type is
  `inferred` whatever it claims, so the STU-476 grade can only ever *lower*
  what the pre-existing grounding check already allowed. Absent grade (pre-STU-476
  artifacts) keeps the old presence reading. (2) **Grade the sentence, not the
  type you believe in** — the prompt says so and the eval scores it: gold pairs
  carry `max_confidence` and `score_confidence` reports the over-graded rate
  (`--max-overgraded` gates CI). Under-grading is deliberately not an error — it
  costs hedged prose; over-grading reaches the reader as a fact. Only 2 of the 10
  typed fixture pairs have power on that axis, and that is the corpus: weakening
  an excerpt to make the metric bite would score the classifier against fiction.
  Requiring `evidence` when `relationship_type != null` was already enforced by
  `scripts/relationship_classifier_validator.py` (the ticket's 57%-absent stat is
  run 18, pre-STU-495/496); STU-476 only added the grade rule beside it.
- Book-specific relationship types (STU-472): the book YAML
  `classification.relationship_types` (`name` + `description`) is **appended** to
  `base.yaml#relationships.enum`; absent ⇒ the generic vocabulary alone, unchanged.
  The bonds that define a world are exactly the ones a generic enum cannot name —
  the Rider–dragon link flattened to `ally`, carranam to `other`. Declared on the 6
  `inheritance` tomes; every other book is untouched. Three things are load-bearing.
  (1) **The name is the label** — a book type carries no `labels` map and no
  token/label split. A book declares one `output_language` and its YAML is written
  by someone who read the novel, so `name: lien de Dragonnier` is both what the
  classifier returns and what the page prints. The ticket's `lien_dragonnier` +
  rendered-label shape was dropped: it buys a config axis nobody needs.
  (2) **A book type must cross three gates, not one.** The ticket names only prompt
  injection. `relationship_classifier_validator` rejected any type outside
  `relationship_tokens()`, so an injected book type would have been *validated
  against a table that never heard of this book* — RALPH would retry it to death.
  It now reads the vocabulary out of the **payload** (`allowed_types`), i.e. judges
  the answer against the question we actually asked; no payload vocabulary (pre-472
  artifact, offline caller) falls back to the generic enum. The third gate is
  rendering (`canonical_relationship`/`relationship_label` take `book_config`).
  (3) **An incomplete or shadowing entry raises**, it does not degrade — a type the
  config declares and the pipeline silently drops is the STU-470 shape.
  STU-477 is why this was cheap: the vocabulary already travelled in the payload
  with per-type criteria, so the agent prompt needed **no edit at all**.
- `antagonist` is now `enemy` (STU-472): a relationship type must be a word a reader
  would use. *Antagonist* is narratology — a role defined toward THE protagonist —
  so `Cain.wiki` typing `[[Captain Westfall]] — antagoniste` on the sole grounds that
  both are in the tournament claims Cain heads his own novel. It also made the term a
  catch-all for "neither friend, family nor lover", which is what the audit caught.
  `legacy: [antagoniste, antagonist]` keeps artifacts already on disk rendering — in
  the new word. **`ally` was checked and kept**: an ally is defined by a shared goal,
  not by a story-structure role, and readers do say it; its STU-477 criterion already
  names the concrete test (shared goal + mutual trust), with `wary_alliance` for
  cooperation without trust. Goldens unaffected — relationship typing is an LLM stage,
  outside the golden path by construction.
- Untyped relations never render (STU-501): a relationship with no usable
  `relationship_type` is **omitted** from every reader-facing surface — the dated
  relationship index, per-relation prose, and the writer prompt. No neutral
  placeholder, no metric name. "Usable" is decided in one place,
  `wiki_creator/relationship_types.usable_relationship_type`, which rejects `None`,
  empty, and the sentinel strings `null`/`none` (the classifier can emit JSON null
  as a literal string, and previously the writer prompt filled the gap with the raw
  co-occurrence metric label, which the LLM then echoed verbatim). All render sites
  route through this helper (`spoiler_blocks`, `provenance.relation_units`,
  `confidence`, `generate_wiki_pages` prompt builders). This is a rendering fix,
  independent of classification correctness (STU-495/476).
  That "all render sites" claim was false on one path until STU-528:
  `character_graph.indirect_relationships` built `path_edge_types` with its own
  `or "co-occurrence"` fallback, so the metric label reached the writer prompt
  (`path: friend → co-occurrence`) for every indirect relation with an untyped hop.
  It routes through the helper now, and an untyped hop **drops the whole indirect
  relation**, not just the hop — a path is nothing but its edge types, so a hole
  leaves the LLM to fill it. The target itself isn't dropped: the next fully-typed
  simple path to it is used if there is one.
- A Studio failure is not a decline (STU-562): a pair the classifier never judged
  — a subprocess timeout, an unrecoverable stdout — used to be appended untyped
  with a `[WARN]` nobody reads, so STU-501 omitted it exactly as it omits a pair
  the model *did* read and decline. Both were `relationship_type: null`, and the
  artifact recorded no difference: the next person measuring the graph could not
  tell loss-with-judgment from loss-with-none-behind-it. Two halves.
  (1) **Retry.** `_run_studio_classifier_item` retries a *transient* failure
  (`studio_run_timeout` / `studio_run_failed` / `studio_run_output_missing`) once
  — `studio_cli_missing` is terminal and is not retried, since retrying an absent
  binary only stalls. This is the outer, subprocess-level retry; it is distinct
  from the pipeline's RALPH loop (`max_attempts: 3`), which catches an off-schema
  *agent output*, not a killed `studio run`. STU-564's log recovery already
  absorbs most of what used to surface as a parse error, so the timeout is the
  live case. (2) **Mark.** A pair that still fails is stamped
  `classification_error` (a new optional `Relationship` field), so the artifact
  distinguishes it from a decline — a retry that does not persist the distinction
  leaves the same fog. `_load_done_keys` treats a stamped pair as **unfinished**:
  it drops it from both the resume keys and the kept list, so a re-run retries it
  once more without duplicating it. The field is `null` on every declined and
  typed pair, so it changes no reader surface (STU-501 still omits the untyped
  pair) and no golden (relationship typing is an LLM stage, off the golden path).
  Related: `stats.classified` is vestigial (STU-563) — the counter that would
  have surfaced this reads 0 on every real run.
- Editorial stance (STU-507): whether pages speak from inside the fiction is
  **declared** in the book YAML (`generation.editorial_stance`), not inherited
  from anti-hallucination prompting. `wiki_creator/editorial_stance.py` holds the
  vocabulary (`mode: in_universe | out_of_universe | hybrid`,
  `hybrid_exceptions`, `expose_pipeline_metadata`, `expose_importance_tier`,
  `forbid_author_mentions`); an unknown mode or exception key raises rather than
  degrading — a silently wrong posture is the bug this closes. Grounding and
  stance are two separate prompt blocks: `GROUNDING_BLOCK` (unconditional, "the
  excerpts are the only truth") and `EditorialStance.prompt_block(sections)`
  (posture only), so switching to `out_of_universe` cannot weaken grounding. The
  four out-of-universe surfaces are each gated by one key: `## Références` and
  `## Rôle dans le récit` via `allows_section` (filtered in `generation_profile`,
  so the section is never generated *and* never mentioned in the prompt), the
  Main_Page `== Statistiques ==` block via `expose_pipeline_metadata`, and the
  importance-tier categories via `expose_importance_tier` (both threaded from
  `wiki_export.main`). Defaults reproduce the pre-STU-507 posture (hybrid, both
  exceptions, metadata and tier exposed) — an unconfigured book is unchanged.
  Inter-page tone coherence is not contractable per page (INV-08); it belongs to
  the consolidation pass (STU-508).

- Editorial-stance consolidation (STU-508): a single post-generation pass
  (`consolidate_editorial_stance.py`, last `wiki-generation` pre-step in
  `run_wiki.py`; `make consolidate-stance`) scans every generated page
  (`wiki_pages`/`book_synopsis`/`event_pages`/`collation_pages`, `_failed`
  skipped) for register that contradicts the declared `editorial_stance.mode`
  (STU-507) and writes an advisory drift report to
  `processing_output/<slug>/editorial_stance_report.json` plus a readable
  stderr summary (page → deviation → short quote, not just a score). **Advisory
  only** — `status: non_binary_advisory`, never fails the run (INV-08: tone is
  not per-page contractable). Deterministic, **zero LLM** — the Fable frugality
  constraint (one pass, not a verifier per page) holds by construction; marker
  vocabulary lives in `cue_words/<lang>.json` (`editorial_stance_markers`, three
  buckets: `meta_narrative`/`reader_address`/`author`), absent → no findings.
  Detection is tied to stance semantics, not heuristic: `meta_narrative` +
  `reader_address` are flagged by the in-universe rule (everywhere in
  `in_universe`; outside the hybrid exception sections in `hybrid` — matched by
  localized heading via `slot_label`; never in `out_of_universe`), `author`
  whenever `forbid_author_mentions` regardless of mode/section. Pure logic in
  `wiki_creator/consolidation.py`.
- Canon policy (STU-512): `library/<author>/<series>/canon.yaml` declares which
  source is authoritative for a series — `primary_source`, a `sources` list
  (`id`/`type`/`path`/`book`/`authority`), `conflict_resolution` (`strategy`:
  `highest_authority` | `primary_wins` | `flag_for_review`; `on_unresolved`:
  `flag` | `fail`) and `cross_tome.later_tome_overrides`. Pure logic in
  `wiki_creator/canon.py`. Two real consumers: `parse_epub.py` resolves which
  file it reads via `resolve_book_source`, and `write_registry.py` passes
  `later_tome_overrides` into `Registry.accumulate` (the only pre-existing
  cross-tome arbitration point — an `entity_type` disagreement between tomes,
  previously hardcoded to "earlier tome wins"). Both consumers are pinned by a
  wiring test (`test_parse_epub_reads_the_source_the_canon_declares`,
  `test_write_registry_cross_tome_override_follows_canon`) — unwire either and a
  test fails; without them the whole feature was deletable with the suite green.
  A source binds to a tome via `book:`, defaulting to the filename stem. The book
  YAML's `file_path` stays the identity anchor (it derives every output path);
  canon only decides which bytes are read.
  **No policy degrades, a broken policy fails**: absent/empty `canon.yaml`, or a
  book the canon doesn't declare, reads `file_path` as before (warning on the
  latter); a `canon.yaml` that exists but is malformed raises, because silently
  ignoring a broken authority file would read a source nobody vouched for.
  The two halves have very different reach. **Source** arbitration
  (`strategy`/`on_unresolved`/`authority`) is unreachable in production —
  `resolve_source` returns early at one candidate, and one EPUB per tome means
  there is never a second. Deliberate: the rule is written down **before**
  `scrape_fandom.py` (a second source of truth on the same content, currently
  LoRA-dataset only) is wired into generation, per STU-512's acceptance criteria.
  **Cross-tome** arbitration is one `canon.yaml` away from live: `inheritance`
  (6 tomes) and `hollow_star_saga` (4) already accumulate via `make run-series`,
  and only `throne-of-glass` (1 tome, where cross-tome can never fire) declares a
  canon today. `later_tome_overrides` is a boolean; STU-488 (the real consumer)
  wants "trace both with provenance rather than overwrite", so it will need to
  widen to an enum.
- Unified entity taxonomy (STU-505): `base.yaml#entity_types` is the single
  authority for the type vocabulary AND its routing. Each type declares
  `ner_labels` (the stock+custom NER labels it absorbs) and an `export` block
  (`subdir`, `full_key`, `infobox_template`, `infobox_source`, `category_key`,
  `category_default`, `importance_categories`, `tome_label_key`) — the data the
  five old Python tables (`types.py` Literal, `entity_extraction.LABEL_TO_TYPE`,
  `export_helpers._INFOBOX_TEMPLATES`, `wiki_export._SUBDIR`,
  `md2wiki._TEMPLATE_NAMES`) encoded separately. All consumers read it via
  `wiki_creator/entity_taxonomy.py`; adding a type is a `base.yaml` edit, no
  `.py` touched. `FACTION` is first-order now (`ner_labels: [FACTION]`) — the
  extractor no longer retags it to `ORG`. `types.ENTITY_TYPE` is a plain `str`;
  `FROZEN_ENTITY_TYPES` is a snapshot checked against `base.yaml` at import
  (`_assert_taxonomy_in_sync` raises on drift). `entity_taxonomy.resolution_types()`
  (NER types + `OTHER`) drives every per-type bucket — `Splits.by_type` is a
  dict keyed by it (was five named fields), so `splits.json`/`split-clusters`
  output nests clusters under `by_type`. `SYNOPSIS`/`COLLATION` stay declared as
  generation-only pseudo-types (no `ner_labels`, never enter resolution). The
  STU-504 `entity-type-declared` validator reads the same keys, so a run using a
  type absent from `base.yaml` fails. Mention-count refinement in
  `entity_classification.get_total_mentions` still threads only PERSON/PLACE/ORG/
  EVENT full-registries; a FACTION entity's counts come from the surface index,
  not its `*_full.json` — a possible fast-follow.

## Config Is Read By People Who Know Books, Not Pipelines

The book YAML is the project's user interface, and its users are readers and
editors — literature people, not engineers. Every key there must be answerable
by someone who has read the novel and nothing else.

- **Name the property of the book, never the mechanism.** `ner.invented_names:
  true` (STU-537), not `ner.backend: gliner` — "are this novel's names invented?"
  is a question about *Eragon*; "which NER backend?" is a question about us. The
  code derives the mechanism from the answer, in one place.
- **A key whose right value requires knowing our internals is a bug**, not a
  config. Either derive it, or reshape the question until the novel answers it.
- Same rule for values: a threshold nobody can set without reading our source is
  a default we have not chosen yet.

## Working Norms

- **ALWAYS use a git worktree for every task.** Start each task in its own isolated worktree/branch off `main` — never work directly on a shared or unrelated branch. This keeps every change scoped to a single issue and prevents mixing concerns.
  - **A worktree runs its own `scripts/` against the checkout `pip install -e .` pinned (STU-569).** The editable install records one absolute path for the whole interpreter, so a subprocess (`studio run`, `python scripts/...`, `run_wiki.py`) imports `wiki_creator` from *that* tree, not the worktree it was launched from. `make` and the pytest `conftest` prepend the right tree, so those paths are correct by construction; anything else needs `PYTHONPATH=$(pwd)`. `wiki_creator/__init__.py` now fails loudly when the imported package is not the one under the cwd (`WIKI_CREATOR_ALLOW_FOREIGN_CHECKOUT=1` opts out) — the silent case (unchanged signature, changed body, green suite on code the branch never ran) is what this closes.
- Prefer `rg` for search.
- Use `apply_patch` for manual edits.
- Do not assume docs are current; verify against `Makefile`, pipeline YAML, and tests.
- Before claiming a fix, rerun the relevant tests and ideally `pytest -q`.

## Where a Task Runs: `claude:local` vs `claude:web`

Every actionable wiki-creator issue in Linear carries one of two labels under the
`claude` group, so it is unambiguous before starting whether a task can be *both
done and verified* in a Claude Code **web** sandbox or must run on a **local**
machine. The web sandbox has **no torch/GLiNER, no GPU, no `library/` EPUBs, no
gold corpus, no `models/`, no API key** — all gitignored or absent by
construction — and cannot install or run any of them.

The test is verification, not just editing: if you can write the change on web
but cannot prove it works there, it is `claude:local`.

- **`claude:local`** — the deliverable or its verification needs any of: GLiNER /
  torch / a GPU (NER, extraction re-runs, the label sweep, the OOM/device bug);
  LoRA / Ollama training or benchmarking; the gitignored assets (EPUBs,
  `research/ner-eval` gold, `models/`); or a **full live-LLM run over real books**
  to produce or measure the result (relation-typing accuracy, alias-adjudication
  precision across the library, embedding disambiguation, GraphRAG eval,
  orchestrator parity when removing `run_wiki.py`). A number the norms require
  ("load-bearing and swept, not guessed") is a local number.
- **`claude:web`** — self-contained: pure logic + deterministic tests (`pytest`
  with `en_core_web_sm`), YAML/config covered by `make golden` / `make smoke`
  (LLM-free by construction), rendering/goldens, docs, refactors, wiring tests.
  A change whose whole proof is the test suite on the committed fixture novella is
  a web task.

Rule of thumb: **STU-571 is the archetype `claude:local`** — the fix is a one-line
`gliner_label` edit, but the norm forbids shipping it without re-running
`research/ner-eval/sweep_labels.py` against GLiNER + gold, none of which the
sandbox has. A task is not web just because the *edit* is small; it is web only if
its *evidence* is reachable there.

## Personal Working Style — Ariane

Portable working style (mirrors `~/.claude/CLAUDE.md`, duplicated here so Claude Code web has it without the machine-global file).

### Collaboration Model

I give direction (a ticket, a bug report, a priority). You do the work — code, tests, lint, commits. **Act, don't ask for permission** on reversible, expected steps: running tests, linting, type-checking, committing, pushing to a branch you're already working on. If something fails, fix and retry without asking first.

Only stop and ask for: irreversible/destructive actions (force-push, history rewrite on a shared branch, deleting something not yours), major architectural decisions, or a genuinely ambiguous requirement — and even then, state your assumption and let me correct it rather than opening with a question when a reasonable default exists. Terse output — no recap of what was just done, no "veux-tu que je…", no unsolicited "next steps" list.

### Code Philosophy

- **Simplicity first.** Minimum code that solves the problem. No speculative abstraction, no unrequested config/flexibility, no error handling for scenarios that can't happen. If it could be a third the size, rewrite it — ask "would a senior engineer call this overcomplicated?"
- **Surgical changes.** Touch only what the task requires. Don't refactor adjacent code, don't restyle to your own taste — match existing convention even if you'd choose differently. Every changed line should trace to the request.
- **Remove over add, fix the root cause.** Default bias is deletion, not accumulation. Disproportionate machinery for a small win means the *approach* is wrong, not that it needs tidying. When you see defensive/validation/dedup scaffolding, ask "why does this need to exist?" — if the answer is "to paper over X," undo X; don't harden the band-aid.
- **Comments: default to none.** Write one only when the code cannot say the *why* itself — a hidden constraint, a non-obvious invariant, a workaround for a specific bug. Never explain *what* the code does. One clause per fact, no connective prose.

### Git Workflow

- **Commit small and often** — one logical change per commit (new function, bug fix, refactor, test). Don't batch unrelated fixes into one commit.
- Commit trailer: `Co-Authored-By: <model name> <noreply@anthropic.com>` — derive the name from the model actually running the session, never hardcode a version string that goes stale.
- **Always tag the Linear issue in the MR description** — reference the issue key (e.g. `STU-515`) in the merge/pull request body so Linear links the MR to the issue.

### Linear Issues

Every issue created or updated carries the full metadata, not just a title and description. An issue missing these is incomplete — fill them at creation, don't defer:

- **Labels** — defects get `bug`; feature/refactor tasks don't. On wiki-creator, every actionable issue also carries `claude:local` or `claude:web` (see "Where a Task Runs" above).
- **Estimate** — always set, even if rough.
- **Priority** — always set, never left at "No priority".
- **Project / cycle** — assign when one applies.
- **Relations** — encode ordering as `blockedBy`, never as prose in the description.

### Presenting Trade-offs

When there are 2+ options to choose between (architecture picks, "swap A for B", design decisions), use a side-by-side pros/cons layout, not narrative paragraphs:

```
**Option A**
- ✅ <pro>
- ❌ <con — and how to mitigate, if cheap>

**Option B**
- ✅ <pro>
- ❌ <con>

**My take:** <one-line recommendation + why>
```

One fact per bullet line, always close with a recommendation. (Doesn't apply to a single-finding go/skip approval — that stays one line.)

### Language

Chat replies in French (native thinking language). Everything that leaves the chat — code, comments, commit messages, PR/MR descriptions, docs, READMEs, tickets, skills, config files, any file another person might read — is **English**, no exceptions. Default to English proactively for any written artifact.

### Decision-Making Style

I'm AuDHD. Two things that help:

1. **Externalize criteria, don't rely on "feel."** When proposing how to split work, cut scope, or classify effort, list the concrete criteria so I can verify against them.
2. **Don't interrupt hyperfocus with unsolicited "are you sure" checks.** If I'm clearly executing on a plan, stay out of the way. Surface concerns before I start or after a natural checkpoint, not mid-flow.
