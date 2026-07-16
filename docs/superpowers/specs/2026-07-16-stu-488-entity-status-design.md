# STU-488 — Entity status per tome (`status` / `death` infobox slots)

Ticket: [STU-488](https://linear.app/studioag/issue/STU-488/multi-livres-55-evolution-perso-and-conflits-inter-tomes)

## What this closes, and what it does not

STU-488 as written covers four things: death, faction change, identity reveal, and
divergent accounts of one event (POV / unreliable narrator). Three of them dissolve
on contact with the code:

* **Identity reveal is already shipped.** STU-539's `alias-adjudication` merges
  Lillian/Celaena by contextual adjudication over the whole PERSON roster.
* **Divergent accounts** are STU-428 (confidence markers) plus the `pov` already
  carried by `chapter_summary_context`. Not an entity state.
* **Faction change** is not a scalar. `FACTION` is an entity type, so "changed
  faction" is a dated edge, not a field — it needs the dated-relationship model,
  which this slice does not build.

This slice extracts **death**, the one axis the ticket's own acceptance test names,
and fills the `status` infobox slot that has been declared and inert since STU-504.

The other three are split out as separate tickets.

### The ticket's premise is false: there is no series page

The ticket says a character who dies in tome 2 must be marked on their *series page*
without erasing their tome 1 role. **There is no series page.** The registry is
per-series (`library/<author>/<series>/registry.json`); the wiki is per-tome
(`library/<author>/<series>/output/<slug>/`).

This is good news, not a gap. Under a per-tome wiki, the page for tome N states the
state at the end of tome N. Brom is alive on tome 1's page and dead on tome 2's, and
"without erasing" is **true by construction** — earlier tomes are never regenerated.
A real aggregated series page would satisfy the ticket's literal wording and conflict
head-on with STU-232 (spoiler-free progression), because it spoils by definition. It
is split out as its own ticket.

Consequence that shrinks this slice to almost nothing: **the series registry does not
carry `status`.** It is a fact of tome N, computed from tome N's text, rendered on
tome N's page. No field on `EntityRecord`, no change to `accumulate`, no new
cross-tome arbitration.

## Vocabulary

The enum follows the fandom-wiki convention (`<data source="status">` /
`<data source="death">` under a `Status` group):

```
alive | deceased | missing | unknown | undead
```

`unknown` is the slot's declared fallback (`base.yaml`, `fallback: unknown`), not an
error case. A rejected verdict and a book that never ran the stage render the same
thing.

Labels are chrome, keyed by language in `base.yaml` and read via `chrome_label` — no
French string literals in `.py` (STU-510).

## Architecture

The fact is consumed at preparation, not resolution: `titles` is computed in
`wiki_preparation.py` while building the batch entity, and `_extracted_fact_value`
reads it back off `entity["titles"]`. `status`/`death` take the same path. The
difference is that ours needs one LLM call, so it is its own script rather than an
inline helper.

```
wiki-resolution                          (unchanged)
  └─ entity-classification → entities with type + importance

PRE_STEPS["wiki-preparation"]            (run_wiki.py)
  ├─ classify_relationships.py           (existing)
  ├─ build_event_layer.py                (existing)
  └─ entity_status.py           ← NEW
       PERSON roster → 1x `studio run entity-status-item`
       → processing_output/<slug>/entity_status.json

wiki_preparation.py
  └─ reads entity_status.json, stamps status/death on the batch entity
     (beside `titles`)

generate_wiki_pages.py::_extracted_fact_value
  └─ token "status"/"death" → entity["status"] / entity["death"]
```

**Why a preparation pre-step and not a `wiki-resolution` stage like
`alias-adjudication`:**

1. `alias-adjudication` sits in resolution because it **changes identity** —
   `entity-classification` reads its output. `status` changes no identity; it only
   decorates the batch entity.
2. Resolution is chained by `make golden`. One more LLM stage there is one more stage
   to exclude. The preparation pre-steps are already outside the golden chain.
3. `generate_wiki_pages.py` is already exactly this shape: a pre-step that shells out
   to `studio run <x>-item`.

Files: pure logic in `wiki_creator/entity_status.py`, runner in
`scripts/entity_status.py`, plus `.studio/{agents,contracts,pipelines}/entity-status-item.*`.
A 1:1 mirror of `alias_adjudication`.

**PERSON only.** `status` is declared on PERSON in `base.yaml`; PLACE/ORG/FACTION have
no such slot. The roster sent to the model is the PERSON roster, like
`alias-adjudication`.

## Snippet selection

This is the part that decides whether it works.
`alias_adjudication.select_snippets` keeps the ≤5 snippets that **name another roster
character** — the right filter for a merge (a snippet naming nobody else can only
confirm the entity exists), useless here. A death snippet often names nobody else.

Two sources of evidence are needed, because the enum asks two different questions:

| Verdict | What proves it | Snippet to show |
|---|---|---|
| `deceased` / `missing` / `undead` | a sentence stating it | snippets carrying a **status marker** |
| `alive` | the character acts late in the book | snippets from the **latest chapters** they appear in |
| `unknown` | nothing | — |

So `select_status_snippets(snippets)` returns ≤5: marker-bearing first, topped up with
the latest.

The marker vocabulary lives in `cue_words/<lang>.json` under `status_markers`; absent
key degrades to an empty collection, per the CLAUDE.md rule (no hardcoded word lists,
no fallback vocabulary constant).

### Why this is not STU-538 again

STU-538 deleted `alias_pattern_templates` after measuring 340 fires and 0 true
positives across the six books with cached extraction. The regex was the verdict: a
match *merged*. Here the regex only **retrieves**, and the model decides.

`die` sits in the context of both Eragon and Brom for the same sentence, and surfaces
it for both. The model reads *"Eragon watched Brom die"* and knows who the subject is.
The word picks the reading; the reading renders the verdict. Subjecthood needs
attribution, which is exactly what STU-538 concluded a regex cannot buy.

The failure direction is also right: a marker missing from the vocabulary means a
death is never retrieved, which means `unknown`. The vocabulary can be poor without
breaking anything — it cannot invent a death.

Budget: `alias_adjudication` fits 38 entities × ≤5 snippets in ~14k tokens. The PERSON
roster is 21–71 across the library; same cap, same order of magnitude, one call.

## Verdict, verification, cache

One row per entity, three fields:

```json
{"name": "Brom", "status": "deceased", "quote": "Brom's chest rose one last time, and then was still."}
```

No chapter field in the reply. Snippets are built from `context_by_chapter`, so each
already knows its `chapter_id`; `death` is derived by code — the chapter of the snippet
containing the quote, rendered via `chapter_number`. The LLM judges, the code formats,
as with every other extracted-fact.

**Three rejection rules, each falling back to `unknown`:**

1. **Name off the roster** → dropped (the model hallucinates characters from its memory
   of the novel).
2. **Quote not verbatim in that entity's own snippets** → dropped. This is STU-539's
   rule unchanged: these novels are in the model's training data, so without the check a
   verdict sourced from its memory of the plot and one sourced from this run's text are
   indistinguishable afterwards. `parse_merge_verdict` already does exactly this; same
   normalization helper.
3. **Status outside the enum** → dropped.

Whole-stage failure paths — missing CLI, timeout, unparseable JSON, empty reply —
**leave the entire roster at `unknown`** and warn. The run never fails.

The asymmetry is STU-539's, not STU-529's. A false `unknown` says "we don't know". A
false `deceased` kills a living character on a page nobody will reread.

**Cache**: `processing_output/<slug>/entity_status.json`, keyed on the roster rows
themselves (`load_cached_merges` / `save_merge_cache`, same shape). `WIKI_MAX_CHAPTERS`
or any upstream extraction fix cannot replay a verdict made for a different roster.
This is the trap STU-539 named: its premise was measured false **because it was measured
against a 5-chapter extraction**, where the reveal has not happened yet. A truncated
roster and a full roster share no verdict.

## Rendering

```yaml
# base.yaml, PERSON.mediawiki source — one added row
| '''Décès''' || {{{death|}}}

# base.yaml, PERSON.infobox — status exists already, death is new
- {token: status, group: infobox, provenance: extracted-fact, obligation: MIN, fallback: unknown, tiers: [figurant, secondary, principal]}
- {token: death,  group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [figurant, secondary, principal]}
```

`death` is `OPT`: most characters do not die, and an absent `OPT` slot is omitted
cleanly by `_bind_batch_fields`. `status` stays `MIN` with its fallback — it renders
`unknown` rather than disappearing, the behaviour declared since STU-504.

`_extracted_fact_value` gains two branches beside `titles`, and its comment
("`status`, `affiliation`, and the specific `type` are future slices") loses `status`.

### `death` renders the chapter, ungated

An earlier draft of this design gated `death` on `editorial_stance` (STU-507), on the
grounds that "Chapter 40" is meta-narrative and contradicts an `in_universe` posture.
That was wrong on three counts:

* The `apparition` slot already renders *"Appears in tome 1, last seen tome 4"*
  (`tome_labels.py`), which is exactly as meta-narrative, and it is **ungated in every
  mode**.
* No book YAML declares `editorial_stance` at all — everything runs on the `hybrid`
  default. `in_universe` is declared nowhere.
* Stance gating today applies to **sections** (`allows_section`) and to the Main_Page
  statistics block (`expose_pipeline_metadata`). There is no infobox-slot gating
  mechanism.

So gating `death` would build a new mechanism, for a mode nobody declares, next to a
slot that already does the same thing ungated. If `in_universe` ever becomes real,
`apparition` and `death` get gated together, in a ticket that has a reason.

### Known limitation: the infobox is not chapter-gated

STU-492 collapses chapter-gated *sections* behind `mw-collapsible` when a book sets
`generation.spoiler.collapse_after_chapter: N`. The infobox is not gated, so a `death`
slot naming chapter 40 would bypass it. **No book declares `collapse_after_chapter`
today**, so this is theoretical; recorded, not designed for.

## Testing

Goldens are out of reach by construction: the golden chain stops at `write-registry`,
and `wiki_preparation` is not in it. `make golden` / `make smoke` stay LLM-free.

Unit tests over the pure logic in `wiki_creator/entity_status.py`:

| Pinned | Why |
|---|---|
| `select_status_snippets` puts marker-bearing snippets first, tops up with the latest, caps at 5 | The whole snippet-selection design |
| A quote not verbatim in **that entity's own** snippets is rejected | The STU-539 rule; without it, the model's memory of the novel passes for text |
| A name off the roster is rejected | Hallucination |
| A status outside the enum is rejected | — |
| Every failure path (missing CLI, timeout, unparseable JSON, empty) leaves the whole roster `unknown` | **The load-bearing test.** This is the asymmetry above; if it breaks, the feature kills living characters |
| `death` is the chapter of the snippet carrying the quote | Deterministic derivation |
| Cache keyed on roster rows: a changed roster misses the cache | The truncated-extraction trap |
| `status_markers` absent from cue_words → empty collection, no marker selection, no crash | CLAUDE.md rule |

Two wiring tests — the STU-512 lesson (*without them the whole feature was deletable
with the suite green*):

1. `wiki_preparation` stamps `status`/`death` onto the batch entity.
2. `_extracted_fact_value` renders the slot from those fields.

### Measurement

STU-538 fired 340 times for 0 true positives and nobody knew for months, because nobody
counted. Here the ground truth is free, unlike STU-537's oracle roster: **we know who
dies**. Eragon has cached extraction, Brom and Garrow die in it, and the rest of the
roster is alive.

So: run the stage on `01_eragon`, check the roster by hand, and report in the MR
description — how many `deceased`, how many real. No `research/` harness, no gold
corpus. If the stage returns `deceased` for anything but Brom and Garrow, that is a
false positive and it is visible by eye. This is not a CI metric; it is the control that
stops us shipping another STU-538.

## Acceptance

A character who dies in tome 2 renders `status: Décédé` and `death: Chapitre N` on their
tome 2 page, and is untouched on their tome 1 page (which is never regenerated). Every
failure path renders `unknown`.

## Split out of this ticket

* Faction change as a dated edge (`affiliation` slot).
* In-universe death circumstance as grounded prose (the STU-481 `## Déroulement` shape),
  rather than an infobox slot.
* An aggregated series page — and its conflict with STU-232.
