# Wiki Page Templates — Slice B (STU-436) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bind the batch-bound identity fields (`nom`, `alias`) into the wiki-page infobox by code so the LLM can never swap them, and derive the section list from slice A's `resolve_template(...).section_tokens()`.

**Architecture:** Two small pure helpers (`_batch_bound_value`, `_bind_batch_fields`) do the binding, driven by the resolved template's `batch-bound` slots. `generation_profile` switches its section source to `resolve_template`. `_run_generation_for_entity` threads `book_config` and calls the binder on every non-stub page. The STU-318/319 post-hoc net is left intact.

**Tech Stack:** Python 3, `wiki_creator.page_templates` (slice A), `pytest`.

## Global Constraints

- No hardcoded vocabulary in scripts — labels/vocab live in `base.yaml` or book YAML (CLAUDE.md invariant). Slice B adds no vocabulary and does **not** modify `base.yaml`.
- Degrade gracefully on absent/malformed config — never raise on a missing optional key.
- Binding overwrites the LLM's value for a batch-bound token; a token the batch cannot source (returns `None`) is skipped, never written as empty.
- `type` is NOT bound in slice B (coarse batch type is noise; specific type is slice C).
- Backward compat: `generation_profile`'s returned section list must match the shipping book's current order (slice A's `section_tokens()` guarantees legacy-order parity).
- Baseline: current `main` full suite is green (~840 passed; report actual numbers, do not hardcode). Run `pytest -q` before each commit.

---

### Task 1: `_batch_bound_value` helper

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_binding.py` (new)

**Interfaces:**
- Produces: `_batch_bound_value(entity: dict, token: str) -> str | None` — returns the batch entity's value for a batch-bound infobox token, or `None` when the batch cannot supply a sensible value for that token.

- [ ] **Step 1: Write the failing test**

Create `tests/test_generate_wiki_pages_binding.py`:

```python
# tests/conftest.py already adds the project root to sys.path, so scripts/ is
# importable directly (same convention as tests/test_generate_wiki_pages.py).
import scripts.generate_wiki_pages as gwp


def test_batch_bound_value_nom():
    entity = {"canonical_name": "Celaena Sardothien", "aliases": ["Celaena"]}
    assert gwp._batch_bound_value(entity, "nom") == "Celaena Sardothien"


def test_batch_bound_value_alias_joins():
    entity = {"canonical_name": "Chaol Westfall", "aliases": ["Chaol", "Captain Westfall"]}
    assert gwp._batch_bound_value(entity, "alias") == "Chaol, Captain Westfall"


def test_batch_bound_value_alias_empty_is_none():
    assert gwp._batch_bound_value({"canonical_name": "X", "aliases": []}, "alias") is None
    assert gwp._batch_bound_value({"canonical_name": "X"}, "alias") is None


def test_batch_bound_value_type_and_unknown_are_none():
    entity = {"canonical_name": "X", "type": "PLACE", "aliases": []}
    assert gwp._batch_bound_value(entity, "type") is None
    assert gwp._batch_bound_value(entity, "affiliation") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_binding.py -v`
Expected: FAIL with `AttributeError: module 'generate_wiki_pages' has no attribute '_batch_bound_value'`

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/generate_wiki_pages.py` (near the other identity helpers, e.g. after `_force_correct_identity`):

```python
def _batch_bound_value(entity: dict, token: str) -> str | None:
    """Value for a batch-bound infobox token, sourced from the batch entity.
    Returns None for tokens the batch cannot sensibly supply (skipped by the
    binder). `type` is intentionally unsupported: the coarse batch type is
    infobox noise; the specific type is an extracted-fact (slice C)."""
    if token == "nom":
        return entity.get("canonical_name") or None
    if token == "alias":
        aliases = [a for a in (entity.get("aliases") or []) if a]
        return ", ".join(aliases) if aliases else None
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_generate_wiki_pages_binding.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_binding.py
git commit -m "feat(generation): _batch_bound_value helper for batch-bound infobox tokens (STU-436)"
```

---

### Task 2: `_bind_batch_fields` — template-driven binding

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_binding.py`

**Interfaces:**
- Consumes: `_batch_bound_value` (Task 1); `resolve_template` from `wiki_creator.page_templates`.
- Produces: `_bind_batch_fields(page: dict, entity: dict, book_config: dict | None) -> None` — mutates `page["infobox_fields"]` in place, overwriting each `batch-bound` infobox token (per the resolved template) with its batch value; skips tokens whose value is `None`; no-op when `book_config is None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_generate_wiki_pages_binding.py`:

```python
def _person_entity():
    return {"canonical_name": "Verin", "type": "PERSON", "importance": "secondary",
            "aliases": ["Ver"]}


def test_bind_overwrites_swapped_nom():
    page = {"infobox_fields": {"nom": "Kaltain", "affiliation": "Adarlan"}}
    gwp._bind_batch_fields(page, _person_entity(), {})
    assert page["infobox_fields"]["nom"] == "Verin"          # overwritten from batch
    assert page["infobox_fields"]["affiliation"] == "Adarlan"  # non-batch-bound untouched


def test_bind_sets_alias_and_skips_type():
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, _person_entity(), {})
    assert page["infobox_fields"]["nom"] == "Verin"
    assert page["infobox_fields"]["alias"] == "Ver"
    assert "type" not in page["infobox_fields"]              # type never bound


