# STU-494 · Progression 3/3 — Per-relation French subsections with progression prose

Sub-issue of the narrative-progression epic (STU-232). Follow-up of STU-492
(rendering: per-chapter spoiler blocks + dated relationship index) and reuses the
section-scoped LLM generation pattern of SP1 (STU-479).

## Goal

Restructure the `== Relations ==` section into one `=== [[Name]] ===` subsection
per typed relationship, each carrying **French progression prose** grounded on
that relation's `evolution` / `key_moments` / `evidence`, and each wrapped in its
own `mw-collapsible` block keyed on that relation's reveal chapter — finer gating
than STU-492's whole-section gating.

## Why this wasn't in STU-492

STU-492 is a **rendering** ticket. The rich progression data (`evolution`,
`key_moments`) already exists but is **English** (the `relationship-classifier`
emits those fields in English while the wiki renders French). Surfacing it
verbatim = English text in a French wiki. Producing French per-relation prose =
new LLM calls + per-relation `forbidden_names` handling → a **generation**
feature, out of 2/3's scope. STU-492 shipped a deterministic language-neutral
dated index as a stopgap; this ticket replaces it with the real per-relation
rendering.

## Decisions

| Decision | Choice |
|---|---|
| Relations structure | **Option A** — the section is *only* `=== [[Name]] ===` subsections. The single umbrella LLM prose block **and** the STU-492 dated index are both dropped. |
| Umbrella / intro prose | **None** — straight into subsections (pure Fandom style). |
| Gating key per relation | **`max(chapters)`** — the progression prose describes the whole arc (incl. end-of-arc beats), so gate on the last chapter to avoid leaking the arc's ending when opened early. |
| Collapsible mechanism | **Native `mw-collapsible`** — same as STU-492, no template to publish. |
| Feature flag | **`generation.relations.per_relation_prose: true`** — off/absent ⇒ STU-492 behavior, byte-identical output. |
| Scope | **PERSON only** — the only entity type with typed relationships. |
| Prose grounding | Reformulate `relationship_type` + `evolution` + `key_moments` + `evidence` + `chapters` into French — translate/paraphrase, never copy the English verbatim. |
| Spoiler safety | Per-call `forbidden_names`, same enforcement (check + one retry) as the sectioned path. |
| Studio contract | **Reuse `wiki-page-item`** — per-relation calls go through the existing generation path; no new contract. |

## Architecture

### Generation — `scripts/generate_wiki_pages.py`

When `per_relation_prose` is enabled and the entity is a PERSON with typed
relationships, the `relationships` section is generated as **N per-relation LLM
calls** instead of one section call, inside `_run_generation_sectioned`:

- Each call is scoped to **one** relation. Grounding block = that relation's
  `relationship_type`, `evolution`, `key_moments`, `evidence`, `chapters` (reuse
  `_relationship_evidence_lines`).
- Prompt instructs: **write French prose** (translate/reformulate the English
  grounding — do NOT copy it verbatim), one short paragraph, spoiler-safe.
- Output isolated to the relation's prose, `forbidden_names` checked with one
  retry — same shape as `_generate_one_section`.
- Emits markdown `### [[<other name>]]\n\n<prose>`. No leading umbrella prose.
- The `<other name>` is the pair's other entity (not the page's own entity),
  chosen exactly as in `relationship_index_lines`.

The section content for `relationships` becomes the concatenation of the N
`###` subsections under the `## Relations` heading.

A new prompt builder (or a `per_relation` branch of `build_prompt`) produces the
single-relation prompt; it forbids inventing beyond the grounding and forbids the
English fields verbatim.

### Provenance — `wiki_creator/provenance.py`

New pure function:

```python
def relation_units(entity: dict) -> list[dict]:
    """One {name, revealed_at_chapter} row per typed relationship.

    name = the other entity of the pair; revealed_at_chapter = max(chapters)
    (last chapter of the arc — the gating key). Typed relationships only;
    empty when none.
    """
```

Attached to `page["relation_units"]` at the generation sites that already attach
`content_units`, only when the feature is on and typed relationships exist.

When the feature is on, the `relationships` entry is **excluded** from
`content_units` (fine per-relation gating replaces whole-section gating), so the
export never double-gates the Relations block.

### Rendering — `wiki_creator/spoiler_blocks.py` + `scripts/wiki_export.py`

New pure function in `spoiler_blocks.py`:

```python
def wrap_relation_collapsibles(body: str, relation_units: list[dict], collapse_after: int) -> str
```

- Locate the `== Relations ==` section, split its content on `=== ... ===`
  subheadings.
- For each subsection, match the `[[Name]]` in its heading against
  `relation_units`. If the matched `revealed_at_chapter > collapse_after`, wrap
  the subsection in an `mw-collapsible mw-collapsed` div
  (`data-expandtext="Chapitre {chapter} — révéler"`, `data-collapsetext="Masquer"`).
- Subsections with no match, `None` chapter, or `chapter <= collapse_after` are
  left untouched — same **leave-open** default as STU-492's `wrap_collapsible`,
  absorbing LLM heading drift.
- Matching is by the normalized name inside `[[ ]]`, not order.

`render_page` (`scripts/wiki_export.py`):

- When `page.get("relation_units")` is present:
  - Skip `inject_relationship_index` (the dated index is dropped for these pages).
  - After the existing `wrap_collapsible` (which leaves the un-unit'd Relations
    `==` block untouched), call
    `wrap_relation_collapsibles(body, relation_units, collapse_after)` when
    `collapse_after is not None`.
- When `relation_units` is absent → unchanged STU-492 path (index + section
  gating), byte-identical output.

### md2wiki — no change

`###` markdown subheadings already convert to `===`. Collapsible `<div>`s are
added on wikitext **after** `convert()`, so md2wiki never sees them — same
invariant as STU-492.

## Config

```yaml
generation:
  relations:
    per_relation_prose: true      # off/absent ⇒ STU-492 behavior (byte-identical)
  spoiler:
    collapse_after_chapter: 3     # reused as the per-relation gating threshold
```

Behavior matrix:

| `per_relation_prose` | `collapse_after_chapter` | Rendered Relations section |
|---|---|---|
| off / absent | any | STU-492 unchanged — umbrella prose + dated index, section-level gating |
| on | absent | `=== Name ===` subsections, **no** collapsibles |
| on | N | `=== Name ===` subsections, each gated in its own collapsible keyed on `max(chapters)` |

## Testing

- **Unit `relation_units`**: `max(chapters)` per relation; other-entity name
  chosen; typed relationships only; empty when none; single-chapter relation →
  that chapter.
- **Unit `wrap_relation_collapsibles`**: gates a subsection with
  `chapter > collapse_after`; boundary `== collapse_after` stays open; unmatched
  heading left untouched; `None` chapter untouched; expand/collapse text carries
  the correct chapter.
- **Generation (mock provider)**: with the feature on, the relationships section
  emits one `### [[Name]]` subsection per typed relation; `forbidden_names`
  enforced (retry on hit); no umbrella prose block.
- **Integration `render_page`**: feature on → `===` subsections + per-relation
  collapsibles, no dated index, no chapter `> N` prose outside its block; feature
  off → body byte-identical to STU-492.

## Out of scope

- Non-PERSON entities.
- Regenerating `evolution` / `key_moments` in French at the classifier source —
  the classifier stays English; translation happens at wiki generation.
- Sub-paragraph provenance within a single relation's prose (the whole
  subsection gates on `max(chapters)`).
