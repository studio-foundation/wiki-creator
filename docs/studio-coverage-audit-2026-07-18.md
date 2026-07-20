# Studio Coverage Audit — Wiki Creator — 2026-07-18

> Scope: find what still bypasses Studio. Not a ticket-closing pass.
> Method: grep + read of current code, run-log inspection, four parallel investigators, every
> headline finding re-verified by hand against `.studio/runs/*.jsonl` or the source.
> The 2026-07-11 audit (milestone M4: STU-454, 455, 456, 432, 457) is treated as **stale** — every
> item was re-checked against current code rather than assumed still accurate.

Studio earns its keep on the three `*-item` pipelines (RALPH + groups + `group_feedback`).
Anything else that simulates orchestration, validation, or propagation by hand is a bypass.

---

## Premise corrections (both change the shape of the M4 list)

**STU-454 shipped on the kernel side today** — Done 2026-07-18 01:56, label `repo:studio`,
studio PR #172 *"Add fan-out (map) stage support for parallel sub-pipeline execution"*.
**Zero adoption in wiki-creator**: `rg STU-454` returns nothing, all nine scripts still hand-roll
the loop. Half the ticket landed; the consuming half has no ticket. This was not visible on
2026-07-11.

**STU-432 was never implemented** — Backlog, no commit, no branch. Its four named targets
(`wiki-page`, `entity-classification`, `copyright-check`, `relationship-*`) come from the issue
body, not from code. It was written against **23** contracts; there are **32** today, and the 9
added since (the roster/item stages from STU-488/529/539/551/574) were never in its scope.

---

## 1. `all_stage_outputs` is never populated — three stages are dead in production, all green

Verified by hand in `.studio/runs/2026-07-18T02h20m-wiki-resolution-876aa7ab.jsonl`:

```json
{"event": "stage_context", "stage": "build-character-graph",
 "context_keys": {"input": 1674, "previous_stage_output": 85354}}
```

The engine delivers `input` + `previous_stage_output` only. `previous_stage_output` reaches
scripts as `previous_outputs`, carrying the accumulated map of every upstream stage (sizes are
monotonic across the run: merge-entities 3467 → relationship-extraction 6934 → alias-resolution
65043 bytes). The key `all_stage_outputs`, which four scripts read and three pipeline YAMLs
declare under `context.include`, **is never populated**.