def test_bind_creates_infobox_and_is_noop_without_config():
    page = {}
    gwp._bind_batch_fields(page, _person_entity(), None)     # None config → no-op
    assert page.get("infobox_fields", {}) == {}
    gwp._bind_batch_fields(page, _person_entity(), {})       # dict config → binds
    assert page["infobox_fields"]["nom"] == "Verin"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_binding.py -v`
Expected: FAIL with `AttributeError: ... has no attribute '_bind_batch_fields'`

- [ ] **Step 3: Write minimal implementation**

At the top of `scripts/generate_wiki_pages.py`, ensure the import exists (add if absent, next to the other `wiki_creator` imports):

```python
from wiki_creator.page_templates import resolve_template
```

Add the binder (after `_batch_bound_value`):

```python
def _bind_batch_fields(page: dict, entity: dict, book_config: dict | None) -> None:
    """Overwrite batch-bound infobox tokens with their batch-entity values, per
    the resolved template. Prevention counterpart to _force_correct_identity:
    the LLM's authored value is discarded for these tokens, so identity
    confusion is impossible for them. No-op when book_config is None."""
    if book_config is None:
        return
    page.setdefault("infobox_fields", {})
    resolved = resolve_template(entity.get("type"), entity.get("importance"), book_config)
    for slot in resolved.infobox():
        if slot.provenance != "batch-bound":
            continue
        value = _batch_bound_value(entity, slot.token)
        if value:
            page["infobox_fields"][slot.token] = value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_generate_wiki_pages_binding.py -v`
Expected: PASS (7 tests total)

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_binding.py
git commit -m "feat(generation): _bind_batch_fields template-driven identity binding (STU-436)"
```

---

### Task 3: `generation_profile` sources sections from the template

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_binding.py`

**Interfaces:**
- Consumes: `resolve_template` (imported in Task 2).
- Produces: `generation_profile(config, importance, entity_type)` unchanged signature/return `(sections: list[str], max_tokens: int)`, but `sections` now comes from `resolve_template(entity_type, importance, {"generation": config}).section_tokens()`, falling back to the existing default when the template resolves empty (e.g. unknown/None type).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_generate_wiki_pages_binding.py`:

```python
def test_generation_profile_uses_template_order():
    # legacy-style book config; sections must come back in the config's order
    config = {"principal": {"sections_by_type": {"PERSON": [
        "infobox", "biography", "personality", "relationships", "references"]}}}
    sections, _ = gwp.generation_profile(config, "principal", "PERSON")
    assert sections == ["infobox", "biography", "personality", "relationships", "references"]


def test_generation_profile_base_default_when_no_config():
    sections, max_tokens = gwp.generation_profile({}, "figurant", "PERSON")
    assert sections[0] == "infobox"
    assert "biography" in sections
    assert isinstance(max_tokens, int)


def test_generation_profile_unknown_type_falls_back():
    sections, _ = gwp.generation_profile({}, "principal", None)
    assert "infobox" in sections and "biography" in sections
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_binding.py -k generation_profile -v`
Expected: FAIL — `test_generation_profile_uses_template_order` fails because the current code returns base.yaml order / config order differently, or the unknown-type test returns `[]`. (Observe the actual failure and confirm it is the section-source behavior, not an import error.)

- [ ] **Step 3: Write minimal implementation**

Replace the `sections` derivation in `generation_profile` (currently reads `sections_by_type` / `sections` off `config[importance]`) with a template call, keeping the `max_tokens` logic intact:

```python
def generation_profile(config: dict, importance: str, entity_type: str | None = None) -> tuple[list[str], int]:
    profile = config.get(importance, {})

    resolved = resolve_template(entity_type, importance, {"generation": config})
    sections = resolved.section_tokens()
    if not sections:  # unknown/None type → keep the legacy default
        sections = _DEFAULT_SECTIONS_BY_IMPORTANCE.get(
            importance, _DEFAULT_SECTIONS_BY_IMPORTANCE["figurant"]
        )

    max_tokens = profile.get("max_tokens_per_page", DEFAULT_NUM_PREDICT)
    try:
        max_tokens = int(max_tokens)
    except (TypeError, ValueError):
        max_tokens = DEFAULT_NUM_PREDICT
    if max_tokens < 64:
        max_tokens = 64
    return sections, max_tokens
```

