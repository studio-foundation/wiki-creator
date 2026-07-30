---
name: compare-providers
description: Set up and score a clean A/B comparison of two LLM providers/models on the same book. Use when the user says "compare providers", "compare les modèles", "A/B mistral vs claude", or wants to know if a quality problem is the pipeline or the model. Prepares caches and scoring; the user launches each run themselves.
---

# compare-providers

The trap this skill exists for (it has already burned one audit): the engine
map-cache (`.studio/runs/map-cache/` — **global, not per-book**) and the five
verdict caches are keyed on item/roster + prompt fingerprint, **not on
provider/model**. A warm run under provider B silently replays provider A's
cached results for every map item and verdict — the "comparison" measures
nothing. And 3/5 suspected "pipeline bugs" of one Alice audit were mistral
generation quality: **re-measure a defect on claude-code before filing it as a
code bug.**

This skill prepares and scores; the runs themselves are paid LLM runs the
**user launches** (CLAUDE.local.md hard rule).

## Protocol

1. **Backup run A's artifacts** (they are about to be overwritten):
   `bak_<DD-MM-YY>_<providerA>/` per the pre-run skill's step 1. If run A does
   not exist yet, do run A first with the same clean-cache procedure.

2. **Record run A's provider mix** — `python scripts/audit_run.py providers`
   plus book YAML overrides — into the comparison notes now, not from memory
   later.

3. **Clear both cache families** so run B pays for its own answers:

   ```bash
   rm -rf .studio/runs/map-cache        # engine per-item resume — ALL books
   rm -f <processing_output>/<slug>/{section_filter,alias_adjudication,entity_status,entity_affiliation,entity_species}.json
   ```

   `make clean` does **not** touch map-cache. Extraction's own cache is
   provider-independent (STU-631) — leave it; it re-runs identically and costs
   no LLM calls. Warn: clearing map-cache also cold-starts every *other*
   book's next run.

4. **Retarget the provider** — `.env` tiers (`STUDIO_BULK_*` for generation,
   `STUDIO_SMART_*` for the five verdict agents, `.studio/CLAUDE.md`) or a book
   YAML override. Change one tier at a time: swapping both generation and
   verdicts in one run confounds the comparison.

5. **Hand run B's command to the user.** Same book, same slice as run A —
   a subset run answers a different question than a full one (STU-497/539), so
   both arms must run the same scope.

6. **Score both arms identically**: validate-wiki-run on each (the audit_log
   gets one entry per arm, `providers` field distinguishing them), then diff —
   GT violations, coverage, weak entities, infobox %, language. Attribute each
   difference to generation vs verdict tier using which stage produced the
   artifact (trace with `audit_run.py trace` when unclear).

## Verdict

Per-metric table A vs B, one paragraph of attribution (which tier explains
which delta), and the recommendation. File issues only for defects that
reproduce on the stronger model — model-quality gaps are config guidance
(`.studio/CLAUDE.md` tier notes), not pipeline bugs.
