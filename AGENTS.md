# AGENTS.md

## Scope

This file is for coding agents working in `wiki-creator-by-studio`.
It complements `CLAUDE.md` with repo-specific execution guidance.

## First Checks

Before changing code or docs, verify the current workflow from:
- [Makefile](/home/arianeguay/dev/src/wiki-creator-by-studio/Makefile)
- [run_wiki.py](/home/arianeguay/dev/src/wiki-creator-by-studio/run_wiki.py)
- [.studio/pipelines/wiki-extraction.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/wiki-extraction.pipeline.yaml)
- [.studio/pipelines/wiki-resolution.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/wiki-resolution.pipeline.yaml)
- [.studio/pipelines/wiki-preparation.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/wiki-preparation.pipeline.yaml)
- [.studio/pipelines/pages-export.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/pages-export.pipeline.yaml)

Do not treat `README.md` as source of truth when it conflicts with code.

## Repo Truths

- Outputs are per-book under `library/<author>/<series>/...`, not global repo folders.
- The active workflow is:
  1. `wiki-extraction`
  2. `wiki-resolution`
  3. `wiki-preparation`
  4. `scripts/generate_wiki_pages.py`
  5. `pages-export`
- `wiki-generation.pipeline.yaml` was deleted (STU-591); its generation scripts are pre-steps of `pages-export` in `run_wiki.py`.
- `entity_extraction.py` stores chapter data by chapter ID.

## Safe Commands

```bash
pytest -q
mypy wiki_creator/
make run-status
make test-extraction
make test-clustering
make test-relationships
```

For full pipeline work, use an explicit book when there is any ambiguity:

```bash
make run BOOK=library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
```

## Editing Rules For This Repo

- Keep manual code edits minimal and local.
- Preserve backward compatibility for test harnesses when scripts are used both by Studio and directly from unit tests.
- When a script reads `additional_context.file_path`, consider whether unit tests also invoke it without that field.
- Prefer fixing contract mismatches at the boundary instead of rewriting downstream code.

## Verification

Minimum before closing a code task:
- run the focused tests for touched files
- if behavior changed across shared scripts, run `pytest -q`

Current known good baseline:
- `pytest -q` passed on 2026-07-10 with `735 passed, 31 skipped`
  (skips require optional spaCy models / the `coref` extra — see `tests/_markers.py`)

## Common Pitfalls

- Assuming outputs live at repo root instead of under each series/book directory
- Forgetting that `generate_wiki_pages.py` is standalone, not a Studio stage
- Breaking CLI/test compatibility while optimizing for Studio payloads
- Documenting a removed `wiki-generation` pipeline as the main workflow without checking `Makefile`