(Keep `_DEFAULT_SECTIONS_BY_IMPORTANCE` and `DEFAULT_NUM_PREDICT` — they remain the fallback and the max-tokens default. Remove no other code.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages_binding.py -k generation_profile -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run any existing generation_profile tests**

Run: `pytest -q -k "generation_profile or generate_wiki" 2>&1 | tail -20`
Expected: PASS. If a pre-existing test asserted the old section source and now fails, update its expectation to the resolved section list (the resolved order matches the book config's order per slice A) — do not weaken the assertion. Report any such update.

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_binding.py
git commit -m "feat(generation): source section list from resolve_template (STU-436)"
```

---

### Task 4: Wire binding into the generation flow

**Files:**
- Modify: `scripts/generate_wiki_pages.py`

**Interfaces:**
- Consumes: `_bind_batch_fields` (Task 2).
- Produces: `_run_generation_for_entity(...)` gains a `book_config: dict | None = None` keyword parameter and calls `_bind_batch_fields(page, entity, book_config)` on every non-stub page it returns. The main loop passes `book_config=book_cfg`.

- [ ] **Step 1: Add the parameter and bind at both return paths**

In `scripts/generate_wiki_pages.py`, add `book_config: dict | None = None` to the `_run_generation_for_entity` signature (the function called at the main-loop site, def near line 785).

Bind on the recovered page — just before `return recovered` in the identity-rejected branch:

```python
        if recovered is not None:
            _bind_batch_fields(recovered, entity, book_config)
            print(" ⚠ identity-corrected from rejected run", file=sys.stderr, end="", flush=True)
            return recovered
```

Bind on the normal success path — just before the final `return item_result`, after the `_force_correct_identity` block:

```python
    if (
        entity.get("type") == "PERSON"
        and isinstance(item_result, dict)
        and "content" in item_result
        and _force_correct_identity(item_result, entity, sibling_canonicals)
    ):
        print(" ⚠ nom force-corrected", file=sys.stderr, end="", flush=True)

    if isinstance(item_result, dict) and "content" in item_result:
        _bind_batch_fields(item_result, entity, book_config)

    return item_result
```

- [ ] **Step 2: Pass book_config from the main loop**

At the `_run_generation_for_entity(...)` call site (near line 1125), add the argument (using `book_cfg`, defined at the top of `main()`):

```python
                        sibling_canonicals=batch_canonicals - {name},
                        book_config=book_cfg,
                    )
```

- [ ] **Step 3: Verify no regression across the whole suite**

Run: `pytest -q`
Expected: green (previous count + the 10 new binding/profile tests from Tasks 1-3; report actual numbers). No failures.

- [ ] **Step 4: Sanity-check the wiring by reading**

Confirm by reading the diff that: (a) `book_config` flows main → `_run_generation_for_entity` → `_bind_batch_fields`; (b) binding runs after `_force_correct_identity` (so the bound `nom` is the final value); (c) stub/dry-run/insufficient-data early returns are NOT bound (they carry `title=canonical_name` and an empty infobox by design). State these three confirmations in the report.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py
git commit -m "feat(generation): wire batch-bound binding into generation flow (STU-436)"
```

---

## Self-Review

**Spec coverage** (against `2026-07-11-wiki-page-templates-slice-b-design.md`):
- Bind `nom`/`alias` by code → Tasks 1-2.
- `type` not bound → Task 1 (`_batch_bound_value` returns None for type) + Task 2 test asserts no `type` row.
- Template-driven (binds only `batch-bound` slots) → Task 2 (`resolve_template(...).infobox()` + provenance check).
- Section list from `resolve_template().section_tokens()` with legacy-order parity + fallback → Task 3.
- Thread `book_config`, bind on every non-stub page (success + recovered), stubs untouched → Task 4.
- Post-hoc net (`_force_correct_identity`, recovery, forbidden_names) unchanged → no task touches them; Task 4 binds *after* force-correct, leaving it a redundant no-op as designed.
- `base.yaml` not modified → no task touches it.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; tests show real assertions.

**Type consistency:** `_batch_bound_value(entity, token) -> str | None` and `_bind_batch_fields(page, entity, book_config) -> None` signatures identical across Tasks 1-4. `generation_profile` signature/return unchanged (Task 3). `_run_generation_for_entity` gains only an optional kwarg (Task 4), so existing callers are unaffected. `resolve_template` is called with `{"generation": config}` in Task 3 (section context) and with the full `book_config` in Task 2 (binding) — both satisfy its `book_config["generation"]…` access; the binding path does not need `export`, so passing the full config is a superset and correct.

**Note for slice C handoff:** the specific `type` (castle/guild), `status`, `affiliation`, `titles` are `extracted-fact` slots still authored by the LLM (or absent). Slice C makes the pipeline produce them so the binder's sibling — an extracted-fact filler — can populate those infobox rows deterministically.
