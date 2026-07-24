# CLAUDE.md

## Project Snapshot

- Repo: `wiki-creator-by-studio`
- Purpose: extract entities from EPUB novels, classify them, generate wiki pages, export wikitext
- Current verified state on 2026-07-21: `pytest -q` => `2009 passed, 1 skipped`
  (skip count depends on which optional models/extras are installed; see `tests/_markers.py`)

## Commands

```bash
pip install -e ".[dev]"      # test suite: carries en_core_web_sm
pip install -e ".[models]"   # to run a book: the lg models the books declare (~1 GB)
pytest -q
mypy wiki_creator/

make run          # studio run wiki-full: the whole build, one Studio run
make run-series
make run-extraction
make run-resolution
make run-preparation
make pages-export
make generate-pages
make generate-pages-dry
make generate-synopsis
make generate-synopsis-dry
make consolidate-stance
make smoke        # e2e smoke test on the committed fixture novella
make golden       # golden regression run: chained resolution stages vs committed goldens (~2s, no spaCy/LLM)
make golden-update  # regenerate goldens after an INTENTIONAL behavior change, then review the diff
```

The `wiki` CLI is the ergonomic front door (STU-597), a thin launcher over
`studio run` with short book aliases and `--help` — it owns no stage order
(Studio does). It does not replace the Makefile: `make` keeps the dev/test
targets (`smoke`/`golden`/`eval-*`) the CLI has no reason to wrap.

```bash
wiki ls [--series]                        # list books / series in the library
wiki book run tog                         # studio run wiki-full on a book by alias
wiki book extraction narnia               # single pipeline (extraction/resolution/preparation)
wiki book run tog --max-chapters 3        # sets WIKI_MAX_CHAPTERS
wiki book pages narnia                    # whole pages-export
wiki book pages narnia --entities "Lucy" --force   # regenerate only some pages (the page-slice)
wiki book add path/to.epub                # import epub + scaffold a minimal book YAML (--llm, --force)
wiki series run inheritance               # wiki-full over every tome, reading order
wiki replay <run-id> [--stage wiki-resolution]     # studio replay, restart from a boundary
wiki status [run-id]  ·  wiki logs <run-id>        # observability (run-ids feed replay)
wiki <cmd> --dry-run                      # print the studio command(s) instead of running
```

A book resolves from a short query — its slug, series, author, or an explicit
`aliases:` list in the book YAML (`aliases: [tog]` reaches throne-of-glass); an
ambiguous or unknown query lists candidates. `book add` fills only the
mechanical fields; the load-bearing reader-authored ones (`ner.invented_names`,
`notability`, `classification` roles) stay for a human — `--llm` drafts only a
`novel_summary`. `replay`/`status`/`logs` are thin passthroughs to the matching
`studio` command; `clean` is deliberately not wrapped (destructive stays an
explicit Makefile opt-in — a future `wiki clean <alias> --yes` is the only
remaining gap).

Default `BOOK` in the `Makefile`:

```bash
library/c_w_lewis/narnia/books/01-the_lion_the_witch_and_the_wardrobe.yaml
```

The Makefile is a front door, not a sequencer (STU-592): every target dispatches
exactly one command. `run_wiki.py` is deleted (STU-457) — `make run` is
`studio run wiki-full --input-file $(BOOK) --live`, and Studio owns all
sequencing. What replaced run_wiki's interface:
- **Restart from a boundary**: `studio replay <run-id> --restart --stage
  wiki-resolution` (run ids from `studio status`). The old `run-from-*` targets
  and `--clean` are gone; the ergonomic front door is STU-597's scope.
- **Retry**: RALPH retries inside each stage; there is no outer per-pipeline
  retry loop anymore.
- **Resume**: per-unit caches (engine map resume, verdict caches) make a plain
  re-run cheap on the LLM side; deterministic compute (extraction, co-occurrence)
  re-executes. The old `.wiki_runs/` skip-on-completed state file is gone, and
  with it the STU-560 staleness check it needed (`extraction_config_changed`) —
  no skip, no stale skip. `extraction_config.json` is still written and asserted
  (STU-600).
- **Series**: `make run-series` loops `discover_series_books` (reading order,
  `04.5_` between `04_` and `05_`) over `studio run wiki-full`.
