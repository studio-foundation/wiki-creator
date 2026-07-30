# Adding or adapting a page template

Every wiki page is assembled from a **template** declared in
`wiki_creator/templates/base.yaml`. That one file is the single authority for the
entity-type vocabulary, the infobox and section **slots** each type carries, how
each slot is filled, and which importance tiers show it. No Python table restates
any of this (STU-505), so most template work is a `base.yaml` edit, not a code
change.

`base.yaml` holds **structure only**. Every reader-facing **string** lives in a
per-language **template pack**, `wiki_creator/templates/lang/<code>.yaml`
(STU-732) — so a token you add there needs a label added here. `lang/en.yaml` is
the reference pack: it must hold every key, and resolution is *requested language
→ `en`*.

This guide covers the common tasks: adapting an existing template (a slot, a
section, a label, a tier), and adding a whole new entity type. Read `base.yaml`
and `lang/en.yaml` alongside it — the `PERSON` block is the fullest worked
example.

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
    category_key: persons          # its default [[Category:X]] label lives in the packs
  infobox:                         # infobox slots (list of tokens)
    - {token: nom, group: infobox, provenance: batch-bound, obligation: MIN, tiers: [...]}
  sections:                        # prose/fact sections (list of tokens)
    - {token: biography, group: section, provenance: llm-prose, obligation: MIN, tiers: [...]}
```

A **slot** (an entry in `infobox` or `sections`) has these fields:

| Field | Meaning |
| --- | --- |
| `token` | The slot's key. Its reader-facing name comes from each pack's `labels:`. |
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

Every token rendered on a page gets its display name from the pack's `labels:`
block — one entry per language file, not one map with a column per language:

```yaml
# wiki_creator/templates/lang/en.yaml
labels:
  status: Status
# wiki_creator/templates/lang/fr.yaml
labels:
  status: Statut
```

Add the token to **`lang/en.yaml` first** (it is the reference pack, and
`tests/test_template_packs.py` fails on a key it lacks), then to every other
shipped pack. A token no pack declares renders titlecased, so a book-declared
custom slot needs no pack edit at all.

The blocks a pack carries: `labels`, `chrome` (navigation, spoiler controls,
status enum), `stubs`, `validator_errors`, `briefs` (per-type, per-section writing
instructions), `few_shot`, `category_defaults`, `relationship_labels`,
`sub_role_labels`, `language_name`. The guide for a **new output language** is
[adding a language](adding-a-language.md); this note is for a template that
introduces a new token needing a label.

> Prompt **scaffolding** (instructions, grounding labels, the classifier criteria,
> `length_by_tier`) stays English whatever the output language, and therefore
> stays in `base.yaml`. Only output-anchoring content — section titles, briefs,
> few-shot, the write-in-`<language>` directive — follows the book's
> `output_language`, and that is what a pack holds.

### Adapt the rendered infobox

The MediaWiki template body is **generated** from the type's `infobox` slot tokens
(STU-729): the first token is the header (the name), each remaining token a row
labelled from each pack's `labels:`. There is no hand-kept `infobox_source` to
edit — the template's `{{{token|}}}` parameters ARE the slot tokens, so the
template and the values the renderer emits cannot drift. To change what the
infobox shows, add or remove a slot in `infobox:` (and its label in every pack);
the row follows.

### Add a relationship type

Relationship types are declared under `relationships.enum`, not per entity type.
Each carries a `description` (the application criterion injected into the
classifier prompt — English scaffolding) and optional `legacy` surface strings
mapping old outputs onto the canonical token. Its reader-facing label goes in each
pack's `relationship_labels`. Book-specific
types are added via the book YAML `classification.relationship_types` instead
(STU-472) — reach for that before editing the shared enum.

### Add a new entity type

1. Add the type block under `entity_types:` with its `ner_labels`,
   `gliner_label`, `export` routing, and `infobox`/`sections` slots. Copy the
   closest existing type as a starting point.
2. Add the type to the `FROZEN_ENTITY_TYPES` snapshot in `wiki_creator/types.py`
   — `_assert_taxonomy_in_sync` raises at import if the snapshot and `base.yaml`
   disagree, so this keeps them in step.
3. Add labels for any new tokens the type introduces, plus a
   `category_defaults` entry for the type itself, to every pack (see above).
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
