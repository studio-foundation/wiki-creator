# Wiki Page Templates — Design (reshape keystone)

**Date:** 2026-07-10
**Status:** Design approved, pending user review of this doc
**Related Linear:** STU-436 (slice B), STU-318 / STU-319 (prior targeted fixes)

## Context

An audit of the `01-throne-of-glass` run surfaced a foundational problem, not a
set of patchable bugs. Observed in `processing_output/01-throne-of-glass/`:

- `events_full.json` = **0 events**, `orgs_full.json` = **0 orgs** — two entire
  entity categories empty, despite the book having a central tournament event and
  multiple organizations (Assassins Guild, Adarlan's court, Eyllwe rebels).
- `places_full.json` = **2 entries, both wrong** — e.g. `entity_015` typed `PLACE`
  with `raw_mentions: ["Arobynn Hamel"]` (a person). Real places (Endovier,
  Rifthold, the glass castle, Adarlan, Terrasen, Erilea) are absent.
- `persons_full.json` = **25 entries, heavily fragmented** — `Celaena Sardothien`
  and `Celaena` are separate; `Chaol Westfall` / `Captain Westfall` / `Chaol` are
  three entries for one man; `Wyrdmarks` (a magic script) and likely `Nothung`
  (a sword) typed as persons.
- The file is **227 KB of verbatim source text** stored as `mentions_by_chapter` —
  the pipeline hoards spans, not facts.
- `relationships_classified.json` — `stats.classified: 0` (stale/wrong), ~54% of
  105 relationships unclassified (`None`/`null`), classified labels in **French**
  for an **English** book (`employeur/employé`, `antagoniste`), and relationships
  are pure co-occurrence (proximity, not verified relation).
- `chapter_summaries.json` — many chapters have a single bullet that paraphrases
  the opening sentence rather than summarizing.

## Diagnosis

The pipeline is **source-oriented** (bottom-up: NER → mentions → co-occurrence →
classification). Each stage inherits the noise of the one below, and nothing is
**pulled by the shape of the final wiki page**. A wiki page is **fact-oriented**
(typed attributes: affiliation, status, titles, arc). There is an impedance
mismatch: the pipeline produces `mentions_by_chapter` (spans); the page needs
`affiliation`, `status`, `titles` (facts). Most infobox slots have **no data
source at all** — which is why they come out empty or hallucinated.

The reshape: **templates pull extraction.** Each slot the template declares
becomes an extraction target. Empty/wrong categories stop being silent gaps and
become unsatisfied contract lines — visible, prioritizable work.

## What already exists

This is **not greenfield**. The book yaml already carries a tier→sections
skeleton consumed by `scripts/generate_wiki_pages.py`:

```yaml
principal:
  sections: [infobox, biography, personality, physical, powers, relationships, trivia, references]
  sections_by_type:
    PLACE: [infobox, biography, physical, relationships, trivia, references]
    ORG:   [infobox, biography, relationships, references]
    EVENT: [infobox, biography, relationships, references]
secondary:
  sections: [infobox, biography, relationships, references]
figurant:
  sections: [infobox, biography]
```

`EVENT` is already a first-class type with a section list, and
`entity_extraction.py` has a full EVENT classifier (lines ~398-468). Yet
`events_full.json` is empty. **EVENT is not a design gap — it is a detection
failure** (slice D). The template design is already type-complete.

What the existing config **lacks**:

1. **Provenance** — sections/fields are opaque names with no notion of *who fills
   them*.
2. **Field-level infobox** — `infobox` is a single opaque token; the code cannot
   know which fields to bind deterministically (this is exactly where STU-436
   lives).

## The template model

Every slot is described by **three orthogonal axes**:

1. **Canonical token** — `status`, `affiliation`, `biography`, … Language-neutral.
   Rendered to a display string via a `labels[lang]` table.
2. **Obligation × tier** — `MIN` (mandatory even at figurant) / `OPT` (conditional
   on tier and on data availability), resolved against the existing
   figurant/secondary/principal tiers.
3. **Provenance** — the keystone addition:
   - `batch-bound` — filled by **code** from the batch entity (nom, alias, type).
     The LLM never authors these, so identity confusion is structurally
     impossible for this class (this is STU-436's mechanism, generalized).
   - `extracted-fact` — the pipeline **must produce** the value (status,
     affiliation, titles, family). Empty ⇒ visible unsatisfied contract line.
   - `llm-prose` — descriptive prose (biography, personality), generated
     section-scoped to shrink the error surface.

### Canonical tokens + per-language rendering

The template stores tokens; a `labels[lang]` table renders them. `output_language`
is a **per-book** setting (independent of the source `language`). Consequence:
`relationship_type` must become a **canonical enum** (`antagonist`, `family`,
`mentor`, `ally`, `romance`, …), not free French text. The classifier emits the
enum; rendering picks `antagoniste`/`antagonist` by language. This fixes the
"French labels for English book" bug and makes the whole product localizable.

### Fully per-book configurable

Novel wikis do not share a field set (fantasy → `powers`/`species`; crime →
`occupation`/`alibi`; One Piece → `bounty`). Therefore:

- A **base default template** provides sensible fields per entity type (DRY).
- The **book yaml overrides/extends** it freely: add, remove, rename fields;
  gate optional sections by genre; set `output_language`; override labels.
- **Provenance is declared inline** on every field wherever it is defined — it is
  a property of the field, not of the config level.

### Worked example — PERSON infobox

Today `infobox` is one opaque token. Under the reshape:

```yaml
PERSON:
  infobox:
    - {token: nom,         provenance: batch-bound,    obligation: MIN}
    - {token: type,        provenance: batch-bound,    obligation: MIN}
    - {token: alias,       provenance: batch-bound,    obligation: OPT}
    - {token: status,      provenance: extracted-fact, obligation: MIN, fallback: unknown}
    - {token: species,     provenance: extracted-fact, obligation: OPT, genre_gated: true}
    - {token: affiliation, provenance: extracted-fact, obligation: OPT}
    - {token: titles,      provenance: extracted-fact, obligation: OPT}
  sections:
    - {token: biography,   provenance: llm-prose,      obligation: MIN}
    - {token: relationships, provenance: extracted-fact, obligation: OPT}  # non-empty only
    - {token: personality, provenance: llm-prose,      obligation: OPT}    # principal
    - {token: physical,    provenance: llm-prose,      obligation: OPT}    # principal
    - {token: powers,      provenance: llm-prose,      obligation: OPT, genre_gated: true}
    - {token: trivia,      provenance: llm-prose,      obligation: OPT}
    - {token: references,  provenance: extracted-fact, obligation: MIN}    # >= 1 anchor
```

## Cross-cutting rules

The four authoring rules (zero empty section, cross-links `[[canonical_name]]`,
narrator attribution when `narrator.reliability` is unreliable/partial, strict
paraphrase ≤ 2-3 consecutive source sentences) **reference** INV-WC-01 /
INV-WC-02 and live in the writer's invariants/skill, **not** in the schema. The
schema declares *which* slots exist; the invariants govern *how* they are filled.
Clean separation.

## The "decorticate everything" question, answered

The 227 KB of `mentions_by_chapter` verbatim text is **not waste** — it is the
evidence store backing the `references` MIN slot (chapter-anchored citations).
The correct conclusion is not "stop decorticating" but **"demote decorticage from
product to citation backbone."** The product is the typed template slots.

## Decomposition into slices

Provenance is the organizer: each slot's provenance tag routes it to a slice.

| Slice | Scope | Provenance targeted | Depends on |
|---|---|---|---|
| **A** (this spec) | Template schema: field-level structure, provenance tags, canonical tokens + labels, base-default + per-book override, relationship enum | *defines the 3 classes* | — |
| **B** (STU-436) | Bind `batch-bound` fields by code (nom/alias/type); LLM authors prose only | `batch-bound` | A |
| **C** | Extraction for factual infobox slots (status, affiliation, titles, family) | `extracted-fact` | A |
| **D** | Fix empty/wrong types: EVENT detection, PLACE mistyping (Arobynn≠place), org population | `extracted-fact` (types) | A, C |
| **E** | Section-scoped `llm-prose` generation (biography/personality per section) | `llm-prose` | A |

**Order:** A first (spine — nothing holds without it), then B (small, ships value
immediately, kills identity confusion), then C/D (the extraction bulk), E last.

## Dependencies & risks

- **Alias resolution** — `batch-bound` nom is only as good as the resolved
  `canonical_name`; fragmented entities (Celaena/Celaena) are upstream of the
  template and must be handled by alias-resolution, not papered over here.
- **Relationship classification** — must emit the canonical enum and bucket into
  the template's relation rows; ~54% currently unclassified.
- **Narrator detection** — the attribution rule needs `narrator` populated
  (currently `None`; STU-426 recently merged POV propagation).

## Testing strategy (for slice A)

- Schema validation: every field declares a valid provenance; MIN
  `extracted-fact` fields declare a `fallback`.
- Base-default + per-book override merge: add/remove/rename resolves correctly.
- Label rendering: token → `labels[lang]` for each configured `output_language`.
- Round-trip: existing `sections`/`sections_by_type` book configs still resolve
  (backward compatibility with the flat form).

## Out of scope (for this spec)

Implementation of B-E. Each gets its own spec → plan → implementation cycle. This
doc fixes the keystone (A) and the decomposition only.
