---
name: add-stage
description: Add or modify a Studio pipeline stage in wiki-creator — the checklist of load-bearing conventions spread across the repo's CLAUDE.md files. Use when adding a stage/script to a pipeline, converting a subprocess loop to a map or pre/call/post split, or when a new stage's output check / context wiring / persistence is being designed.
---

# add-stage

Every rule here was learned the hard way (the STU is the receipt). Work through
them as a checklist; the verification at the end is LLM-free.

## Files a stage touches

- `.studio/pipelines/<pipeline>.pipeline.yaml` — the stage entry
- `.studio/contracts/<stage>.contract.yaml` — output contract + `expected_outputs.files`
- `.studio/agents/<agent>.agent.yaml` — only if it calls an LLM
- `scripts/<stage>.py` — thin; pure logic in `wiki_creator/<module>.py`
- `tests/test_<module>.py`

## Script conventions

- Reads the Studio payload from **stdin** (`additional_context` = book yaml
  string, `previous_outputs`, `all_stage_outputs`), writes JSON to stdout.
  Keep a `--book` argv mode as a standalone dev tool.
- Paths always derive from the book yaml via `wiki_creator/paths.py` — never
  hand-built.
- **Disk is the bus across pipelines (STU-455).** An artifact from an earlier
  *pipeline* is read from disk, never from Studio context — those are separate
  `studio run` invocations, so `previous_outputs` is empty of it by
  construction. Studio context is only for stages chaining in memory inside one
  pipeline. Never add a `load_*.py` passthrough stage; if you read an artifact
  from disk against a possible in-memory copy, add a wiring test pinning the
  disk read against a contradictory payload
  (`test_main_reads_splits_from_disk_not_from_stage_context` is the model —
  without it a reinstated loader passes the whole suite green).

## Contract

- `expected_outputs.files` names what **this stage** writes, per stage not per
  pipeline, so a missing file fails the right stage inside its RALPH loop
  (STU-600).
- Globs are cwd-relative and pin the two corpus roots:
  `{library,public_domain}/*/*/processing_output/*/<file>` (STU-623). A bench
  book goes under `library/_bench/<book>/` to match. Known limit: the glob
  matches *any* book's artifact, so a stale file from book Y satisfies book X.
- Tool names: dash format in agent YAML (`repo_manager-write_file`), dot format
  in contract YAML (`repo_manager.write_file`).
- Domain rejection (QA says no) is `post_validation.rejection_detection` →
  status `rejected`, not `failed`.

## LLM loop shape — decide, don't default

- **Per-item fan-out** (chunks, planned pages): a `map` stage
  `over: input.<items>`, `resume: true`, `on_item_failure: collect-all`
  (STU-589/612). Persistence = the engine's per-item resume cache, keyed on the
  resolved item input + `prompt_fingerprint` (+ an `attempt` counter when a
  retry must be a real re-roll, as wiki-pages does). The host script does one
  nested `studio run <fan-out-pipeline>` and reads back `map_output.resumed`.
- **One call per book** (a verdict): a pre/call/post split — `*-pre` script
  builds the input and decides cache hit/miss (`needs_verdict`), a native
  `call: *-verdict` stage (`condition:` on the miss, `on_failure: continue`
  when the bias is keep-everything), a post script that parses, applies and
  caches the verdict script-side (section-filter and alias-adjudication are the
  models).
- Never a hand-rolled subprocess loop — that is the shape STU-589/612 removed.

## Persistence rules (both load-bearing)

- **Cache keyed on the inputs that produced it** — roster rows, prompt
  fingerprint, a `CACHE_VERSION` bump when the question changes with unchanged
  rows (STU-552). Keyed on the book slug alone = replays a verdict made for a
  different roster, silently (the STU-497/539 subset-run trap).
- **A per-unit failure fails that unit, never the run.** Record it (warn,
  `classification_error` stamp per STU-562), keep going, safe default on the
  missing unit (keep the section, merge nothing, render `unknown`).

## Config surface

Any new book-YAML key must be answerable by someone who has read the novel and
nothing else — name the property of the book, never the mechanism
(`ner.invented_names`, not `ner.backend`). A threshold nobody can set without
reading our source is a default we have not chosen yet.

## Verify (LLM-free only)

`pytest -q`, `make golden` (chained resolution stages vs goldens), `make smoke`
(e2e on the fixture novella), `mypy wiki_creator/`. A stage-order or YAML
change with no golden/smoke coverage needs one added. No live runs — if the
change genuinely needs one, say so and stop.