The `make test` / `test-coref` chains stay deleted (STU-592); the single-stage
dev tools (`test-extraction`/`test-clustering`/`test-relationships`) stay — they
sequence nothing.

## Actual Pipeline Layout

Primary workflow — one Studio run (STU-457):

```bash
studio run wiki-full --input-file <book.yaml> --live    # = make run
```

`wiki-full.pipeline.yaml` call-chains (STU-599) the four pipelines, forwarding
the book yaml as each child's input:
1. `wiki-extraction` — epub-parse, section-filter (pre/call/post), entity-extraction, entity-clustering, split-clusters
2. `wiki-resolution` — chapter-summary, resolve-clusters, relationship-extraction, alias-resolution, alias-adjudication (pre/call/post), entity-classification, write-registry
3. `wiki-preparation` — entity-status/affiliation/species (each pre/call/post), discover-relationships, classify-relationships, build-character-graph, build-event-layer, wiki-preparation
4. `pages-export` — generate-wiki-pages, generate-book-synopsis, generate-event-pages, consolidate-editorial-stance, assemble, copyright-check, wiki-export

Important:
- **Every former run_wiki.py pre-step is a pipeline stage (STU-457).** The
  scripts keep a `--book` argv mode as standalone dev tools; without `--book`
  they read the Studio stdin payload (book yaml in `additional_context`,
  artifacts from disk). A pre-step that "never fails the run" is now a
  `call ... on_failure: continue` (trio) or a stage that exits 0 with a warning
  (discovery with no roster, synopsis with no events).
- `.studio/pipelines/wiki-generation.pipeline.yaml` is deleted (STU-591); the
  four generation scripts are stages of `pages-export`. Restart the generation
  phase with `studio replay <run-id> --restart --stage pages-export`.
- **The LLM loops run natively, not as hand-rolled subprocess loops (STU-589/612).**
  The four fan-outs — `discover-relationships`, `classify-relationships`,
  `chapter-summaries`, `wiki-pages` (`.studio/pipelines/*.pipeline.yaml`) — each own
  a `map` stage `over: input.<items>` dispatching one child run per item; the host
  stage script does one nested `studio run <fan-out-pipeline>` and reads the
  collected results. `section-filter`, `alias-adjudication` and the
  `entity-status`/`affiliation`/`species` trio (STU-457) run as a **pre/call/post
  split** inside their host pipeline (a `*-pre` script, a native `call: *-verdict`
  stage, a `*` post script) — one call per book, no subprocess. Persistence for
  all of these is in **"A Long Run Persists As It Goes"**.
- **A stage declares the files it writes (STU-600).** `expected_outputs.files` in
  `.studio/contracts/*.contract.yaml` names them per *stage*, not per pipeline —
  `splits.json` is written by `split-clusters`, so a missing file fails that stage
  and names it, inside the RALPH loop where the miss enriches retry feedback.
  `run_wiki.py`'s `required_files()`/`check_outputs()` were deleted there; its
  `clean_files()` died with the file in STU-457 (`--clean` returns with STU-597's
  CLI). `chapter_summaries.json` is asserted on the `chapter-summary` stage now
  that the writer is a stage.
- **The `expected_outputs` globs pin the `library/` layout (STU-623).** Every
  `expected_outputs.files` entry is a cwd-relative glob
  (`library/*/*/processing_output/*/<file>`) that hardcodes
  `library/<author>/<series>/`, so a book outside that layout fails its stage's
  output check even when the stage wrote the file — and the error names the glob,
  not the path written (hit while benching STU-457 with the fixture book in a
  scratch dir). Convention, not a kernel fix: contract-checked books live under
  `library/`, and a bench/test/throwaway corpus that must pass the contracts goes
  under `library/_bench/` (gitignored) — two levels down (`library/_bench/<book>/`)
  it still matches `library/*/*/`. The glob is also over-broad the other way — it
  matches *any* book's artifact, so a stale file from book Y satisfies a stage
  running on book X. Closing that needs Studio to template `expected_outputs` from
  the run input (`{{input.file_path}}` → derived paths), a new kernel surface
  deferred until a second corpus location actually exists.
