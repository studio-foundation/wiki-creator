# CLAUDE.md

## Project Snapshot

- Repo: `wiki-creator-by-studio`
- Purpose: extract entities from EPUB novels, classify them, generate wiki pages, export wikitext
- Current verified state on 2026-07-21: `pytest -q` => `2009 passed, 1 skipped`
  (skip count depends on which optional models/extras are installed; see `tests/_markers.py`)

## Setup (fresh machine)

- Node.js LTS **≤ 22** (Node 24's V8 headers break `better-sqlite3`'s native
  build) and the Studio CLI: `npm i -g @studio-foundation/cli`. If `studio` is
  missing or resolves to a dangling symlink, check `node --version` /
  `nvm alias default` first — a global install done under a different active
  Node version than your shell defaults to produces exactly that.
- Studio CLI **≥ 0.15.0** — below that, agent-yaml env interpolation
  (`${VAR:-default}`, `.studio/agents/*.agent.yaml`) isn't supported and the
  five whole-book verdict agents silently no-op (`.studio/CLAUDE.md`); 0.15.0
  is also the first version with `batch:` map-stage dispatch and per-call
  token usage (STU-757), which the four BULK fan-outs and `studio status` now
  depend on.
- Python: `pip install -e ".[dev]"` first (test suite), then `".[models]"` (the
  spaCy lg models books declare), `".[gliner]"` (any book with
  `ner.invented_names: true`), `".[coref]"` (any book with `coref: true`) — see
  README Setup for the full extras list; this file only repeats the two most
  common.

## Commands

```bash
pip install -e ".[dev]"      # test suite: carries en_core_web_sm
pip install -e ".[models]"   # to run a book: the lg models the books declare (~1 GB)
pytest -q
mypy wiki_creator/

make run          # studio run wiki-full: the whole build, one Studio run
make run-series
make run-series-wiki   # studio run wiki-series: the series wiki alone (STU-709)
make run-extraction
make run-resolution
make run-preparation
make pages-export
make generate-pages
make generate-pages-dry
make generate-synopsis
make generate-synopsis-dry
make consolidate-stance
make check-wikilinks         # STU-725: assert every [[link]] in output/<book>/ resolves to a page
make check-wikilinks-series  # same over output/_series/
make smoke        # e2e smoke test on the committed fixture novella
make golden       # golden regression run: chained resolution stages vs committed goldens (~2s, no spaCy/LLM)
make golden-update  # regenerate goldens after an INTENTIONAL behavior change, then review the diff

make sync-push    # push this machine's derived artifacts to the rsync hub
make sync-pull    # pull them back
make sync-push-dry / sync-pull-dry   # same, rsync --dry-run, prints the file list
make sync-paths   # print the synced path set
```

`sync-push`/`sync-pull` move the gitignored artifacts that cost real LLM/GPU
time to regenerate — `library/**` and `public_domain/**`
`{processing_output,wiki_inputs,registry.json,character_graph.json}`,
`library/**/output`, and `.studio/runs/` — between machines through a central
rsync hub. `public_domain/**/output` is committed in git, so it is excluded.

The hub comes from the environment, never from the Makefile:

```bash
export WIKI_SYNC_REMOTE=user@pi:/path/to/wiki-creator-sync
```

