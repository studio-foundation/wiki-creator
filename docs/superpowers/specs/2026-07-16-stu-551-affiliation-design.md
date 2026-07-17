# STU-551 — Faction as a per-tome scalar (`affiliation` infobox slot)

Ticket: [STU-551](https://linear.app/studioag/issue/STU-551/faction-change-as-a-dated-edge-affiliation-slot)

> **Measured, and closed: B.** The choice between grounding the value on the entity
> roster (A) and reading it free-text from the snippets (B) was left open here because
> the GPU was held by concurrent runs. It has since been measured — see
> *Measurement result* at the bottom, which supersedes *The unresolved choice*. The
> answer is **B**, and the first draft's reasoning for B was wrong even though its
> conclusion was right.

## What this ticket becomes

STU-551 as written asks for a **dated edge**: an affiliation carrying the chapter it
starts and, when the text says so, where it ends. It should not be built. Three
findings, none of them a matter of taste:

**1. The acceptance test is already satisfied by a scalar.** The ticket's own test is
*"a character who changes faction in tome 3 shows the tome 3 faction on the tome 3
page, and the tome 1 faction on the tome 1 page, with neither erasing the other."*
STU-488 established that the wiki is per-tome (`library/<author>/<series>/output/<slug>/`)
while the registry is per-series, and earlier tomes are never regenerated. So a scalar
per tome satisfies the test **by construction** — the same reasoning that shrank
STU-488, and that STU-553 has since confirmed by deciding against an aggregated series
page. The date the ticket wants to preserve is the tome, and the tome is the page.

**2. The intra-tome date is the thing STU-488 measured unbuildable.** STU-488 shipped a
`death` slot deriving the chapter from the snippet its verdict quoted, then removed it:
3 of 4 derived chapters were wrong. Brom dies around chapter 37; his slot read "Chapter
61", where a character *says* he was killed. Morzan and Marian die before the book opens
and have no death chapter at all. **The place where the text states a fact is not the
place where the fact happens.** A dated edge needs a date, and the only date source
available is the snippet that quotes — measured wrong on the sibling slot, for a reason
that transfers verbatim: "Eragon had once ridden with the Empire" dates nothing.

**3. There is no edge to date.** The ticket's premise is that `FACTION` is a first-order
entity type (STU-505), so affiliation is a relationship to another entity. But
[relationship_extraction.py:207](scripts/relationship_extraction.py#L207) filters the
co-occurrence graph to `type == "PERSON"` in hard code. **Zero PERSON↔ORG or
PERSON↔FACTION edges exist in any artifact.** Building one means unfiltering the graph —
a change larger than this ticket, and one STU-536 has opinions about.

So: **`affiliation` is a scalar per tome — the faction the character belongs to at the
end of the tome.** A 1:1 mirror of `status`.

### What this costs, and why the cost is acceptable

A character who switches sides mid-tome renders only their end-state, and the page says
nothing about the switch. That is the same trade `status` makes (Brom is `deceased` on
tome 2's page; the page does not say he was alive for 36 chapters), and it is the
reader-facing convention on every fandom wiki. The prose sections are where an arc is
told; the infobox states a fact. If the switch itself is worth rendering, it is prose —
the STU-481 `## Déroulement` shape, which is where STU-552 sent the death circumstance
for the identical reason.

## Architecture

Pre-step to `wiki-preparation`, beside `entity_status.py`:

```
PRE_STEPS["wiki-preparation"]            (run_wiki.py)
  ├─ classify_relationships.py           (existing)
  ├─ build_event_layer.py                (existing)
  ├─ entity_status.py                    (existing, STU-488)
  └─ entity_affiliation.py      ← NEW
       PERSON roster → 1x `studio run entity-affiliation-item`
       → processing_output/<slug>/entity_affiliation.json

wiki_preparation.py
  └─ reads entity_affiliation.json, stamps `affiliation` on the batch entity
     (beside `titles`, `status`)

generate_wiki_pages.py::_extracted_fact_value
  └─ token "affiliation" → entity["affiliation"]
```

Files: pure logic in `wiki_creator/entity_affiliation.py`, runner in
`scripts/entity_affiliation.py`, plus
`.studio/{agents,contracts,pipelines}/entity-affiliation-item.*`. A 1:1 mirror of
`entity_status`, which is itself a mirror of `alias_adjudication`.

**Why a preparation pre-step** — STU-488's three reasons hold unchanged: it changes no
identity (unlike `alias-adjudication`, which `entity-classification` reads); resolution
is the chain `make golden` runs, so `make golden` / `make smoke` stay LLM-free **by
construction** rather than by mocking; and `generate_wiki_pages.py` is already exactly
this shape.

**PERSON only.** `affiliation` is declared on PERSON in `base.yaml`. The roster sent to
the model is the PERSON roster.

### Why not folded into the `entity-status` call

Same roster, same PERSON entities, same snippet mechanics, one LLM call instead of two —
considered, rejected. **The snippets are the design** (STU-488: *"this is the part that
decides whether it works"*), and the two concerns need different retrievals: `status`
needs marker-bearing **and** latest snippets, `affiliation` needs affiliation-marker
snippets only. Showing the union dilutes both within one budget. Coupling them also
means one unparseable reply loses two independent verdicts, and the cache is keyed on
roster rows that include the snippets — merging changes the key for both. One call per
book per concern, across ~15 books, is not a scaling problem.

## Snippet selection — single source

`status` is two-source because its enum asks two questions: `deceased` is proved by a
sentence saying so, `alive` by the character acting late (a novel never says "Eragon is
alive"). **`affiliation` asks one question.** No sentence proves "no affiliation", so
there is no `alive`-analogue to be proved by lateness. Single source: snippets bearing
an `affiliation_markers` cue, **latest-first**.

Latest-first is what absorbs the intra-tome change without dating it: a character who
joins the Varden in chapter 30 has their latest marker-bearing snippet with the Varden.
State at the end of the tome — the same rule as `status`, for the same reason.

The marker vocabulary lives in `cue_words/<lang>.json` under `affiliation_markers`.
Absent key → empty collection → no snippets → slot omitted. Per the CLAUDE.md rule: no
hardcoded word lists, no fallback vocabulary constant in the `.py`.

**The marker retrieves; it does not decide.** This is the STU-538 line, and it is why
this is not that: STU-538 measured 340 fires and 0 true positives when a pattern *was*
the verdict. "Eragon rode with the Varden against the Empire" carries a marker for two
factions and the model reads which one he belongs to; the regex cannot. A marker missing
from the vocabulary means an affiliation is never retrieved, which means the slot is
omitted — the forgiving direction.

## Verdict, verification, cache

One row per entity, three fields:

```json
{"name": "Eragon", "affiliation": "Varden", "quote": "Eragon had joined the Varden."}
```

**Three rejection rules, each falling back to an omitted slot:**

1. **Name off the roster** → dropped. The model hallucinates characters from its memory
   of the novel.
2. **Quote not verbatim in that entity's own snippets** → dropped. STU-539's rule
   unchanged, reusing `entity_status._normalize` — including its typographic folding.
   That folding is not cosmetic: before `99a6a71`, every STU-488 verdict whose evidence
   sat inside **dialogue** was silently dropped, in a novel, where such facts are
   announced in dialogue. The bug is inherited if the helper is reimplemented instead of
   reused.
3. **The value is not literally in the quote** → dropped. **This is the new rule.**

Rule 3 is what rule 2 alone does not buy. STU-488's value is an enum member, so
verifying the quote verifies the verdict. Here the value is a **name**, so the model can
quote a real sentence and infer the wrong faction from it — inference is the whole risk
surface. Requiring the rendered string to appear in the quote makes the value as
verified as the quote is. *"Eragon rejoignit les Varden"* → `Varden` passes. A quote
that proves membership without naming the faction is dropped, and that is deliberate:
under-recall costs an omitted slot, over-reach puts a character in the wrong army.

Comparison is on the normalized forms, so typographic and whitespace variants match; the
folding is many-to-one on typography only and cannot make an invented name match.

**Every failure path omits the slot** — missing CLI, timeout, unparseable JSON, empty
reply, hallucinated name. `affiliation` is `OPT` with **no declared fallback** (unlike
`status`: `MIN`, `fallback: unknown`), so `_bind_batch_fields` drops it cleanly and
nothing renders. The run never fails.

The asymmetry is STU-539's, not STU-529's: a false affiliation puts a character in the
wrong army on a page nobody will reread, and reads as fact; an absent one says nothing.

**Cache**: `processing_output/<slug>/entity_affiliation.json`, keyed on the roster rows
themselves. `WIKI_MAX_CHAPTERS` or any upstream extraction fix cannot replay a verdict
made for a different roster. This is not hypothetical bookkeeping — STU-539's premise
was measured false **because it was measured against a 5-chapter extraction**, and
STU-560 has just shown the same class of bug at the pipeline level (a completed-run
check that ignored the `ner` config, so three books rendered spaCy-typed entities while
configured for GLiNER).

## Rendering

`_extracted_fact_value` gains one branch beside `titles` and `status`:
token `affiliation` → `entity["affiliation"]`, plain text. Its docstring comment loses
`affiliation` from "future slices".

**No `base.yaml` change.** Both halves already exist, declared and inert:

* [base.yaml:56](wiki_creator/templates/base.yaml#L56) — the slot:
  `{token: affiliation, group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [secondary, principal]}`
* [base.yaml:44](wiki_creator/templates/base.yaml#L44) — the row:
  `| '''Affiliation''' || {{{affiliation|}}}`

**Plain text, no wikilink.** No infobox slot carries a `[[...]]` today —
`make_infobox_call` formats key/value and nothing more; `titles` and `status` are plain
text. Adding link resolution here would be new machinery for one slot, and it is
severable: if the taxonomy is later fixed so that affiliations are reliably entities
with pages, linking becomes a change to the renderer, not to this stage.

## The unresolved choice: where the value comes from

Two candidates. **The choice is deferred to step 1 of the implementation plan**, because
it turns on a measurement the GPU was not free to run.

**A — the value must be a name on the ORG+FACTION roster**
* Grounded in the pipeline's own entities; wikilinkable later without re-extraction.
* Buys the anti-hallucination check for free (name off roster → drop), STU-488's rule 1
  applied to the value as well as the subject.
* Requires that a real faction roster exists. If it does not, the slot renders nothing
  and the feature is a no-op.

**B — free text read from the snippets, verified by rules 2 and 3**
* Independent of the taxonomy: works wherever the text names a faction, entity or not.
* Rule 3 (the value must be in the quote) carries the grounding that A gets from the
  roster.
* Two tomes may name one faction differently (`Varden` / `the Varden`) with nothing to
  reconcile them.

### Why this is open, and what decides it

The measurement that would decide it was taken and is **void**. This design first
measured the ORG/FACTION roster across the three books with a cached extraction and
found: Eragon 0 FACTION with `Varden`/`Empire`/`Urgals` typed ORG beside `Garrow` (a
person), `Utgard` (a place) and `ALFRED A. KNOPF` (the publisher, off the copyright
page); throne-of-glass 0 ORG and 0 FACTION; Narnia 5 FACTION, all of them species
(`Humans`, `Fauns`, `Centaurs`, `Sons of Adam`, `Daughters of Eve`). That reading
condemned A and chose B.

**Those numbers describe STU-560, not the configured
behavior.** `4d0dda9` — *"all three books with an extraction cache were rendering
spaCy-typed entities while configured for GLiNER — Garrow back to ORG, the STU-537 bug
verbatim"* — landed while this design was being written. The three books measured are
exactly those three. Under GLiNER, `FACTION` asks for `"people, race, or order"` and
`Varden` is an order; the roster may be real.

This is precisely the trap this document quotes twice (STU-539's premise, measured false
against a truncated artifact). **Re-measure before choosing.**

The measurement, as step 1 of the plan: re-extract `01_eragon` under GLiNER
(`invented_names: true` is already declared) and read the ORG+FACTION roster.

* If `Varden`/`Empire` type FACTION or ORG cleanly and the junk is gone → **A**, which
  dominates B on grounding and on future linking.
* If the roster is still species-and-noise, or empty on throne-of-glass → **B**.

Rule 3 holds under either. So does everything above it.

**Do not measure on a truncated extraction** (`WIKI_MAX_CHAPTERS`) — a subset answers a
different question, which is how STU-539's premise came to be false. **Read the roster
first, then score**; STU-488's prediction was wrong on both halves before contact with
the artifact.

## Testing

Unit tests over the pure logic in `wiki_creator/entity_affiliation.py`:

| Pinned | Why |
|---|---|
| `select_affiliation_snippets` keeps marker-bearing only, latest-first, caps at 5 | The snippet design; latest-first is what makes the scalar mean "end of tome" |
| A quote not verbatim in **that entity's own** snippets is rejected | STU-539's rule; without it the model's memory of the novel passes for text |
| A value not literally present in its own quote is rejected | **The load-bearing test.** Rule 3 is the only thing standing between a real quote and an inferred faction |
| A name off the roster is rejected | Hallucination |
| Every failure path (missing CLI, timeout, unparseable, empty) omits the slot for the whole roster | The asymmetry; if it breaks, the feature puts characters in the wrong army |
| Cache keyed on roster rows: a changed roster misses the cache | The truncated-extraction trap |
| `affiliation_markers` absent from cue_words → empty collection, no crash | CLAUDE.md rule |
| Typographic quotes in the snippet match a straight-quoted reply | The `99a6a71` regression, inherited if `_normalize` is reimplemented |

Two wiring tests — the STU-512 lesson (*without them the whole feature was deletable
with the suite green*):

1. `wiki_preparation` stamps `affiliation` onto the batch entity.
2. `_extracted_fact_value` renders the slot from that field.

Goldens are out of reach by construction: the golden chain stops at `write-registry` and
`wiki_preparation` is not in it. `make golden` / `make smoke` stay LLM-free.

## Measurement — the ship gate

Run the stage on the books with a cached extraction and report the numbers in the MR. No
`research/` harness, no gold corpus, not a CI metric — the control that stops us shipping
another STU-538, which fired 340 times for 0 true positives and nobody knew for months
because nobody counted.

**Read the roster first, then score.** A prediction written before reading the artifact
is a hypothesis, not a rubric.

**Precision is the metric: 0 false positives or it does not ship** — STU-488's bar.
Under-recall is not a failure; it renders nothing.

One risk to check by hand: on Narnia, `Sons of Adam` / `Daughters of Eve` / `Humans` are
obvious affiliation candidates and they are **species**. A high yield on Narnia is a red
flag, not a success — those values belong to the `species` slot, which is declared and
empty. Narnia has no factions.

## Acceptance

A character who belongs to a faction at the end of tome N renders it on tome N's page.
A character who changes faction in tome 3 renders the tome 3 faction on the tome 3 page
and the tome 1 faction on the tome 1 page — true by construction, since tome 1 is never
regenerated. Every failure path omits the slot.

## Follow-ups this surfaces, all out of scope

* **The taxonomy does not hold factions.** `FACTION`'s `gliner_label` is
  `"people, race, or order"` and collects species; `ORG`'s is
  `"kingdom, empire, or government"` and collects the real factions; the PERSON `species`
  slot is declared and empty while Narnia's FACTION entities are exactly its values. This
  is a real defect with a measurement behind it, and it is the reason choice A is in
  doubt. Its own ticket — and it should be re-measured post-STU-560 first.
* **The studio CLI swallows a stage's stderr.** A python stage that dies at startup
  crashes the node CLI with `Error: write EPIPE` and reports nothing else. Three runs
  during this design reported `EPIPE` where the cause was a one-line `ImportError`.
* **`pip install -e .` pins the main checkout.** Any worktree runs its own `scripts/`
  against `main`'s `wiki_creator/`. Here it failed loudly because STU-560 added a new
  symbol; the silent case — unchanged signature, changed behavior — would let a worktree
  go green while testing `main`'s code. CLAUDE.md mandates a worktree per task and does
  not mention this.
* **GLiNER's device is hardcoded.** [gliner_ner.py:89](wiki_creator/nlp/gliner_ner.py#L89)
  — `device = "cuda" if torch.cuda.is_available() else "cpu"`, no config key, so
  concurrent runs on one 6 GB GPU OOM each other with no way to place them. The same
  shape as the coref device bug.

## Measurement result — the choice is B

Re-extracted `01_eragon` and `01-throne-of-glass` under GLiNER on 2026-07-16, after
STU-560 (`4d0dda9`). `extraction_config.json` confirms the arm:
`{invented_names: true, model: urchade/gliner_large-v2.1, threshold: 0.5}`.

| Book | FACTION | ORG |
|---|---|---|
| `01_eragon` | **10** — `Urgals` 201, `Varden` 144, `Ra'zac` 111, `Riders` 51, `Twins` 11, `Forsworn` 6, `People` 4, `Elves` 4, `Du Vrangr Gata` 4, `Dwarves` 3 | **1** — `Empire` 116 |
| `01-throne-of-glass` | **2** — `Fae` 11, `Champions` 10 | **1** — `King of Adarlan` 5 |

**The pre-STU-560 numbers this design was written on were the bug, and they were wrong
in both directions.** Eragon measured 0 FACTION and 13 ORG (`Varden` and `Empire` typed
ORG beside `Garrow`, `Utgard` and `ALFRED A. KNOPF`). Under GLiNER, Alagaësia's factions
are all there, correctly typed, and every piece of spaCy junk is gone — including
`Garrow`, the STU-537 canonical example. **A was condemned on a false reading.**

**And it still loses, for a reason the first draft never had.** The two books disagree:

* On Eragon the roster is excellent and A would work beautifully.
* On **throne-of-glass** — the Makefile's default `BOOK` — the entire vocabulary is
  `Fae` (a species), `Champions`, and `King of Adarlan`, **which is a person**.
  Celaena's real affiliations (Adarlan, the assassins' guild) are not entities at all.

So A fails on three counts, none of them the one this design originally gave:

1. **The roster is not universal.** A book with no faction entities renders nothing
   under A. That is not a tail case — it is the default book.
2. **A would offer a PERSON as an affiliation candidate.** Priming the model with
   `King of Adarlan` on the default book manufactures the exact false positive the
   whole design guards against.
3. **A's marginal grounding is near zero.** Rule 3 — the value must be verbatim in the
   quote — already does the work A would buy. On Eragon the model quotes `Varden`
   either way; on throne-of-glass, A would *block* `Adarlan`, a legitimate answer that
   happens not to be an entity.

**Decision: B.** Free text from the snippets, verified by rules 2 and 3. The design
above stands unchanged; no fourth rule, no roster in the prompt.

### What this corrects in the sections above

*The unresolved choice* says "if `Varden`/`Empire` type FACTION or ORG cleanly and the
junk is gone → **A**". They do, it is, and the answer is still B — because that rule was
written from Eragon alone and throne-of-glass is the book that decides. **A one-book
measurement is a hypothesis.** This design recorded that lesson twice (STU-539's premise,
STU-488's prediction) and its own decision rule still had it.

Also corrected: *Follow-ups* calls the taxonomy defect "the reason choice A is in doubt".
It is not. On Eragon the taxonomy works — `FACTION` holds real factions and `ORG` holds
the Empire. The defect is narrower than stated: `FACTION`'s `gliner_label`
(`"people, race, or order"`) still admits species (`Elves`, `Dwarves`, `People` on Eragon;
`Fae` on throne-of-glass), and `ORG` mistyped a person on throne-of-glass. Worth its own
ticket, but it does not block this slot, and the Narnia red-flag check in the measurement
section stands.
