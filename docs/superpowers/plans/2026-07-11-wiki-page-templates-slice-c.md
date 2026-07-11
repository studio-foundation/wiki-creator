# Wiki Page Templates — Slice C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deterministically extract role-word titles per entity from its name variants, inject them into the batch bundle, and extend the infobox binder to fill the `titles` extracted-fact slot.

**Architecture:** A pure helper `wiki_creator/facts.py:extract_titles` matches `role_words` (from cue_words) against an entity's name variants. `build_entity_bundle` adds a `titles` field. The slice-B binder (`_bind_batch_fields`) is generalized to dispatch by provenance so it also fills `extracted-fact` slots. `base.yaml` widens PERSON `titles` to the secondary tier so they render.

**Tech Stack:** Python 3, `wiki_creator.lang` (cue_words loader), `wiki_creator.page_templates` (slice A), `pytest`.

## Global Constraints

- No hardcoded vocabulary in scripts — `role_words` come from `cue_words/<lang>.json` via `load_lang_config`; `extract_titles` takes the list as a parameter and has no built-in list (CLAUDE.md invariant). Degrade to `[]` when role_words is empty/absent.
- Never raise on absent keys; degrade gracefully.
- `extracted-fact` binds like `batch-bound` (authoritative when present) but is OPT: absent → skipped → row omitted.
- Only `titles` is produced in slice C; `status`/`affiliation`/specific `type` stay `None` (future slices).
- Baseline: current `main` full suite is green (report actual numbers). Run `pytest -q` before each commit.

---

### Task 1: `extract_titles` deterministic helper

**Files:**
- Create: `wiki_creator/facts.py`
- Test: `tests/test_facts.py` (new)

**Interfaces:**
- Produces: `extract_titles(name_variants: Iterable[str], role_words: list[str]) -> list[str]` — unique, title-cased role-word titles found in the name variants, first-seen order; `[]` when role_words is empty.

- [ ] **Step 1: Write the failing test**

Create `tests/test_facts.py`:

```python
from wiki_creator.facts import extract_titles

ROLE_WORDS = ["captain", "guard", "queen", "king", "prince", "princess",
              "lady", "lord", "sir", "duke", "assassin", "champion"]


def test_single_title_from_alias():
    assert extract_titles(["Chaol", "Captain Westfall"], ROLE_WORDS) == ["Captain"]


def test_multiple_titles_dedup_first_seen_order():
    variants = ["Celaena", "Adarlan's Assassin", "the King's Champion", "Assassin"]
    assert extract_titles(variants, ROLE_WORDS) == ["Assassin", "Champion"]


def test_no_title_returns_empty():
    assert extract_titles(["Nehemia", "Nehemia Ytger"], ROLE_WORDS) == []


def test_empty_role_words_returns_empty():
    assert extract_titles(["Captain Westfall"], []) == []


def test_none_variants_safe():
    assert extract_titles([], ROLE_WORDS) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_facts.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki_creator.facts'`

- [ ] **Step 3: Write minimal implementation**

Create `wiki_creator/facts.py`:

```python
"""Deterministic per-entity fact extraction for wiki infobox extracted-fact
slots. Vocabulary comes from cue_words (passed in), never hardcoded here.
Home for the growing fact-extractor family (titles now; status/affiliation
in later slices)."""
from __future__ import annotations

import re
from typing import Iterable

_WORD_RE = re.compile(r"\b\w+\b")


def extract_titles(name_variants: Iterable[str], role_words: list[str]) -> list[str]:
    """Role-word titles found in an entity's name variants (aliases, mentions,
    canonical name). Whole-word, case-insensitive match against `role_words`;
    returns unique, title-cased titles in first-seen order. Empty when
    `role_words` is empty."""
    role_set = {w.lower() for w in (role_words or []) if w}
    if not role_set:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for variant in name_variants or []:
        for word in _WORD_RE.findall(str(variant).lower()):
            if word in role_set and word not in seen:
                seen.add(word)
                found.append(word.capitalize())
    return found
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_facts.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/facts.py tests/test_facts.py
git commit -m "feat(facts): deterministic role-word title extraction (slice C)"
```

---

### Task 2: Inject `titles` into the batch bundle

**Files:**
- Modify: `scripts/wiki_preparation.py`
- Test: `tests/test_wiki_preparation.py`