| File:line | Real effect | Evidence |
|---|---|---|
| [build_character_graph.py:73](../scripts/build_character_graph.py#L73) | `all_outputs.get("entity-classification")` with no fallback → `entities=[]`. The stage has emitted `nodes: [], links: []` for its entire life. | Same run: `entity-classification` emits 26 entities / 50 relations; `build-character-graph` emits `{"nodes": [], "links": []}`. `find library -name "*character_graph*"` = **0 files**. 15 runs since 2026-03-25. Three further kills stack behind it: `book_slug` (:81) and `yaml_path` (:93) are keys no book YAML declares, and the disk write is gated on `sgp.exists()` (:96) so it can never create the file the first time. **It starves a live consumer three stages downstream** — see below. |
| [alias_resolution.py:802-804](../scripts/alias_resolution.py#L802-L804) | `relationships` read with no fallback → always `[]` → `_detect_role_symmetric_pairs` never fires, `role_symmetric: 0` on every run. | Verified by hand: entities three lines above (:793-798) *do* have a `previous_outputs` fallback; relationships do not. Not a stage-ordering problem — since STU-539 `relationship-extraction` runs before `alias-resolution`. |
| [split_clusters.py:79](../scripts/split_clusters.py#L79) | `pov_detection` always `null` on disk (5 books checked) — but the golden carries it. | The comment (:76-78) justifies the read for `entity-resolution-PERSON`, a stage that no longer exists. No production consumer of `Splits.pov_detection` exists either. |
| [entity_extraction.py:680](../scripts/entity_extraction.py#L680) | `next(iter(prev_outputs.values()), {})` — positional, not keyed on `"section-filter"`. Correct only by accident. | Latent: if `context.include` gained a stage, insertion order would hand it `epub-parse`'s **untagged** chapters — front matter extracted as narrative, silently. Stages 4 and 5 key by name (:865, :203); this one does not. |

### The `build-character-graph` chain is dark end to end

The broken stage is not an orphan. The full chain:

[build_character_graph.py:95](../scripts/build_character_graph.py#L95) writes
`library/<author>/<series>/character_graph.json` → [wiki_preparation.py:632-636](../scripts/wiki_preparation.py#L632-L636)
reads it back → `build_entity_bundle(graph=…)` → `indirect_relationships` →
[generate_wiki_pages.py:382](../scripts/generate_wiki_pages.py#L382) injects it into the writer
prompt.

The file has never existed, so `_series_graph` stays `None`. The guard is a bare
`if _series_graph_path.exists():` with **no else and no warning** — so `indirect_relationships` is
absent from every bundle ever built, and the whole STU-528 indirect-path feature has never run in
production and has never been measured. Nothing anywhere says so.

**What Studio should do**: fail at load when a script reads, or a pipeline declares, a context key
the engine does not populate — or populate `all_stage_outputs`, since three pipeline YAMLs already
declare it. Today the YAML declares one propagation graph and the engine delivers another, and
nothing errors.

**Why the suite is green**: [test_e2e_golden.py:123-124](../tests/test_e2e_golden.py#L123-L124)
hands every stage **both** `previous_outputs` and `all_stage_outputs`. Any read order looks
correct under test. This is precisely the class the STU-455 wiring test exists to catch, one layer
down — and the wiring test does not cover it.

**Gap**: both sides. The four read fixes are wiki-creator; a lying `context.include` passing green
is a **kernel** gap.

**New.** Covered by neither STU-432 nor STU-457.

---

## 2. Fan-out: nine re-implementations of one loop

STU-454's kernel half is done and unconsumed. What each script hand-rolls:

| Script | Unit | Concurrency | Timeout | Retry | Resume key | Failure isolation |
|---|---|---|---|---|---|---|
| [section_filter.py:47](../scripts/section_filter.py#L47) | all sections, 1 call | — | 300 | none | rows, own cache | keep all sections |
| [alias_adjudication.py:48](../scripts/alias_adjudication.py#L48) | whole roster, 1 call | — | 600 | none | rows, own cache | merge nothing |
| [entity_status.py:88](../scripts/entity_status.py#L88) | whole roster, 1 call | — | 600 | none | `roster.load_cache` + `CACHE_VERSION` | `unknown` |
| [entity_affiliation.py:82](../scripts/entity_affiliation.py#L82) | whole roster, 1 call | — | 600 | none | same | empty |
| [entity_species.py:86](../scripts/entity_species.py#L86) | whole roster, 1 call | — | 600 | none | same | empty |
| [chapter_summary.py:474](../scripts/chapter_summary.py#L474) | chapter | serial | `llm_timeout*4` | none | **output artifact itself** | extractive fallback |
| [generate_wiki_pages.py:952](../scripts/generate_wiki_pages.py#L952) | entity | serial | `timeout*4` | 1 domain retry (spoiler) | **output artifact itself** | `_failed` stub |
| [classify_relationships.py:237](../scripts/classify_relationships.py#L237) | pair | serial | 120 | 2, transient-only | **output artifact itself** | `classification_error` stamp |
| [discover_relationships.py:85](../scripts/discover_relationships.py#L85) | text chunk | **ThreadPool** | 120 | none | dedicated votes file, roster + **prompt fingerprint** | chunk left uncached |

Note the five roster/section stages make **one** `studio run` call for the whole book — they are
not per-item loops. Four are.

Eight of nine re-write the same four-branch error ladder (`FileNotFoundError` / `TimeoutExpired` /
`returncode != 0` / `output is None`). Only the **error vocabulary** is shared — as string
literals, not code. [studio_io.py:190](../wiki_creator/studio_io.py#L190) deduplicates the *reply*
half; nothing deduplicates the *invocation* half (tempfile → `yaml.safe_dump` → subprocess →
ladder → unlink, written out nine times). Only
[generate_wiki_pages.py:1040-1046](../scripts/generate_wiki_pages.py#L1040-L1046) puts the call
behind a seam (`StudioRunner`), and does so for testability, not reuse.

**Sub-defect**: three of the nine use **the output artifact itself** as resume state, so the cache
is not keyed on inputs — a changed prompt or roster silently replays old answers. That violates
the cache-keyed-on-inputs rule CLAUDE.md states, on the three oldest stages. `chapter_summary`
partly patches it (a failed-LLM summary counts as unfinished, :606-633);
`generate_wiki_pages` relies on `--force` being passed by hand.

**Gap**: wiki-creator (adopt the shipped fan-out). The remaining kernel-side want is per-unit
persistence + progress — only `discover_relationships` has a good version of it.

**New** in the sense that the wiki-creator half of STU-454 has no ticket.

---

## 3. Hand-scraping `.studio/runs/*.jsonl` — kernel, root cause measured

Not just `generate_wiki_pages.py`: **all nine** scripts route through
[studio_io.py:190-216](../wiki_creator/studio_io.py#L190-L216) — ~85 lines that regex the run id
out of raw stdout, then open the JSONL log on disk and scan for `stage_complete`. Parsing stdout is
only the fallback.

The comment states the cause ([studio_io.py:201-206](../wiki_creator/studio_io.py#L201-L206)):

> `studio run --json` echoes the whole run — input included — and stdout is cut at 8 KiB
> (STU-533), so a large run's payload never decodes.

And the measurement, `library/c_w_lewis/narnia/audits/audit_log.json:95-97`:

> `studio run --json stdout truncated at exactly 8192 bytes (nondeterministic Node stdout flush
> race)` — evidence: `raw_response byte length == 8192 on all 3 saved artifacts`

Measured cost: **19 Narnia pages generated then discarded** (`audit_log.json:124,126`), plus 5 of 8
books with no adjudication verdict at all (STU-561/STU-564) — the stage warned, merged nothing,
and every pipeline stayed green.

Two distinct CLI defects stack: `--json` echoes the entire run when the caller wants one stage's
output, and stdout is cut at exactly 8192 bytes.

Local aggravator: [studio_io.py:147-148](../wiki_creator/studio_io.py#L147-L148) falls back to
`glob(f"*-{run_id[:8]}.jsonl")` with `matches[-1]` as tie-break — an 8-char prefix glob that can
return **another run's** log.

**What Studio should do**: guarantee untruncated stdout, or expose
`studio run --json --stage-output <name>` returning the requested output directly. **Kernel gap.**
Four wiki-creator test files exist solely for the prosthesis
(`test_studio_run_truncated_stdout_stu533.py`, `test_studio_io.py:85`,
`test_entity_species.py:248`, `test_entity_affiliation.py:224`).

Other reads of `.studio/` internals:

- [discover_relationships.py:57,66](../scripts/discover_relationships.py#L57) hashes
  `.studio/agents/relationship-discovery.agent.yaml` as bytes to fingerprint the prompt for cache
  busting. Legitimate need, fragile means — breaks on a semantics-free YAML reformat. Studio should
  expose an agent fingerprint. Nice-to-have, not a bug.
- `research/ner-eval/build_gold.py:116-121` reads `providers.anthropic.apiKey` out of
  `.studio/config.yaml` as a fallback to the env var. Layer leak, research-only, fixable here:
  require `ANTHROPIC_API_KEY`.

Nothing touches `registry.lock.json` or any other `.studio/` internal.

---

## 4. Passthrough stages that survived STU-455

`load_*.py`: **0 files**. STU-455 closed its own list. Three stages do the same job under other
names.

| Stage | Finding |
|---|---|
| [save_relationships.py:54](../scripts/save_relationships.py#L54) | **Pure passthrough, verified by hand**: `rel_output` in at :30, `rel_output` out at :54, zero transformation. Only real effect is the `json.dump` to `relationships.json`. Its contract requires `relationships` alone — strictly **weaker and redundant** with `relationship-extraction` upstream, which already requires `entities`+`relationships`+`stats` on the same payload. The "keep `assemble_wiki_pages` for its contract" precedent does not transfer. Fold the disk write into `relationship_extraction.py` (the pattern `entity_classification.py:808` already uses). |
| [merge_entities.py:26-33](../scripts/merge_entities.py#L26-L33) | 8-line body; the transformation is two `.get()` and one `isinstance`. Emits exactly `resolve-clusters`' shape (27 entities in, 27 out in the run log). Residual value is the `narrator`-required assertion, which `alias-resolution`'s contract re-asserts one stage later. The `all_stage_outputs` fallback (:38) is dead in production — only tests reach it. |
| [verify_entity_types.py:201](../scripts/verify_entity_types.py#L201) | `enabled = input_data.get("verify_entity_types", False)` — **no book YAML under `library/` declares the key** (only `.studio/inputs/book.input.yaml:13`, unused). No-op across the whole library: re-emits `clusters`+`stats` verbatim plus `type_corrections: []`, 6 lines. The Ollama logic at :129-195 is dead in production. `split_clusters.py:63-66` already falls back to `entity-clustering`, so removal is a YAML-only change. |

`assemble_wiki_pages.py`: **keep** — and its justification is under-sold in CLAUDE.md. Beyond the
`wiki-page` contract's two external validators, the stage **carries the data**:
[copyright_check.py:217](../scripts/copyright_check.py#L217) reads
`previous_outputs["wiki-generation"]["pages"]` with **no disk fallback**, so deleting the stage
yields `pages=[]` → `status: pass, checked_pages: 0` → 0 pages exported, **green**.

**Gap**: wiki-creator. **New** — STU-455 closed the `load_*` shape, not this one.

---

## 5. Contracts — six new beyond STU-432's four

`rg 'validators:|json_schema|tool_calls|post_validation' .studio/contracts/` returns **one hit**:
[wiki-page.contract.yaml:12](../.studio/contracts/wiki-page.contract.yaml#L12). Every other
contract's entire machine-checked surface is `schema.required_fields` — top-level key *presence*,
no type, no nesting, no enum. Three item contracts get real validation from a separate validator
**stage** inside a RALPH group, not from the contract.

New, ranked by capacity to corrupt output:

1. **[build-character-graph.contract.yaml:10-17](../.studio/contracts/build-character-graph.contract.yaml#L10-L17)**
   — worst in the repo. Two node/link schemas, ~15 typed fields, two literal enums, written out as
   comments against `required_fields: [graph, delta]`. This is what lets the stage emit
   `nodes: []` while passing its contract (§1). STU-432 never named it.
2. **[chapter-summary-item.contract.yaml:11](../.studio/contracts/chapter-summary-item.contract.yaml#L11)**
   — a second `"mixed"` phantom. The 2026-07-17 audit caught the one in
   `chapter-summary.contract.yaml`; this duplicate is unrecorded, and
   [types.py:32](../wiki_creator/types.py#L32) declares it too. The value now exists in **three**
   places and no producer emits it.
3. **[write-registry.contract.yaml](../.studio/contracts/write-registry.contract.yaml)** — no
   comment at all, `required_fields: [registry]`, while
   [write_registry.py:110-121](../scripts/write_registry.py#L110-L121) also emits
   `series_registry`, the multi-tome accumulation summary. The whole STU-485 series path has zero
   contractual surface.
4. **[section-filter.contract.yaml:8-10](../.studio/contracts/section-filter.contract.yaml#L8-L10)**
   — the load-bearing invariant ("sections are tagged, never removed: `chapters.json` must stay
   complete", which is what keeps STU-489 mention offsets stable) is prose. A stage that dropped
   sections would satisfy the contract.
5. `verify-entity-types` (:8-9), `wiki-preparation` (:8), `split-clusters` (:8-12) — textbook
   array-of-objects described in a comment, top-level key required.
6. `save-relationships` (4-key passthrough, contract requires 1), `epub-parse` (`language`
   undeclared, `parse_epub.py:406`), `wiki-page-validator` (`error_codes` undeclared,
   `wiki_page_validator.py:26`).

**Inside STU-432's own scope, worth flagging**:
[entity-classification.contract.yaml:11](../.studio/contracts/entity-classification.contract.yaml#L11)
restates the type enum as `PERSON|PLACE|ORG|EVENT|OTHER` — **`FACTION` is missing**, first-order
since STU-505. This is the exact drift `wiki-page.contract.yaml:8-9` warns about in prose:
*"Restating it here is how it drifted last time — the enum that stood here claimed
PERSON|PLACE|ORG long after EVENT shipped."* Same mistake, one file over, one entity type later.
`wiki-page` fixed it by reading `base.yaml` at runtime through `validators:`;
`entity-classification` still restates. Also undeclared there: the producer emits `stats` and
`narrator` (`entity_classification.py:790-795`).

**Do not "fix"**: the five item/roster contracts (`alias-adjudication-item`, `entity-status-item`,
`entity-affiliation-item`, `entity-species-item`, `section-filter-item`) describe nested shape in
comments **deliberately**, and each says so — a hallucinated verdict must not fail the run, it must
render nothing. Hardening them into schema checks would invert the STU-538/539 fail-safe bias.
`split-clusters.contract.yaml:10-11` likewise refuses to name the type vocabulary on purpose,
citing STU-505.

---

## 6. Orchestration outside Studio, beyond `run_wiki.py`

**Already covered by STU-457**: `.wiki_runs/` state file, skip-on-`completed`, `--retries 3`,
restart/clean, the 11 uncontracted `PRE_STEPS`.

New:

- **[run_wiki.py:31-52,153-155](../run_wiki.py#L31-L52) `required_files()`** — a **structural**
  gap, not laziness. STU-455 made disk the bus between pipelines; a contract validates a stage's
  *stdout*, while the artifact that matters is written to `processing_output/` as a side effect.
  Studio is **blind by design** to what `check_outputs` verifies. Fixable here only by making every
  stage echo its artifact — which STU-455 explicitly rejected. **Kernel need**: a contract clause
  asserting files on disk, e.g. `output_files.required: [...]`. This is the one finding that
  genuinely requires a new kernel feature, and it is a premise of STU-457 rather than a ticket.
- **[relationship_extraction.py:981-1062](../scripts/relationship_extraction.py#L981-L1062)** — a
  second retry layer (`_CLASSIFIER_MAX_ATTEMPTS = 2`) stacked on RALPH's `max_attempts: 3`. The
  docstring (:1033) acknowledges it: RALPH catches an off-schema *agent output*, this catches a
  killed *subprocess*. Legitimate, but it exists **only because the fan-out is a subprocess** —
  it disappears when STU-454 is adopted.
- **Two Studio stages launch Studio inside themselves**:
  [section_filter.py:49](../scripts/section_filter.py#L49) (a `wiki-extraction` stage) and
  [alias_adjudication.py:50](../scripts/alias_adjudication.py#L50) (a `wiki-resolution` stage)
  make a nested `studio run`, write their own cache, and `section_filter` also rewrites
  `epub_data.json` **in place** on top of emitting it on stdout. Manual nested fan-out — direct
  STU-454 target.
- **The Makefile is a third sequencing authority.** `make run-generation` is a divergent copy of
  `PRE_STEPS["wiki-generation"]` ([run_wiki.py:103-108](../run_wiki.py#L103-L108)) that **skips the
  `wiki-generation` pipeline entirely** and goes straight to `pages-export`. `CLEAN ?= --clean` is
  **on by default** in the Makefile: the `make` front door silently deletes artifacts where the
  `run_wiki.py` front door does not. `make test*` chains `entity_clustering` +
  `relationship_extraction` directly, bypassing both Studio and `run_wiki.py`.
- **Double execution confirmed independently**: [run_wiki.py:28](../run_wiki.py#L28) keeps
  `wiki-generation` as pipeline #4, so `chapter_summary` / `wiki_preparation` / `assemble` /
  `copyright-check` / `wiki-export` each run **twice** per `make run`. Already in the 2026-07-17
  audit; still open.

---

## Summary — candidates, in order

| # | Bypass | Side | Covered? |
|---|---|---|---|
| 1 | `all_stage_outputs` never populated — 3 stages dead and green, incl. `build-character-graph` which has never produced a graph | wiki-creator (4 reads) + kernel (a lying `context.include` must fail) | **no** |
| 2 | Adopt the shipped STU-454 fan-out — 9 hand-rolled loops, 3 with a cache not keyed on inputs | wiki-creator | half (STU-454 is `repo:studio`) |
| 3 | `studio run --json` 8192-byte truncation → 85 lines of JSONL scraping + 4 test files | **kernel** | no (STU-533/561/564 treat symptoms) |
| 4 | Contract clause asserting files on disk (direct consequence of STU-455) | **kernel** | premise of STU-457, not ticketed |
| 5 | 3 surviving passthrough stages (`save-relationships`, `merge-entities`, `verify-entity-types`) | wiki-creator | no |
| 6 | 6 comment-documented contracts + `FACTION` missing from the restated enum | wiki-creator | STU-432 partially (4/32, written against 23) |
| 7 | Makefile as third authority + `--clean` by default + `wiki-generation` double run | wiki-creator | STU-457 partially |

## Decisions taken (2026-07-18)

**`build-character-graph` is repaired, not deleted.** The deciding fact is not the feature's value
— it is that the current state is the worst of the three options: the code claims the feature
exists, nobody can judge it, and nothing reports its absence. Repair covers four lines
(`all_stage_outputs` → `previous_outputs` fallback at :73, `book_slug` :81, `yaml_path` :93, the
`sgp.exists()` gate at :96 that prevents first creation), plus turning
`wiki_preparation.py:634`'s silent `if exists()` into an explicit warning. Then measure
`indirect_relationships` on one book before letting it run across the library. If it does not
improve pages, deleting it afterwards is a *measured* reject in the STU-468/538 tradition rather
than an unexamined abandonment.

Note the repair cannot be judged by `pytest`: the golden harness hands every stage both context
keys, so the suite is green before and after. The proof is a real run plus a non-empty
`find library -name character_graph.json`.

**`wiki-generation.pipeline.yaml` is deleted.** No argument for keeping it survives "it executes
`wiki_preparation` twice per `make run`". The `--restart wiki-generation` entry point is not lost
in substance — `--restart` accepts any name in `PIPELINES`.

The risk flagged before deciding is **cleared**: `pages-export.pipeline.yaml` declares its own
stage literally named `wiki-generation` (running `assemble_wiki_pages.py`), so
`copyright_check.py:217`'s `previous.get("wiki-generation")` resolves inside `pages-export` and
does not depend on the deleted pipeline. The name collision is historical, and worth renaming
separately.

Deletion is four coordinated edits, not one:

1. `run_wiki.py:28` — drop `"wiki-generation"` from `PIPELINES`.
2. `run_wiki.py:103-108` — move `PRE_STEPS["wiki-generation"]`'s four scripts
   (`generate_wiki_pages`, `generate_book_synopsis`, `generate_event_pages`,
   `consolidate_editorial_stance`) onto `"pages-export"`. This makes `run_wiki.py` and
   `Makefile:99` converge on the same graph for the first time.
3. `run_wiki.py:44-46` and `:79-81` — move the `wiki_pages.json` assertion from the
   `"wiki-generation"` key of `required_files()` / `clean_files()` onto `"pages-export"`, which is
   `[]` today. **A naive deletion silently drops the only check that `wiki_pages.json` exists.**
4. `CLAUDE.md:54` — the line describing the pipeline as still existing, and `:1180`'s
   "last `wiki-generation` pre-step" phrasing.

Cross-cutting test gap worth its own line: the golden chain hands every stage **both** context
keys, so it cannot see finding #1 at all. A wiring test that opposes `previous_outputs` to
`all_stage_outputs` — the STU-455 shape one layer down — is what would have caught
`build-character-graph` fifteen runs ago.
