# Wiki Page Templates — Slice C Design (extracted-fact: titles)

**Date:** 2026-07-11
**Status:** Design approved (conversation), pending spec review
**Depends on:** slice A (template schema, merged PR #52), slice B (infobox binder, merged PR #53)
**Reshape context:** A (schema) → B (batch-bound binding) → **C (extracted-fact: titles)** → D (missing entity types) → E (section-scoped prose)

## Context

Slice A tagged each infobox slot with a provenance class. Slice B bound the
`batch-bound` slots (`nom`, `alias`). Slice C is the first `extracted-fact` slot:
the pipeline must *produce* the value, then the binder fills it.

A flow audit (`docs/flow-audit.md`, verified against current code) confirmed there
is **no per-entity fact extraction** in the pipeline: the batch bundle carries
canonical_name, type, importance, aliases, relationships, and chapter summaries —
but no factual attributes (status, affiliation, titles). Of those, **titles are
deterministically derivable** from the entity's own name variants: `role_words`
in `cue_words/<lang>.json` (`captain, king, prince, duke, lady, lord, sir,
assassin, champion, …`) already appear in the resolved aliases (`Captain Westfall`,
`Duke Perrington`, `Crown Prince`). So titles need **no LLM and no new
vocabulary** — a pure deterministic pass.

`status` (needs fate detection) and `affiliation` (needs ORG links, which are
empty until slice D) are deferred.

## Goal

1. Deterministically extract role-word **titles** per entity from its name
   variants, using `role_words` from cue_words.
2. Inject `titles` into the batch bundle (`build_entity_bundle`).
3. Extend the slice-B infobox binder to fill `extracted-fact` slots (`titles`)
   from the bundle, using the same provenance-driven mechanism.

Out of scope: `status`, `affiliation`, and the specific `type` (later slices);
any LLM extraction; scanning full prose contexts for titles (aliases + mentions
are the high-precision signal).

## Design

### 1. `wiki_creator/facts.py` — deterministic title extraction

```
extract_titles(name_variants: Iterable[str], role_words: list[str]) -> list[str]
```

- Lower-cases `role_words` into a set. For each name variant, tokenizes on word
  boundaries and collects any token that is a role word.
- Returns unique, **title-cased** titles in first-seen order
  (`["Captain"]`, `["Assassin", "Champion"]`).
- Degrades gracefully: empty/missing `role_words` → `[]` (honors the CLAUDE.md
  invariant — no hardcoded vocabulary; the list is passed in from cue_words).
- New module because it is the home for the growing extracted-fact family
  (status/affiliation extractors will join it in later slices).

### 2. Bundle injection — `scripts/wiki_preparation.py`

- `build_entity_bundle(...)` gains a `role_words: list[str] | None = None`
  parameter and adds one field to the bundle:
  `"titles": extract_titles([canonical_name, *aliases, *raw_mentions], role_words)`.
- `main()` loads the list once from the book language and threads it:
  `role_words = load_lang_config(book_language(ctx)).get("role_words", [])`,
  where `ctx = yaml.safe_load(payload["additional_context"])` (same source the
  path helper already uses). Passed as `role_words=role_words` into each
  `build_entity_bundle(...)` call in the `entity_bundles` comprehension.

### 3. Binder generalization — `scripts/generate_wiki_pages.py`

- New helper:
  ```
  _extracted_fact_value(entity: dict, token: str) -> str | None
      titles -> ", ".join(entity["titles"])  (None if empty/absent)
      (status, affiliation, specific type -> None; future slices)
  ```
- Extend the existing `_bind_batch_fields(page, entity, book_config)` to dispatch
  by provenance instead of skipping non-batch-bound slots:
  ```
  for slot in resolved.infobox():
      if slot.provenance == "batch-bound":
          value = _batch_bound_value(entity, slot.token)
      elif slot.provenance == "extracted-fact":
          value = _extracted_fact_value(entity, slot.token)
      else:                       # llm-prose → the LLM authors it
          continue
      if value:
          page["infobox_fields"][slot.token] = value
  ```
- The function **name is kept** (`_bind_batch_fields`) to avoid churning slice B's
  merged tests; its docstring is updated to state it binds all
  pipeline-sourced (`batch-bound` + `extracted-fact`) infobox tokens.

**Provenance semantics.** An `extracted-fact` slot binds like `batch-bound` — when
the pipeline produced a value it is authoritative and overwrites the LLM's — but
it is OPT: absent (the common case today) → skipped → the row is omitted (or left
to whatever the LLM wrote, which the grounding/forbidden guards still police).

## Files

- Create: `wiki_creator/facts.py`
- Modify: `scripts/wiki_preparation.py` (`build_entity_bundle` param + field; `main` threading)
- Modify: `scripts/generate_wiki_pages.py` (`_extracted_fact_value`; extend `_bind_batch_fields` + docstring)
- Modify: `wiki_creator/templates/base.yaml` — widen PERSON `titles` from
  `tiers: [principal]` to `tiers: [secondary, principal]` (one line) so the
  extracted titles actually display for the many titled *secondary* characters
  (Duke Perrington, etc.); extracting a fact that never renders is pointless.
- Test: `tests/test_facts.py` (new); extend `tests/test_generate_wiki_pages_binding.py`; a bundle-injection test in the wiki_preparation tests.

`titles` is already an `extracted-fact` OPT slot for PERSON in `base.yaml`; the
only change there is widening its tier gate to include `secondary`.

## Testing strategy

- `extract_titles`: single title (`Captain Westfall` → `["Captain"]`); multiple
  (`["Celaena", "Adarlan's Assassin", "the King's Champion"]` → `["Assassin", "Champion"]`);
  dedupe + first-seen order; empty role_words → `[]`; no false positive on a plain
  name (`["Nehemia"]` → `[]`).
- Bundle: `build_entity_bundle(..., role_words=[...])` includes `titles` derived
  from the entity's aliases; with `role_words=None`/`[]`, `titles == []`.
- Binder: an entity carrying `titles: ["Captain"]` and a PERSON/principal template
  gets `infobox_fields["titles"] == "Captain"`; an entity with no titles gets no
  `titles` row; `batch-bound` binding (nom/alias) still works unchanged; `llm-prose`
  slots are never bound.
- Full suite green (current `main` baseline; report actual numbers).

## Risks

- Titles only appear if the titled form survived alias-resolution as an alias (it
  does for the shipping book: `Captain Westfall`, `Duke Perrington`). Prose-only
  titles are out of scope (deferred, higher-recall LLM pass later).
- `role_words` doubles as the importance-classification vocabulary; reusing it for
  titles is intentional and adds no new config surface.