**Interfaces:**
- Consumes: `extract_titles` (Task 1); `book_language`, `load_lang_config` from `wiki_creator.lang`.
- Produces: `build_entity_bundle(...)` gains a `role_words: list[str] | None = None` keyword param and adds a `"titles"` key to the returned bundle. `main()` loads `role_words` once from the book language and passes it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_wiki_preparation.py` (reuses the existing `_registries()` helper in that file):

```python
def test_build_entity_bundle_extracts_titles_from_aliases():
    persons, places, orgs, events = _registries()
    entity = {
        "canonical_name": "Chaol",
        "type": "PERSON",
        "importance": "secondary",
        "aliases": ["Chaol Westfall", "Captain Westfall"],
    }
    entities_by_name = {"Chaol": entity}
    role_words = ["captain", "duke", "king", "prince", "assassin"]

    bundle = build_entity_bundle(
        entity, [], persons, places, orgs, events, entities_by_name,
        role_words=role_words,
    )
    assert bundle["titles"] == ["Captain"]


def test_build_entity_bundle_titles_empty_without_role_words():
    persons, places, orgs, events = _registries()
    entity = {"canonical_name": "Chaol", "type": "PERSON", "importance": "secondary",
              "aliases": ["Captain Westfall"]}
    bundle = build_entity_bundle(
        entity, [], persons, places, orgs, events, {"Chaol": entity},
    )
    assert bundle["titles"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wiki_preparation.py -k titles -v`
Expected: FAIL with `KeyError: 'titles'` (bundle has no titles key yet).

- [ ] **Step 3: Add the parameter and field to `build_entity_bundle`**

Add `role_words: list[str] | None = None` to the `build_entity_bundle` signature (after `graph`). In the returned bundle dict, add one entry (place it near `"aliases"`):

```python
        "titles": extract_titles(
            [canonical_name, *entity.get("aliases", []), *entity.get("raw_mentions", [])],
            role_words or [],
        ),
```

Add the import at the top of `scripts/wiki_preparation.py` (next to the other `wiki_creator` imports):

```python
from wiki_creator.facts import extract_titles
from wiki_creator.lang import book_language, load_lang_config
```

- [ ] **Step 4: Run the bundle test to verify it passes**

Run: `pytest tests/test_wiki_preparation.py -k titles -v`
Expected: PASS (2 tests) — the first yields `["Captain"]`, the second `[]` (role_words defaults to `[]`).

- [ ] **Step 5: Thread `role_words` from `main()`**

In `main()` (near the top, after `payload = json.load(sys.stdin)`), load the role words once from the book language:

```python
    _ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    role_words = load_lang_config(book_language(_ctx)).get("role_words", [])
```

Then pass it into the `build_entity_bundle(...)` call inside the `entity_bundles` comprehension:

```python
            graph=_series_graph,
            role_words=role_words,
        )
```

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: green (report actual numbers; the 2 new bundle tests + Task 1's 5).

- [ ] **Step 7: Commit**

```bash
git add scripts/wiki_preparation.py tests/test_wiki_preparation.py
git commit -m "feat(preparation): inject extracted titles into batch bundle (slice C)"
```

---

### Task 3: Bind the `titles` extracted-fact slot

**Files:**
- Modify: `wiki_creator/templates/base.yaml`
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_binding.py`

**Interfaces:**
- Consumes: `resolve_template` (already imported); the bundle `titles` field (Task 2).
- Produces: `_extracted_fact_value(entity: dict, token: str) -> str | None` (`titles` → joined titles, else None); `_bind_batch_fields` now also binds `extracted-fact` slots.

- [ ] **Step 1: Widen the `titles` tier gate in base.yaml**

In `wiki_creator/templates/base.yaml`, change the PERSON `titles` slot from
`tiers: [principal]` to `tiers: [secondary, principal]` (so titled secondary
characters render a Titles row):

```yaml
      - {token: titles,      group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [secondary, principal]}
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_generate_wiki_pages_binding.py`:

```python
def test_bind_fills_titles_extracted_fact_at_secondary():
    entity = {"canonical_name": "Chaol Westfall", "type": "PERSON",
              "importance": "secondary", "aliases": ["Chaol"], "titles": ["Captain"]}
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, entity, {})
    assert page["infobox_fields"]["titles"] == "Captain"     # extracted-fact bound
    assert page["infobox_fields"]["nom"] == "Chaol Westfall"  # batch-bound still works


def test_bind_omits_titles_when_absent():
    entity = {"canonical_name": "Nehemia", "type": "PERSON",
              "importance": "secondary", "aliases": [], "titles": []}
    page = {"infobox_fields": {}}
    gwp._bind_batch_fields(page, entity, {})
    assert "titles" not in page["infobox_fields"]            # OPT + no value → omitted


def test_extracted_fact_value_titles_and_unknown():
    assert gwp._extracted_fact_value({"titles": ["Captain", "Duke"]}, "titles") == "Captain, Duke"
    assert gwp._extracted_fact_value({"titles": []}, "titles") is None
    assert gwp._extracted_fact_value({"affiliation": "X"}, "affiliation") is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_binding.py -k "titles or extracted_fact" -v`
Expected: FAIL — `_extracted_fact_value` undefined, and `titles` not bound (binder skips non-batch-bound slots).

- [ ] **Step 4: Add `_extracted_fact_value` and extend the binder**

In `scripts/generate_wiki_pages.py`, add the helper next to `_batch_bound_value`:

```python
def _extracted_fact_value(entity: dict, token: str) -> str | None:
    """Value for an extracted-fact infobox token, sourced from facts the pipeline
    produced into the batch entity. None when the fact is absent (slot omitted).
    `status`, `affiliation`, and the specific `type` are future slices."""
    if token == "titles":
        titles = [t for t in (entity.get("titles") or []) if t]
        return ", ".join(titles) if titles else None
    return None
```

Update `_bind_batch_fields` to dispatch by provenance (replace the
`if slot.provenance != "batch-bound": continue` skip):

```python
def _bind_batch_fields(page: dict, entity: dict, book_config: dict | None) -> None:
    """Overwrite pipeline-sourced infobox tokens with authoritative values, per
    the resolved template: `batch-bound` from the batch identity, `extracted-fact`
    from facts the pipeline produced. `llm-prose` slots are left to the LLM.
    No-op when book_config is None."""
    if book_config is None:
        return
    page.setdefault("infobox_fields", {})
    resolved = resolve_template(entity.get("type"), entity.get("importance"), book_config)
    for slot in resolved.infobox():
        if slot.provenance == "batch-bound":
            value = _batch_bound_value(entity, slot.token)
        elif slot.provenance == "extracted-fact":
            value = _extracted_fact_value(entity, slot.token)
        else:
            continue
        if value:
            page["infobox_fields"][slot.token] = value
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages_binding.py -v`
Expected: PASS (the 3 new tests plus all slice-B binding tests still green — the
existing tests use only batch-bound tokens, unaffected by the new branch).

- [ ] **Step 6: Run the full suite**

Run: `pytest -q`
Expected: green (report actual numbers). No failures.

- [ ] **Step 7: Commit**

```bash
git add wiki_creator/templates/base.yaml scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_binding.py
git commit -m "feat(generation): bind titles extracted-fact infobox slot (slice C)"
```

---

## Self-Review

**Spec coverage** (against `2026-07-11-wiki-page-templates-slice-c-design.md`):
- Deterministic role-word title extraction → Task 1 (`extract_titles`, no hardcoded vocab, `[]` on empty role_words).
- Inject into batch bundle → Task 2 (`build_entity_bundle` param + field; `main` threading via `book_language`/`load_lang_config`).
- Generalize the binder to `extracted-fact` → Task 3 (`_extracted_fact_value` + provenance dispatch, name kept).
- Widen `titles` to secondary tier so it renders → Task 3 Step 1.
- `status`/`affiliation`/specific `type` deferred → `_extracted_fact_value` returns None for them; no task adds them.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; tests show real assertions.

**Type consistency:** `extract_titles(name_variants, role_words) -> list[str]` used identically in Tasks 1-2. `_extracted_fact_value(entity, token) -> str | None` mirrors `_batch_bound_value`'s signature. `_bind_batch_fields` signature unchanged (Task 3 only changes its body), so slice-B call sites and tests are unaffected. `build_entity_bundle` gains an optional trailing kwarg, so existing positional callers/tests are unaffected.

**Note for later slices:** `_extracted_fact_value` is the extension point — slice D adds specific `type`/`affiliation` (once ORGs exist), a later slice adds `status`. `wiki_creator/facts.py` is the home for their extractors.