- **Disk is the bus across pipelines (STU-455).** A stage reads an artifact written
  by an *earlier pipeline* from disk, never from Studio's context — those are
  separate `studio run` invocations, so `previous_outputs`/`all_stage_outputs`
  are empty of it by construction. Studio's context is only for stages that
  really do chain in memory inside one pipeline (resolve-clusters →
  relationship-extraction, chapter-summary → wiki-preparation).
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
- [.studio/pipelines/wiki-full.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/wiki-full.pipeline.yaml): the top-level pipeline `make run` invokes (STU-457)
- [scripts/entity_extraction.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_extraction.py): writes per-book `*_full.json`, `chapters.json`
- [scripts/relationship_extraction.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/relationship_extraction.py): co-occurrence graph, optional coref, CLI/live mode
- [scripts/discover_relationships.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/discover_relationships.py): schema-guided typed relation discovery (STU-556), writes `relationships_discovered.json`; pure logic in `wiki_creator/relationship_discovery.py`. One `studio run discover-relationships` per book — the engine fans out one child run per paragraph-aligned chunk (`map` stage, STU-589), and per-item resume (STU-605) replaces the old script-side votes cache (see "A Long Run Persists")
- [scripts/build_character_graph.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/build_character_graph.py): series character graph stage of wiki-preparation, runs after typing (STU-575/457), writes `character_graph.json` + `character_graph_delta.json`; pure logic in `wiki_creator/character_graph.py`
- [scripts/chapter_summary.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/chapter_summary.py): chapter summaries used during preparation
- [scripts/wiki_preparation.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/wiki_preparation.py): batch generation
- [scripts/generate_wiki_pages.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_wiki_pages.py): standalone generation. One `studio run wiki-pages` per book — the engine fans out one child run per planned item call (`map` stage, STU-612/589) via a plan walk → fan-out → replay (the walk records every `wiki-page-item` the generation would dispatch, the map runs them, the replay serves results back keyed on the item input); per-item resume (STU-605) keyed on the rendered prompt + `prompt_fingerprint` + `attempt` (the retry counter that makes a forbidden-name re-roll a real second call rather than a cache replay)
- [scripts/generate_book_synopsis.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_book_synopsis.py): book synopsis page from `events.json` (SP4/STU-482), writes `book_synopsis.json`; pure logic in `wiki_creator/synopsis.py`
- [scripts/generate_event_pages.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_event_pages.py): one `EVENT` page per high-salience event from `events.json` (SP3/STU-481), writes `event_pages.json`; pure logic in `wiki_creator/event_pages.py`
- [scripts/consolidate_editorial_stance.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/consolidate_editorial_stance.py): post-generation editorial-stance consolidation pass (STU-508), writes `editorial_stance_report.json`; pure logic in `wiki_creator/consolidation.py`
- [scripts/entity_status.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_status.py): per-tome character status stage of wiki-preparation (STU-488; pre/call/post split since STU-457, with `entity_status_pre.py`), writes `entity_status.json`; pure logic in `wiki_creator/entity_status.py`
- [scripts/wiki_export.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/wiki_export.py): Markdown -> wikitext
- [scripts/resolve_clusters.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/resolve_clusters.py): resolves NER clusters
- [scripts/alias_resolution.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/alias_resolution.py): conservative PERSON alias merging, runs after resolve-clusters
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
1. `resolve-clusters` + `relationship-extraction` run first (STU-590 removed the
   `merge-entities` passthrough; both read `resolve-clusters` output directly)
2. `alias-resolution` runs after — reads entities from resolve-clusters output (STU-276)
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

Subsystem gotchas moved to nested `CLAUDE.md` files (STU history, measured invariants) — each loads only when you work under that path:

- [`wiki_creator/nlp/CLAUDE.md`](wiki_creator/nlp/CLAUDE.md) — NER: spaCy models, GLiNER, `invented_names`, device placement, extraction config keying
- [`scripts/CLAUDE.md`](scripts/CLAUDE.md) — pipeline stage behavior: parsing/markup, alias resolution & adjudication, entity status/affiliation/species, registry/multi-tome, notability, collation, relationships, character graph, editorial stance/register, taxonomy
- [`.studio/CLAUDE.md`](.studio/CLAUDE.md) — config.yaml / provider & env tiers
- [`tests/fixtures/markup/CLAUDE.md`](tests/fixtures/markup/CLAUDE.md) — markup regression corpus rules