Unset, both targets fail with that line. Both directions run `rsync -a --update`
and **never** `--delete` — these trees are edited from both machines, so an older
copy can never clobber a newer one, and nothing is ever removed remotely. Paths
are discovered by `find` at run time (a missing `wiki_inputs/` is silent, not an
error) and pushed with full relative paths, so the hub mirrors the repo tree and
a pull restores each file in place. Edit the set in one place: `SYNC_PATHS_CMD`
in the `Makefile`.

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
wiki series run inheritance               # wiki-full over every tome, then wiki-series once
wiki cache clean tog [--llm | --all]      # clear a book's caches (verdicts + map-cache); --all wipes every artifact
wiki replay <run-id> [--stage wiki-resolution]     # studio replay, restart from a boundary
wiki status [run-id]  ·  wiki logs <run-id>        # observability (run-ids feed replay)
wiki cost <run-id> [<run-id> ...]         # per-stage cost report from a run's usage events (STU-758)
wiki <cmd> --dry-run                      # print the studio command(s) instead of running
```

A book resolves from a short query — its slug, series, author, or an explicit
`aliases:` list in the book YAML (`aliases: [tog]` reaches throne-of-glass); an
ambiguous or unknown query lists candidates. `book add` fills only the
mechanical fields; the load-bearing reader-authored ones (`ner.invented_names`,
`notability`, `classification` roles) stay for a human — `--llm` drafts only a
`novel_summary`. `replay`/`status`/`logs` are thin passthroughs to the matching
`studio` command; `cost` is the one exception — it reads `.studio/runs/*.jsonl`
directly (pure aggregation, no `studio` shell-out) and accepts multiple run-ids
so a failed run plus its completing resume merge into one report.
`cache clean <book>` (STU-641) clears a book's caches so a
re-run regenerates instead of replaying: `--llm` (default) removes the five
verdict JSONs plus the global `studio cache clean` map-cache, keeping extraction
— the provider-comparison path (STU-622); `--all` wipes the book's whole
`processing_output`/`wiki_inputs`/`output` too. A full destructive `wiki clean
<alias> --yes` (the `make clean` scope, no explicit book) is still unwrapped.

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
  `04.5_` between `04_` and `05_`) over `studio run wiki-full`, then runs
  `wiki-series` once (STU-709).
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
3. `wiki-preparation` — entity-status/affiliation/species (each pre/call/post), discover-relationships, relation-reconciliation (pre/call/post, STU-754), classify-relationships, build-character-graph, build-event-layer, wiki-preparation
4. `pages-export` — generate-wiki-pages, generate-book-synopsis, generate-event-pages, consolidate-editorial-stance, assemble, copyright-check, wiki-export

A multi-tome series runs a fifth pipeline **once, after the tome loop** (STU-709):

```bash
studio run wiki-series --input-file <any tome.yaml> --live   # = make run-series-wiki
```

`wiki-series.pipeline.yaml` is the arc split (STU-720) plus two stages: a
`series-arc-pre` / `call: series-arc-verdict` pair generating the hub's arc
paragraph through the `wiki-pages` map, then `series-assemble`
(`scripts/series_assemble.py`: every tome's `{wiki_pages,entity_status,events}.json`
from disk, joined on the series registry, plus the hub model and the arc,
into `<series>/series_assembly.json`) and `series-export`
(`scripts/series_export.py`: one merged page per entity + the hub, into
`output/_series/`, a stateless full rebuild). The input is any tome's book yaml —
the series is derived from its path, and language/register/labels come from the
first tome, as the arc pass already does.

The arc **must** be a native `call`, not a nested `studio run` subprocess issued
from inside `series-assemble` — that was STU-709's shape, the last LLM call still
made that way after STU-621, and on a real `wiki series run` it produced no arc at
all while the run stayed green (`arc: null` passes the contract, the hub renders
its deterministic frame, exit 0). `series_assemble.py --series/--book` keeps the
subprocess path as a standalone dev tool.

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
  The five fan-outs — `discover-relationships`, `classify-relationships`,
  `chapter-summaries`, `wiki-pages`, and (since STU-753) `entity-status`/
  `affiliation`/`species` (`.studio/pipelines/*.pipeline.yaml`) — each own a `map`
  stage `over: input.<items>` dispatching one child run per item; the host stage
  script does one nested `studio run <fan-out-pipeline>` and reads the collected
  results. `section-filter` and `alias-adjudication` run as a **pre/call/post
  split** inside their host pipeline (a `*-pre` script, a native `call: *-verdict`
  stage, a `*` post script) — one call per book, no subprocess; the entity trio
  is *also* pre/call/post at the host-pipeline level, but its `call:` target is a
  map fan-out (one agentic call per PERSON, not one call over the whole roster —
  see "Point-Query Verdicts Search The Book" below). Persistence for all of these
  is in **"A Long Run Persists As It Goes"**.
- **A stage declares the files it writes (STU-600).** `expected_outputs.files` in
  `.studio/contracts/*.contract.yaml` names them per *stage*, not per pipeline —
  `splits.json` is written by `split-clusters`, so a missing file fails that stage
  and names it, inside the RALPH loop where the miss enriches retry feedback.
  `run_wiki.py`'s `required_files()`/`check_outputs()` were deleted there; its
  `clean_files()` died with the file in STU-457 (`--clean` returns with STU-597's
  CLI). `chapter_summaries.json` is asserted on the `chapter-summary` stage now
  that the writer is a stage.
- **The `expected_outputs` globs pin the two corpus roots (STU-623).** Every
  `expected_outputs.files` entry is a cwd-relative glob
  (`{library,public_domain}/*/*/processing_output/*/<file>`), so a
  contract-checked book must live two levels under `library/` or under
  `public_domain/` — `<root>/<author>/<series>/`. A book outside both roots fails
  its stage's output check even when the stage wrote the file, and the error names
  the glob, not the path written (hit while benching STU-457 with the fixture book
  in a scratch dir). Convention, not a kernel fix: a bench/test/throwaway corpus
  that must pass the contracts goes under `library/_bench/<book>/` (gitignored) —
  still two levels down, so it matches. The glob is over-broad the other way — it
  matches *any* book's artifact, so a stale file from book Y satisfies a stage
  running on book X. Closing that needs Studio to template `expected_outputs` from
  the run input (`{{input.file_path}}` → derived paths), a kernel surface nobody
  has needed yet.
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

The series wiki is series-scoped, beside the per-tome dirs (STU-705/709):

```text
library/sarah_j_maas/throne-of-glass/series_assembly.json
library/sarah_j_maas/throne-of-glass/output/_series/
```

## Files To Know

- [Makefile](/home/arianeguay/dev/src/wiki-creator-by-studio/Makefile): command entrypoints
- [.studio/pipelines/wiki-full.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/wiki-full.pipeline.yaml): the top-level pipeline `make run` invokes (STU-457)
- [scripts/entity_extraction.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_extraction.py): writes per-book `*_full.json`, `chapters.json`
- [scripts/relationship_extraction.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/relationship_extraction.py): co-occurrence graph, optional coref, CLI/live mode
- [scripts/discover_relationships.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/discover_relationships.py): schema-guided typed relation discovery (STU-556), writes `relationships_discovered.json`; pure logic in `wiki_creator/relationship_discovery.py`. One `studio run discover-relationships` per book — the engine fans out one child run per paragraph-aligned chunk (`map` stage, STU-589), and per-item resume (STU-605) replaces the old script-side votes cache (see "A Long Run Persists")
- [scripts/build_character_graph.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/build_character_graph.py): series character graph stage of wiki-preparation, runs after typing (STU-575/457), writes `character_graph.json` + `character_graph_delta.json`; pure logic in `wiki_creator/character_graph.py`
- [scripts/series_assemble.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/series_assemble.py): `wiki-series` assembly stage (STU-709) — every tome's artifacts read from disk, joined on the series registry, plus the hub model and the arc the `series-arc-verdict` call produced (STU-720); writes `<series>/series_assembly.json`. Pure logic in `wiki_creator/series.py` + `series_hub.py` + `canonicalize.py` (STU-719: cross-tome merge key, generic-role drop, the `link_targets` map the export retargets every tome's `[[link]]` through)
- [scripts/series_export.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/series_export.py): `wiki-series` export stage — renders the assembly into `output/_series/` (one merged page per entity + the hub), stateless full rebuild; pure logic in `wiki_creator/series_pages.py`
- [scripts/chapter_summary.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/chapter_summary.py): chapter summaries used during preparation
- [scripts/wiki_preparation.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/wiki_preparation.py): batch generation
- [scripts/generate_wiki_pages.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_wiki_pages.py): standalone generation. One `studio run wiki-pages` per book — the engine fans out one child run per planned item call (`map` stage, STU-612/589) via a plan walk → fan-out → replay (the walk records every `wiki-page-item` the generation would dispatch, the map runs them, the replay serves results back keyed on the item input); per-item resume (STU-605) keyed on the rendered prompt + `prompt_fingerprint` + `attempt` (the retry counter that makes a forbidden-name re-roll a real second call rather than a cache replay)
- [scripts/generate_book_synopsis.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_book_synopsis.py): book synopsis page from `events.json` (SP4/STU-482), writes `book_synopsis.json`; pure logic in `wiki_creator/synopsis.py`
- [scripts/generate_series_arc.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_series_arc.py): series hub arc paragraph (STU-708) — one LLM call per series grounded on every tome's synopsis + high-salience events + the assembled series characters, writes `library/<author>/<series>/series_arc.json` (cached on the rendered prompt + agent fingerprint); pure logic in `wiki_creator/series_arc.py`. Runs as the `series-arc-pre` / `call: series-arc-verdict` split of `wiki-series` (STU-720, `scripts/series_arc_pre.py`); `--series` stays a standalone dev tool
- [scripts/generate_event_pages.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/generate_event_pages.py): one `EVENT` page per high-salience event from `events.json` (SP3/STU-481), writes `event_pages.json`; pure logic in `wiki_creator/event_pages.py`
- [scripts/consolidate_editorial_stance.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/consolidate_editorial_stance.py): post-generation editorial-stance consolidation pass (STU-508), writes `editorial_stance_report.json`; pure logic in `wiki_creator/consolidation.py`
- [scripts/entity_status.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_status.py): per-tome character status stage of wiki-preparation (STU-488; pre/call/post split since STU-457, with `entity_status_pre.py`; the call fans out one agentic search-and-decide call per PERSON since STU-753, `.studio/pipelines/entity-status-verdicts.pipeline.yaml`), writes `entity_status.json`; pure logic in `wiki_creator/entity_status.py`. `entity_affiliation.py`/`entity_species.py` are the same shape for the `affiliation`/`species` slots (STU-551/574/753)
- [wiki_creator/book_search.py](/home/arianeguay/dev/src/wiki-creator-by-studio/wiki_creator/book_search.py): full-text search over a book's `chapters.json` (STU-753) — the retrieval primitive the entity trio's agents search with instead of receiving a pre-selected snippet pack; `scripts/book_search_tool.py` is its Studio tool-plugin executor (`.studio/tools/book-search.tool.yaml`)
- [scripts/wiki_export.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/wiki_export.py): Markdown -> wikitext
- [scripts/check_wikilinks.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/check_wikilinks.py): wikilink integrity gate (STU-725) over a rendered `.wiki` set (book or `--series`), exits non-zero on a dead link; pure logic in `wiki_creator/wikilinks.py` (`find_dead_links`, book/series scope share it). Intentional red links live in book YAML `export.red_links`
- [scripts/resolve_clusters.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/resolve_clusters.py): resolves NER clusters
- [scripts/alias_resolution.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/alias_resolution.py): conservative PERSON alias merging, runs after resolve-clusters
- [scripts/entity_classification.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_classification.py): classifies entities, reads from alias-resolution output
- [wiki_creator/canonicalize.py](/home/arianeguay/dev/src/wiki-creator-by-studio/wiki_creator/canonicalize.py): the one normalization key (STU-719/724) — `canonical_key` (identity: case/accents/punctuation/spacing + leading article), `canonical_tokens` (comparison: also strips the caller's declared titles), `preferred_display_name`, and two role predicates (`is_bare_role` in-book, `is_generic_role_name` cross-tome). Read by `entity_clustering`, `alias_resolution` and `series.py`; see `scripts/CLAUDE.md`

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

The entity trio — `entity-status`, `entity-affiliation`, `entity-species` — was the
last one-call-per-book verdict left after STU-457; STU-753 moved it to the engine
map shape too, but as a **point-query fan-out**, not a roster sweep: one agentic
call per PERSON entity (name + aliases + `book_dir`, no snippet pack), each with a
`book-search-search_book` tool over `chapters.json` and `tool_calls.minimum: 1`
(anti-theatre — the agent cannot answer without having searched). The per-unit
cache is the engine's, same as the four fan-outs above, keyed on the item input
(name, aliases, book_dir) plus a `prompt_fingerprint` that now covers **both** the
agent's system prompt **and the book's own text** (`studio_io.prompt_fingerprint`
hashing the agent yaml + `chapters.json`) — either changing re-runs every
character, since either can change the answer. The pre stage no longer keeps its
own roster-diff cache to decide `needs_verdict`; the engine's resume already
skips an unchanged item for free. The post stage still writes the same
`entity_status.json` / `entity_affiliation.json` / `entity_species.json` artifact
`wiki_preparation.py` reads, unconditionally rebuilt from the fresh map output on
every run, so downstream is unaffected: see `wiki_creator/roster.py`,
`wiki_creator/book_search.py`, `scripts/book_search_tool.py`,
`.studio/tools/book-search.tool.yaml`.

**Grounding widened, so a name-in-quote gate stands in the old scoping's place.**
The old design's snippet pack was scoped per entity, so a quote lifted from a
different character's evidence failed the check by construction. Free retrieval
searches the whole book, so `is_quoted` alone would accept any real sentence
regardless of who it is about — `roster.quote_names_entity` (the quote must
literally name this entity or one of its aliases) is the mechanical replacement;
the "who the sentence is *about*" ambiguity within a single co-mention sentence
("Eragon watched Brom die" names both) is still the prompt's job, as it always was.

This is the base principle the caches already documented in Gotchas are each one
instance of — `section-filter`, `alias-adjudication`, extraction
(STU-529/539/560), and the entity trio's engine-level resume (STU-488/551/574/753).
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

## A Real Run Snapshots Its Book Before It Overwrites Anything (STU-760)

`epub-parse` — wiki-full's first executing stage, run exactly once per
top-level `studio run wiki-full`/`wiki-extraction` invocation, never as a
map/fan-out item — snapshots the book's `processing_output/<slug>`,
`wiki_inputs/<slug>`, `output/<slug>` and the series `registry.json` to
`bak_<DD-MM-YY>/` (beside them, under the series dir) before doing anything
else, via `wiki_creator.backup.snapshot_book_artifacts`. Idempotent per day (an
existing `bak_<date>/` is never touched) and silent on a cold book (nothing to
snapshot yet).

This is **not** a Studio `on_stage_start` YAML hook, despite the ritual it
replaces being framed that way: Studio 0.15.0's hook commands only substitute
`{{tool.*}}` (`pre_tool_use`/`post_tool_use`) and `{{output.*}}`
(`on_stage_complete`) — `on_stage_start` gets no context at all, and `call`
stages (what `wiki-full`'s own stage list is entirely made of) don't support
`hooks:` in the first place. A plain guard at the top of the first stage
script that *does* receive the book path gives the same "before this run
writes a byte" guarantee without needing a Studio change.

`bak_*/` is gitignored and manually pruned — retention is not automated.
`CLAUDE.local.md`'s manual `mkdir bak_<date>; cp -r ...` ritual still works as
a fallback (e.g. to snapshot before a stage other than epub-parse, or a
whole-series backup), it's just no longer required before a normal run.

A second, genuinely hook-shaped addition rides along: `pages-export`'s last
stage (`wiki-export`) has an `on_stage_complete` hook running `make sync-push`
when `WIKI_SYNC_REMOTE` is set (silently skipped otherwise) — this one needs
no book-specific context, so the hook mechanism fits it fine.

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

- **ALWAYS use a git worktree for every task, no exceptions.** Never work directly
  on `main`, in the main checkout, or on a shared/unrelated branch — every task
  gets its own worktree/branch. This has slipped repeatedly (leftover diffs on
  `main`) — treat it as a hard rule, not a default.
- **Worktrees live under `.worktrees/` in the repo root** (`.worktrees/<slug>`),
  branch named after the issue/task. Sibling-directory worktrees
  (`../wiki-creator-stu-XXX`, `../wiki-creator-worktrees/stu-XXX`) and
  `.claude/worktrees/` are pre-existing drift, not the convention — don't add
  more of those; new worktrees go in `.worktrees/`.
  - **A worktree runs its own `scripts/` against the checkout `pip install -e .` pinned (STU-569).** The editable install records one absolute path for the whole interpreter, so a subprocess (`studio run`, `python scripts/...`) imports `wiki_creator` from *that* tree, not the worktree it was launched from. `make` and the pytest `conftest` prepend the right tree, so those paths are correct by construction; anything else needs `PYTHONPATH=$(pwd)`. `wiki_creator/__init__.py` now fails loudly when the imported package is not the one under the cwd (`WIKI_CREATOR_ALLOW_FOREIGN_CHECKOUT=1` opts out) — the silent case (unchanged signature, changed body, green suite on code the branch never ran) is what this closes.
- **An audit/run that writes to `main` (reads/writes `library/`, `public_domain/`
  output on disk) still ends up producing a diff on `main` by nature of the
  tooling.** When that diff needs a PR: `git stash -u` on `main`, create the
  `.worktrees/<slug>` worktree/branch, `git stash pop` inside it, commit there,
  open the PR from the worktree. `main` never carries the files — stash-and-pop
  is the bridge, not a one-off cleanup step.
- **Iterating on a rule/doc mid-task stays on the same branch and PR.** New
  commits on the existing branch, `git push`, PR updates in place — don't open a
  second PR for a follow-up tweak in the same task. Only fine while the added
  commits stay in scope (doc-only here); unrelated code creep still splits out.
- **A finished task ends with an opened PR, not just a pushed branch.** Once a
  worktree's work is committed and pushed, open the PR as part of finishing the
  task — don't wait to be asked.
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
