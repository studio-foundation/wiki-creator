# CLAUDE.md

## Project Snapshot

- Repo: `wiki-creator-by-studio`
- Purpose: extract entities from EPUB novels, classify them, generate wiki pages, export wikitext
- Current verified state on 2026-07-13: `pytest -q` => `1113 passed, 37 skipped`
  (skips = tests needing optional spaCy models or the `coref` extra; see `tests/_markers.py`)

## Commands

```bash
pip install -e ".[dev]"
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

## wiki-resolution Stage Order (as of STU-276)

Inside `wiki-resolution`, order matters:
1. `merge-entities` + `relationship-extraction` run first
2. `alias-resolution` runs after — reads entities from merge-entities output
3. `entity-classification` reads entities from alias-resolution, relationships from relationship-extraction

## Chapter Summary: temporal_context (as of STU-271)

- Each chapter summary carries `temporal_context: present | flashback`
- Detected by `_detect_temporal_context` using flashback cues from `cue_words/<lang>.json`
- Prompt is split into two blocks (present vs backstory) depending on this value
- `build_chapter_summary_context` propagates `temporal_context` to the context dict

## Gotchas

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
  once in `load_wiki_pages.py` (the `wiki-page` stage the `unique-page-title`
  validator checks and export renders): different-type pages that would share a
  `page_filename` get the type label appended, so the flat MediaWiki namespace
  stays collision-free. Scope is `from_artifacts` only — cross-tome type
  arbitration in `Registry.accumulate` is governed by the STU-512 canon policy,
  not this one. The 11 Throne-of-Glass `entity_overrides` are `force_type`
  (classification), not collision rustines, so removing them needs a real spaCy
  run to verify — left in place.

- `entity_extraction.py` keys chapter mentions by chapter ID, not chapter title.
- `merge_entities.py` passes through only the current `resolve-clusters` output shape (runs before `alias-resolution` per the STU-276 pipeline order; STU-447 dropped the older `split-clusters` + `entity-resolution-*` compat branch and a vestigial `alias-resolution` priority check that predated STU-276 and never fired in production).
- `split_clusters.py`, `relationship_extraction.py`, and `verify_entity_types.py` are intentionally tolerant of missing `file_path` in unit-test mode.
- `generate_wiki_pages.py` must run after `wiki-preparation`; it consumes `wiki_inputs/<slug>/batch_*.json`.
- `generate_book_synopsis.py` (SP4) consumes `events.json` (SP0) and writes `processing_output/<slug>/book_synopsis.json`; `load_wiki_pages.py` appends that page to the export flow and `wiki_export.py` renders it at the wiki root (`Synopsis.wiki`, no infobox/categories, `entity_type: SYNOPSIS`). If `events.json` is absent, the stage warns and skips — it never fails the run.
- `generate_event_pages.py` (SP3/STU-481, STU-502) consumes `events.json` (SP0) and writes `processing_output/<slug>/event_pages.json` — one `EVENT` page per event with `salience >= threshold` (default `0.7`, raised from `0.6` in STU-502 to drop the low-value long tail) that has ≥1 participant. Title and infobox `{participants, lieu, chapitre, issue}` are built deterministically from the event; the writer LLM only authors the `## Déroulement` prose (grounded, spoiler-safe via forbidden_names). To stop the writer paraphrasing the title (STU-502), `build_event_prompt` injects the `DEFAULT_CONTEXT_WINDOW` (=3) neighbouring events before/after in narrative order as **read-only** NARRATIVE CONTEXT — background to situate the event (what leads up to it / what it brings about), never facts to attribute to it; `neighbor_context` windows the full events list, so context spans below-threshold neighbours too. `load_wiki_pages.py` appends the pages; `wiki_export.py` renders each under `output/wiki/events/` with `Infobox_event` + `[[Category:Événements]]`. Thresholds are configurable via book YAML `generation.event_pages` (`salience_threshold`, `max_pages`, `max_tokens`). Absent/empty `events.json` warns and skips — never fails the run. Titles are the full event description (grounded, unique) — LLM-named events are a possible fast-follow.
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
  are a possible fast-follow. `load_wiki_pages.py` appends the pages,
  `wiki_export.py` renders them at the wiki root body-only (like `SYNOPSIS`) and
  `main_page_content` links them under Navigation — they carry no category, so
  that link is their only entry point. Titles come from
  `export.categories.labels.{minor_persons,minor_locations,minor_organizations,minor_other}`.
  Pure logic in `wiki_creator/collation.py`; `COLLATION` is declared in
  `templates/base.yaml`, the STU-504 page-type vocabulary.
- `export.index.{principals_shown, places_shown}` sizes the Main_Page showcase
  lists (STU-511, was `[:8]`/`[:5]` hardcoded in `export_helpers.py`). `0` empties
  a section; absent/negative/unparseable falls back to the 8/5 defaults.
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

## Working Norms

- **ALWAYS use a git worktree for every task.** Start each task in its own isolated worktree/branch off `main` — never work directly on a shared or unrelated branch. This keeps every change scoped to a single issue and prevents mixing concerns.
- Prefer `rg` for search.
- Use `apply_patch` for manual edits.
- Do not assume docs are current; verify against `Makefile`, pipeline YAML, and tests.
- Before claiming a fix, rerun the relevant tests and ideally `pytest -q`.

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
