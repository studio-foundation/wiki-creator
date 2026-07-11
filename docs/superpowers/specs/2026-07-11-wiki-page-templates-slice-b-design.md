# Wiki Page Templates — Slice B Design (STU-436)

**Date:** 2026-07-11
**Status:** Design approved (conversation), pending spec review
**Linear:** STU-436 · depends on slice A (merged, PR #52)
**Related:** STU-318 (detection safety net), STU-319 (force-set title/importance/type)

## Context

Slice A shipped `wiki_creator/page_templates.py`: a typed template schema where every
slot carries a **provenance** tag (`batch-bound` / `extracted-fact` / `llm-prose`).
Slice B is the first consumer. It targets the `batch-bound` class.

Today, identity fields in the infobox are handled by **detection + repair**: the LLM
authors `infobox_fields` freely, and `_force_correct_identity` (STU-318/319) repairs a
swapped `nom` / drops a sibling's `alias` *after the fact* (PERSON-only). STU-436 is the
**prevention** counterpart: bind identity fields from the batch entity by code so the LLM
never authors them and confusion is structurally impossible for that class.

## Goal

1. **Bind batch-bound identity fields by code** — `nom` (canonical_name) and `alias`
   (aliases) come from the batch entity, overwriting whatever the LLM emitted.
2. **Consume slice A's section resolver** — `generation_profile` derives its section list
   from `resolve_template(...).section_tokens()` instead of the hardcoded/config list.

`type` is intentionally **not** bound in slice B: the batch entity only knows the coarse
type (`PLACE`, not `castle`), which is redundant noise in an infobox. The useful
*specific* type (castle, guild) is an `extracted-fact` and belongs to slice C. So even
though the template tags `type` as `batch-bound`, `_batch_bound_value` supplies no value
for it and it is skipped.

Out of scope (later slices): `extracted-fact` slots including the specific `type`
(status, affiliation, castle/guild — slice C), missing entity types (slice D),
section-scoped prose (slice E), prompt trimming, and wiring the relationship enum into
the Relations section.

## Design

### 1. Section list from the template resolver

`generation_profile(config, importance, entity_type)` (scripts/generate_wiki_pages.py:1009)
currently returns `(sections, max_tokens)` where `sections` comes from `config[importance]`
or a hardcoded default. Change: derive `sections` from
`resolve_template(entity_type, importance, {"generation": config}).section_tokens()`.

- `config` here is the `generation` sub-dict (`book_cfg["generation"]`, per call site line
  1117), so it is wrapped as `{"generation": config}` to match `resolve_template`'s
  `book_config["generation"]…` access. Section resolution needs nothing else.
- `max_tokens` resolution is unchanged (stays a `generation_profile` concern).
- Slice A guarantees `section_tokens()` preserves the legacy config's section **order**,
  so the swap is order-preserving. It is **behavior-preserving for the shipping book on 11
  of 12 (type × tier) combinations**; the exception is intentional: the book's *flat*
  `secondary.sections` lists `relationships` for every type, but the type-aware template
  gates PLACE `relationships` to `principal`, so **PLACE/secondary drops `relationships`**
  (`[infobox, biography, references]`). This is the desired type-aware refinement (the
  point of the reshape), pinned by `test_generation_profile_place_secondary_drops_relationships`.
- Backward compat: a book with no `generation.<tier>` config resolves to the base-default
  template for its entity type — which is the intended new default, and matches the old
  `_DEFAULT_SECTIONS_BY_IMPORTANCE` closely (references now included at figurant, an
  intentional slice-A improvement).

### 2. Batch-bound binding

New helpers in `scripts/generate_wiki_pages.py`:

```
_batch_bound_value(entity: dict, token: str) -> str | None
    nom   -> entity["canonical_name"]
    alias -> ", ".join(entity.get("aliases", []))  (None if empty)
    (any other token, including type) -> None
```

```
_bind_batch_fields(page: dict, entity: dict, book_config: dict) -> None
    page.setdefault("infobox_fields", {})
    resolved = resolve_template(entity["type"], entity["importance"], book_config)
    for slot in resolved.infobox():
        if slot.provenance != "batch-bound":
            continue
        value = _batch_bound_value(entity, slot.token)
        if value:                      # skip tokens the batch cannot source
            page["infobox_fields"][slot.token] = value
```

- The mechanism is **template-driven**: it binds exactly the tokens the resolved template
  tags `batch-bound`. `_batch_bound_value` encodes what the batch can actually supply; a
  token with no sensible batch value (e.g. `type`, whose only batch value is the coarse
  entity type) returns `None` and is skipped.
- Binding **overwrites** any LLM-authored value for that token, making identity confusion
  impossible for bound fields regardless of what the model produced.

### 3. Threading & call sites

`_run_generation_for_entity(...)` (the per-entity generation function) gains a
`book_config: dict | None = None` parameter, passed from the main loop (which already holds
`book_cfg`). `_bind_batch_fields(page, entity, book_config)` is called on the successful
page immediately before `return item_result` (after the `_force_correct_identity` block) and
on the recovered page in the identity-rejected path (before `return recovered`), so every
non-stub page gets deterministic identity fields. Stub / dry-run / insufficient-data pages
already carry `title = canonical_name` and an empty infobox; they are left as-is.

### 4. The post-hoc net stays

`_force_correct_identity`, `_recover_identity_rejected_page`, and the `forbidden_names`
guard are **unchanged**. Binding makes the infobox `nom`/`alias` repair inside
`_force_correct_identity` a redundant no-op (the bound values already match the entity), but
the function still covers the PERSON path defensively and the `forbidden_names` guard covers
**prose-level** confusion (biography text), which binding does not touch. Removing the now-
redundant infobox repair is deferred (documented for a later cleanup).

## Files

- Modify: `scripts/generate_wiki_pages.py` — `generation_profile`, new `_batch_bound_value`
  / `_bind_batch_fields`, `_run_generation_for_entity` signature + two call sites.
- Test: `tests/test_generate_wiki_pages_binding.py` (new), plus any existing
  `generation_profile` tests that assert the old section source.

`wiki_creator/templates/base.yaml` is **not** modified in slice B.

## Testing strategy

- `_batch_bound_value`: nom←canonical_name; alias←joined aliases; alias empty → None;
  type → None (all types); unknown token → None.
- `_bind_batch_fields`: overwrites an LLM-swapped `nom` with canonical_name; sets `alias`
  from the entity; does **not** add a `type` row for any type. Binds only `batch-bound`
  slots (leaves `extracted-fact`/`llm-prose` untouched).
- `generation_profile`: returns `resolve_template(...).section_tokens()` for a book whose
  `generation.<tier>` config is present (order preserved) and for a book with no such config
  (base-default). `max_tokens` still honored.
- Regression: existing generation tests still pass (the section source changed but the
  shipping book's resolved order matches its legacy config).

## Risks

- `_bind_batch_fields` assumes `page["infobox_fields"]` exists. `parse_response` /
  `make_stub_page` always set it (to `{}` at least); the binding is only invoked on
  non-stub pages that carry it. Guard with `page.setdefault("infobox_fields", {})`.
- `entity["importance"]` / `entity["type"]` are required by `resolve_template`; both are
  present on every batch entity (used throughout generation already).
