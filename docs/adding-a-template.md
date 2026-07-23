# Adding or adapting a page template

Every wiki page is assembled from a **template** declared in
`wiki_creator/templates/base.yaml`. That one file is the single authority for the
entity-type vocabulary, the infobox and section **slots** each type carries, how
each slot is filled, which importance tiers show it, and every reader-facing
label — localized by language. No Python table restates any of this (STU-505), so
most template work is a `base.yaml` edit, not a code change.

This guide covers the common tasks: adapting an existing template (a slot, a
section, a label, a tier), and adding a whole new entity type. Read
`base.yaml` alongside it — the `PERSON` block is the fullest worked example.

## Anatomy of a template

Each entry under `entity_types:` declares one type (`PERSON`, `PLACE`, `ORG`,
`EVENT`, `FACTION`, …) with four parts:

```yaml
PERSON:
  ner_labels: [PER, PERSON]        # NER labels this type absorbs
  gliner_label: person name        # the label the GLiNER backend asks for
  export:                          # presentation routing (subdir, category, infobox template)
    subdir: characters
    infobox_template: Infobox character
    category_default: Personnages
    infobox_source: |- ...         # the MediaWiki infobox template body
  infobox:                         # infobox slots (list of tokens)
    - {token: nom, group: infobox, provenance: batch-bound, obligation: MIN, tiers: [...]}
  sections:                        # prose/fact sections (list of tokens)
    - {token: biography, group: section, provenance: llm-prose, obligation: MIN, tiers: [...]}
```

A **slot** (an entry in `infobox` or `sections`) has these fields:

| Field | Meaning |
| --- | --- |
| `token` | The slot's key. Its reader-facing name comes from `labels:` (localized). |
| `group` | `infobox` or `section`. |
| `provenance` | Where the value comes from — see below. |
| `obligation` | `MIN` (must be present; a `fallback:` renders when empty) or `OPT` (dropped when empty). |
| `tiers` | The importance tiers that show this slot: `figurant`, `secondary`, `principal`. |
| `fallback` | The value rendered when a `MIN` slot has no data (e.g. `unknown`, `none`). |
| `genre_gated` | `true` = only shown for books whose YAML opts in (e.g. `species`, `powers` for fantasy). |

### Provenance — the load-bearing field

`provenance` decides how a slot is filled, and getting it wrong is the classic
mistake:

- **`batch-bound`** — a deterministic fact bound at batch time (name, type,
  first appearance). Always available.
- **`extracted-fact`** — a fact a pipeline stage computes (`status`,
  `affiliation`, `species`, `relationships`). A slot declared `extracted-fact`
  with **nothing computing it is cleared, not invented** — the writer LLM never
  fills it. If you add such a slot, wire the stage that produces it, or it renders
  empty on purpose (STU-551/572).
- **`llm-prose`** — free prose the writer LLM authors (biography, personality),
  grounded against the source excerpts.

Do not declare a slot `llm-prose` to get a fact "for free": prose slots are the
one place ungrounded content can leak, which is what `extracted-fact` clearing
exists to prevent.

## Tasks

### Adapt an infobox slot or section

Edit the slot in the type's `infobox`/`sections` list. To change **who sees it**,
edit `tiers` (a `figurant` page is one short paragraph; drop the slot from that
list to hide it on minor entities). To make it **mandatory**, set
`obligation: MIN` and add a `fallback:`. To make it **fantasy-only**, add
`genre_gated: true`.

If the slot is new and reader-facing, add its label (next task). If it is a new
`extracted-fact`, remember it needs a producing stage.

### Localize a label

Every token rendered on a page gets its display name from `labels:`, keyed by
language:

```yaml
labels:
  status: {en: Status, fr: Statut}
```

Add your language's column to every map that anchors output: `labels`,
`length_by_tier`, `briefs` (per-type, per-section writing instructions), `chrome`
(navigation, spoiler controls, status enum), `stubs`, `validator.errors`,
`language_names`, and the `few_shot` example. A language missing from a map falls
back to nothing — the guide for a **new output language** is
[adding a language](adding-a-language.md); this note is for a template that
introduces a new token needing a label.

> Prompt **scaffolding** (instructions, grounding labels) stays English whatever
> the output language. Only output-anchoring content — section titles, briefs,
> few-shot, the write-in-`<language>` directive — follows the book's
> `output_language`.

### Adapt the rendered infobox

The MediaWiki template body is `export.infobox_source` (a `<includeonly>` wikitext
table). Its `{{{field|}}}` placeholders are populated from the slots; change the
table to change how the infobox renders in the exported wiki. Keep the field names
in step with the slot tokens they display.

### Add a relationship type

Relationship types are declared under `relationships.enum`, not per entity type.
Each carries a `description` (the application criterion injected into the
classifier prompt — English scaffolding), localized `labels`, and optional
`legacy` surface strings mapping old outputs onto the canonical token. Book-specific
types are added via the book YAML `classification.relationship_types` instead
(STU-472) — reach for that before editing the shared enum.

### Add a new entity type

1. Add the type block under `entity_types:` with its `ner_labels`,
   `gliner_label`, `export` routing, and `infobox`/`sections` slots. Copy the
   closest existing type as a starting point.
2. Add the type to the `FROZEN_ENTITY_TYPES` snapshot in `wiki_creator/types.py`
   — `_assert_taxonomy_in_sync` raises at import if the snapshot and `base.yaml`
   disagree, so this keeps them in step.
3. Add labels for any new tokens the type introduces (see above).
4. A generation-only pseudo-type (like `SYNOPSIS`, `COLLATION`) carries no
   `ner_labels` and never enters resolution — declare it with empty `infobox`/
   `sections` if it is body-only.

All consumers read the type through `wiki_creator/entity_taxonomy.py`, so adding a
type touches no other Python.

## Verifying

Template changes are deterministic and covered by the test suite and goldens — no
LLM needed:

```bash
pytest -q
make golden    # rendering/resolution stages vs committed goldens
make smoke     # end-to-end on the committed fixture novella
```

If your change intentionally alters rendered output, regenerate the goldens with
`make golden-update` and review the diff **in the same PR** (see
[CONTRIBUTING.md](../CONTRIBUTING.md#verifying-a-change)). The
`entity-type-declared` and `unique-page-title` validators check that a run only
uses declared types and that no two pages collide, so a type missing from
`base.yaml` fails the run.
