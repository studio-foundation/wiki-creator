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

- `entity_extraction.py` keys chapter mentions by chapter ID, not chapter title.
- `merge_entities.py` passes through only the current `resolve-clusters` output shape (runs before `alias-resolution` per the STU-276 pipeline order; STU-447 dropped the older `split-clusters` + `entity-resolution-*` compat branch and a vestigial `alias-resolution` priority check that predated STU-276 and never fired in production).
- `split_clusters.py`, `relationship_extraction.py`, and `verify_entity_types.py` are intentionally tolerant of missing `file_path` in unit-test mode.
- `generate_wiki_pages.py` must run after `wiki-preparation`; it consumes `wiki_inputs/<slug>/batch_*.json`.
- `generate_book_synopsis.py` (SP4) consumes `events.json` (SP0) and writes `processing_output/<slug>/book_synopsis.json`; `load_wiki_pages.py` appends that page to the export flow and `wiki_export.py` renders it at the wiki root (`Synopsis.wiki`, no infobox/categories, `entity_type: SYNOPSIS`). If `events.json` is absent, the stage warns and skips — it never fails the run.
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
- `workers` in relationship/coref config directly impact RAM usage.
- `.studio/config.yaml` and `.studio/runs/` must not be committed.
- Never add hardcoded word lists to scripts. All vocabulary belongs in `wiki_creator/cue_words/<lang>.json` (language-wide) or the book YAML `classification` section (book-specific). No script may define a fallback vocabulary constant — if a key is absent from cue_words, degrade gracefully to an empty collection.
- `tests/test_e2e_golden.py` chains all deterministic resolution stages on the fixture novella and compares every stage output to goldens in `tests/fixtures/e2e/golden/stages/`. Any intentional behavior change in those stages requires `make golden-update` and a review of the golden diff in the same PR. The extraction seed is committed (`golden/seed/`, regenerate with `gen_seed.py`); a `@requires_en_sm` test keeps it shape-compatible with real extraction in CI.

## Working Norms

- **ALWAYS use a git worktree for every task.** Start each task in its own isolated worktree/branch off `main` — never work directly on a shared or unrelated branch. This keeps every change scoped to a single issue and prevents mixing concerns.
- Prefer `rg` for search.
- Use `apply_patch` for manual edits.
- Do not assume docs are current; verify against `Makefile`, pipeline YAML, and tests.
- Before claiming a fix, rerun the relevant tests and ideally `pytest -q`.
