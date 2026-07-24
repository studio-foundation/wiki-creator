# CLAUDE.md — wiki_creator/nlp/

NER backend: spaCy / GLiNER. Moved verbatim from the root CLAUDE.md Gotchas section so it loads only when working under `wiki_creator/nlp/`.

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


- Extraction is keyed on its config (STU-560): `entity_extraction.py` writes the
  resolved `ner` block to `processing_output/<slug>/extraction_config.json`
  (`ner.extraction_fingerprint`), asserted by `expected_outputs` (STU-600). The
  staleness *check* (`extraction_config_changed`) died with `run_wiki.py`
  (STU-457): the bug it closed was the orchestrator's skip-on-completed reading
  a `ner` flip and applying it to nothing — every `studio run` re-extracts, so
  there is no skip left to go stale. The class rule stands for the per-unit
  caches: a cache is keyed on the config that produced it (STU-529/539/488, the
  engine's prompt-fingerprinted map resume).

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
