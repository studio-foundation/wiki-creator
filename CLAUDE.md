# CLAUDE.md

## Project Snapshot

- Repo: `wiki-creator-by-studio`
- Purpose: extract entities from EPUB novels, classify them, generate wiki pages, export wikitext
- Current verified state on 2026-03-09: `pytest -q` => `288 passed`

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
make pages-export
make run-generation
make run-from-resolution
make run-from-generation
make run-status
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
- [scripts/generate_wiki_pages.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_wiki_pages.py): standalone Ollama generation
- [scripts/wiki_export.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/wiki_export.py): Markdown -> wikitext

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

## Gotchas

- `entity_extraction.py` keys chapter mentions by chapter ID, not chapter title.
- `merge_entities.py` supports both current `resolve-clusters` output and older `entity-resolution-*` stage shapes for compatibility with tests and older runs.
- `split_clusters.py`, `relationship_extraction.py`, and `verify_entity_types.py` are intentionally tolerant of missing `file_path` in unit-test mode.
- `generate_wiki_pages.py` must run after `wiki-preparation`; it consumes `wiki_inputs/<slug>/batch_*.json`.
- `workers` in relationship/coref config directly impact RAM usage.
- `.studio/config.yaml` and `.studio/runs/` must not be committed.
- Never add hardcoded word lists to scripts. All vocabulary belongs in `wiki_creator/cue_words/<lang>.json` (language-wide) or the book YAML `classification` section (book-specific). No script may define a fallback vocabulary constant — if a key is absent from cue_words, degrade gracefully to an empty collection.

## Working Norms

- Prefer `rg` for search.
- Use `apply_patch` for manual edits.
- Do not assume docs are current; verify against `Makefile`, pipeline YAML, and tests.
- Before claiming a fix, rerun the relevant tests and ideally `pytest -q`.