## A Long Run Persists As It Goes, Never All-Or-Nothing

An LLM stage over a book is a long run — tens to hundreds of per-unit calls
(chunks, roster rows, sections), each network-bound and each able to time out.
So **every such stage writes each unit's result to disk the moment it lands, not
at the end**, and re-reads that cache on the next invocation to run only what is
missing. A timeout, a crash, a `Ctrl-C`, or a machine going to sleep mid-run
costs the units in flight, never the hundred already done.

**Where the per-unit cache lives depends on who owns the fan-out (STU-589/612).**
The four flat/nested fan-outs — `discover-relationships`, `classify-relationships`,
`chapter-summaries`, `wiki-pages` — moved the loop into the **engine** (a `map`
stage `over: input.<items>`, `resume: true`, `on_item_failure: collect-all`; each
dispatches one child pipeline per item). Persistence is now the engine's per-item
resume cache, **keyed on the resolved item input** — the item text plus a
`prompt_fingerprint` (STU-560, so a prompt or vocabulary edit re-runs every item),
plus an `attempt` counter on `wiki-pages` (so the forbidden-name retry is a real
second roll, not a replay of the offending output). The script does one
`studio run <fan-out-pipeline>` and reads back `map_output.resumed`; the retired
`save_votes_cache`/`load_votes_cache` (still in `relationship_discovery.py`, but
test-only now) are what this replaced — the canonical shape used to be a
per-chunk lock writing a script-side votes JSON. So `45 chunks | 12 resumed | 0 failed`
is a resume, and a `FAILED` chunk stays uncached and re-runs next pass while the
rest stay done.

`section-filter` and `alias-adjudication` also migrated (STU-589 call half), but as
a **pre/call/post split** in their host pipeline (`wiki-extraction`,
`wiki-resolution`): a `*-pre` script builds the classifier input and decides cache
hit/miss (`needs_verdict`), a native `call: *-verdict` stage invokes the LLM with no
subprocess (`condition:` on the miss, `on_failure: continue` to keep the STU-529/538
keep-everything bias), and a `*` post script parses, applies and **caches the verdict
script-side** (`section_filter.json` / `alias_adjudication.json`). These are one call
per book, not per-item, so their cache stays where it was — the migration removed the
subprocess, not the JSON.

The remaining trio — `entity-status`, `entity-affiliation`, `entity-species` — is
**not migrated**: each still does one `studio run` subprocess per roster row and
keeps its own script-side cache (STU-488/551/574), unchanged until STU-457 folds the
orchestration into Studio.

This is the base principle the caches already documented in Gotchas are each one
instance of — `section-filter`, `alias-adjudication`, `entity-status`,
`entity-affiliation`, `entity-species`, extraction (STU-529/539/488/551/574/560).
Two rules travel with it, and both are load-bearing:

- **The cache is keyed on the inputs that produced it**, never on the book slug
  alone — the roster rows, the prompt fingerprint, a `CACHE_VERSION` when the
  rows are unchanged but the question is not (STU-552). A cache keyed on identity
  instead of inputs replays a verdict made for a different roster or a different
  prompt, silently — that is the STU-497/539 subset-run trap.
- **A per-unit failure fails that unit, never the run.** The stage records the
  failure (a warn, a `classification_error` stamp per STU-562) and keeps going;
  the reader-facing bias on the missing unit is the stage's own safe default
  (keep the section, merge nothing, render `unknown`). Restarting the whole run
  because one call died is the anti-pattern this principle exists to kill.

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
  - **A worktree runs its own `scripts/` against the checkout `pip install -e .` pinned (STU-569).** The editable install records one absolute path for the whole interpreter, so a subprocess (`studio run`, `python scripts/...`) imports `wiki_creator` from *that* tree, not the worktree it was launched from. `make` and the pytest `conftest` prepend the right tree, so those paths are correct by construction; anything else needs `PYTHONPATH=$(pwd)`. `wiki_creator/__init__.py` now fails loudly when the imported package is not the one under the cwd (`WIKI_CREATOR_ALLOW_FOREIGN_CHECKOUT=1` opts out) — the silent case (unchanged signature, changed body, green suite on code the branch never ran) is what this closes.
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
