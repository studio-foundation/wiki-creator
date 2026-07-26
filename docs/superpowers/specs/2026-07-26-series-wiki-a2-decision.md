# Series Wiki (A2) — reopen STU-553, one merged wiki per series

Reverses [STU-553](https://linear.app/studioag/issue/STU-553/decide-whether-an-aggregated-series-page-exists-it-conflicts-with-stu)
(`2026-07-17-stu-553-series-page-decision.md`, "no series page").
Parent epic: [STU-233](https://linear.app/studioag/issue/STU-233/support-series-multi-livres-accumulation-entre-tomes-epic).

## Decision

**Ship an aggregated series wiki. It REPLACES the per-tome wikis — one page per
character per series, not a page per character per tome.** This is the Fandom shape:
the ToG wiki has one `Gavriel`, not one per tome. Spoiler safety moves entirely onto
the collapse UI (STU-232's `mw-collapsible`), matching Fandom — the coarse per-tome
gate is given up on purpose.

## Why this reverses STU-553

STU-553 rejected a series page on one load-bearing objection (§5): cost = a second
export pipeline, whose killer was **cross-tome dedup / title collision** — N tomes of
`Gavriel` colliding in one flat MediaWiki namespace, a pass `assemble_wiki_pages.py`
was never asked to run.

That objection costed the wrong shape: a series page **added on top of** the per-tome
wikis (A1). Fandom is not that. Fandom is **one page per character for the whole
series** (A2). Under A2 there is exactly one `Gavriel` page — **the dedup problem does
not exist**, because there is nothing to dedup against. The §5 killer evaporates.

The spoiler objection (§2/§4) is answered by the collapse UI: latest Status shown but
collapsed, per-tome detail in collapsible sections — Fandom's own convention.

## Model — re-derive, never mutate

The series page is a **pure function of every tome's already-persisted artifacts**,
re-rendered whole each run. No read-write/edit wiki tools, no insert-position logic, no
page mutation. This is STU-455 ("disk is the bus") at series scope; the same anti-loader
wiring test discipline applies.

When tome 5 runs, tomes 1-4 are NOT regenerated — and do not need to be: each tome
persists its own contribution to disk under its own slug
(`processing_output/<slug>/{wiki_pages,entity_status,events}.json`, series
`registry.json`). The series-assemble stage reads across all slugs and renders. Re-run
one tome → its `processing_output` is rewritten → next assemble picks it up. Idempotent.

### series-assemble stage (new, series scope)

1. series `registry.json` → canonical identity across tomes (Gavriel-t2 == Gavriel-t3).
2. per canonical character, gather each tome's contribution (that tome's
   `wiki_pages.json[entity]` + `entity_status.json` + events) in reading order
   (`wiki_creator/series.py`).
3. render **one** page:
   - Status scalar = latest tome with a verdict (latest-wins), collapsed by default.
   - one `mw-collapsible` section per tome for role-in-narrative / events
     (STU-232 renderer, tome axis instead of chapter axis).
   - relationships merged across tomes.
4. write to the series export root.

## Genuinely new work (the surviving cost)

- **Series export root** above `output/<slug>/`: Main_Page, index, categories.
- **Cross-tome notability reconciliation**: tome 2 says `Gavriel` minor, tome 5 major →
  one tier rule. Default **latest-wins** (state at furthest reading position), consistent
  with Status. Percentile books (STU-509/513) are deliberately non-comparable across
  tomes — reconciliation operates on the resolved tier, not the raw percentile.
- **Tome-axis collapsible renderer**: extend `wiki_creator/spoiler_blocks.py` from the
  chapter axis to the tome axis.

## Explicitly NOT doing

- Read-write / edit wiki tools. Mutate-in-place reintroduces exactly what the STU-455
  wiring test kills (non-idempotent runs, a stage lying about propagation).
- A1 (series page on top of per-tome pages) — the dedup nightmare STU-553 rightly
  rejected. A2 is not A1.
- Keeping per-tome wikis. One wiki per series; per-tome output is retired for series
  books. (Single-book libraries render as a one-tome series — same code path.)

## Verification

Build is provable LLM-free: assemble logic, notability reconciliation and the tome-axis
renderer are pure logic + goldens on a synthetic 2-tome fixture (`claude:web`). A final
visual acceptance on a real multi-tome series (ToG/Eragon) is a `claude:local`
checkpoint, run by a human — not required to land the logic.
