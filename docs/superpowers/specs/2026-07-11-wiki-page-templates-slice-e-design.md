# Wiki Page Templates — Slice E Design (section-scoped prose)

**Date:** 2026-07-11
**Status:** Design approved (conversation), pending spec review
**Depends on:** slices A-D (merged). Last slice of the reshape.

## Context

Today `_run_generation_for_entity` makes **one** `studio run wiki-page-item`
call producing the entire page `content` (all sections at once). Slice E
generates each `llm-prose` section in its **own scoped call**, reusing the
existing `sections`-list plumbing (`build_prompt`/`wiki-page-item` already take
a section list — passing a single-section list scopes it with the existing
agent/contract, no new Studio stage).

Cost is affordable: only **principal** entities have multiple prose sections
(biography, personality, physical, powers, trivia); secondary/figurant have just
biography. Principals are few, and the model is local Ollama (wall-clock, not $).

## Goal

1. Generate each content section in a separate `wiki-page-item` call
   (`sections=[section]`), then assemble the section blocks in order.
2. Run `forbidden_names` validation **per section** (smaller surface).
3. **Graceful degradation**: a failed OPT section is omitted (the rest survive)
   instead of stubbing the whole page. Only a failed `biography` (the MIN
   section) falls back to the failed-stub.
4. Assemble `references` **deterministically** (`## Références` + book title) —
   no LLM call, no hallucinated sources.

## Design

### New helpers — `scripts/generate_wiki_pages.py`

```
_assemble_section_blocks(blocks: list[str]) -> str
    # pure: join non-empty section markdown blocks with a blank line
    return "\n\n".join(b.strip() for b in blocks if b and b.strip())

_generate_one_section(*, entity, section, book_title, model, timeout,
                      max_tokens, forbidden_names, language, file_path,
                      grounding) -> str | None
    # one wiki-page-item call scoped to sections=[section]; returns the section's
    # content block, or None on error / persistent forbidden-name hit (omit).
    result = _run_wiki_page_item(..., sections=[section], ...)
    if result.get("error"): return None
    content = result.get("content") or ""
    if section == "relationships" and not entity.get("relationships"):
        content = _strip_relations_section(content)      # no rels → drop
    if forbidden_names and _check_forbidden_names({"content": content, ...}, forbidden_names):
        # one retry, then omit the section if it persists
        ...retry once; still hit → return None
    return content or None
```

### Rewrite `_run_generation_for_entity` to loop

```
stub checks (unchanged: insufficient-data, dry-run)

content_sections = [s for s in sections if s not in ("infobox", "references")]
blocks = []
for section in content_sections:
    block = _generate_one_section(entity=entity, section=section, ...)
    if block:
        blocks.append(block)
    elif section == "biography":            # MIN section failed → page is empty
        return make_stub_page(entity, failed=True)
    # else: OPT section omitted

if not blocks:                              # nothing generated at all
    return make_stub_page(entity, failed=True)

if "references" in sections:
    blocks.append(_references_block(book_title, language))   # deterministic

page = {
    "title": entity["canonical_name"],
    "importance": entity["importance"],
    "entity_type": entity["type"],
    "infobox_fields": {},
    "content": _assemble_section_blocks(blocks),
}
if entity.get("type") == "PERSON":
    _force_correct_identity(page, entity, sibling_canonicals)   # unchanged net
_bind_batch_fields(page, entity, book_config)                  # slice B, once
return page
```

### Notable simplification (flagged for review)

The current single-call path calls `_recover_identity_rejected_page` to recover a
whole-page studio run that the validator rejected on identity grounds. **The
sectioned path drops this recovery**: a section run that errors is simply omitted
(biography → stub). Rationale: identity confusion is now much smaller-surface
(one section per call) and the infobox is bound deterministically (slice B) +
`_force_correct_identity` still runs on the assembled page + `forbidden_names`
runs per section. The whole-page rejected-run recovery was a band-aid for the
large-surface single call; per-section it is largely redundant. `_recover_*`
stays in the file (still referenced by any non-sectioned callers/tests) but is
not invoked by the sectioned flow.

## Files

- Modify: `scripts/generate_wiki_pages.py` — `_assemble_section_blocks`,
  `_generate_one_section`, `_references_block`, rewrite `_run_generation_for_entity`.
- Test: `tests/test_generate_wiki_pages.py` (or a new module) — assembly (pure),
  per-section generation (mock `_run_wiki_page_item`), sectioned flow
  (per-section calls, biography-fail-stub, omit-failed-OPT, deterministic refs,
  infobox still bound).

No change to `.studio/` agents/contracts or `base.yaml`.

## Testing strategy

- `_assemble_section_blocks`: joins blocks, drops empties, blank-line separator.
- `_generate_one_section`: returns content on success (mock `_run_wiki_page_item`);
  None on error; None on persistent forbidden hit (with one retry attempted);
  strips relations when no typed rels.
- `_run_generation_for_entity` (sectioned): calls `_run_wiki_page_item` once per
  content section (assert call count + per-call `sections=[one]`); assembles in
  order; biography failure → failed stub; a failed OPT section is omitted but the
  page still returns with the others; `references` appended deterministically
  without an LLM call; infobox bound once on the assembled page.
- Full suite green (report actual numbers).

## Risks / out of scope

- Per-section calls repeat the entity context in each prompt (fine for a local
  model; a shared-context optimization is out of scope).
- `max_tokens` is passed per section as-is (a per-section budget split is a minor
  future optimization).
- Section-specific prompt tailoring (e.g. "Personality: traits not plot") is out
  of scope — v1 reuses the existing per-section `SECTION_DEFINITIONS`.
