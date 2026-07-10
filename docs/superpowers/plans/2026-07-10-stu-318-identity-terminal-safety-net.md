# STU-318 Identity-Confusion Terminal Safety Net — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When identity confusion survives the `wiki-page-item` validator + RALPH retries, recover the rejected page and force-correct its infobox identity fields instead of discarding it as a failed stub.

**Architecture:** Detection already exists (`check_identity_match`, commit #41) and is wired as a hard validation stage with 3× RALPH retries. We leave that untouched. We add, in `scripts/generate_wiki_pages.py` and PERSON-only: (1) pure repair helpers reusing the validator's `_normalize_name`; (2) an *identity-only* rejection gate so we never smuggle a page past grounding/language validators; (3) recovery of the rejected generation output via the existing `_load_studio_stage_output`, force-correct, keep. A belt-and-suspenders force-correct also runs on the success path.

**Tech Stack:** Python 3, pytest, existing Studio pipeline plumbing.

## Global Constraints

- Guard applies to `entity_type == "PERSON"` only; all other types keep today's behaviour.
- Reuse `scripts.wiki_page_validator._normalize_name` — do NOT define a second normalization.
- Never add hardcoded vocabulary lists to scripts (CLAUDE.md). The only literals introduced are the validator's own error-marker substrings, kept in sync with `check_identity_match`.
- New function params are optional with safe defaults so existing callers/tests are unaffected.
- Before claiming completion: `pytest -q` green (baseline `735 passed, 31 skipped`) and `mypy wiki_creator/` clean.
- Work in the worktree at `.claude/worktrees/stu-318` on branch `arianedguay/stu-318-confusions-identitaires-llm-validation-post-generation`.

---

### Task 1: Pure identity-repair helpers

**Files:**
- Modify: `scripts/generate_wiki_pages.py` (add import + `_nom_matches_identity`, `_force_correct_identity`)
- Test: `tests/test_generate_wiki_pages.py`

**Interfaces:**
- Consumes: `scripts.wiki_page_validator._normalize_name(value: str) -> str`.
- Produces:
  - `_nom_matches_identity(nom: str, entity: dict) -> bool`
  - `_force_correct_identity(page: dict, entity: dict, sibling_canonicals: set[str] | None = None) -> bool` — mutates `page["infobox_fields"]` in place, tags `page["_identity_corrected"] = True` when it changes anything, returns whether it changed.

- [ ] **Step 1: Write the failing tests**

Add to the import block at the top of `tests/test_generate_wiki_pages.py` (alongside the existing names):

```python
from scripts.generate_wiki_pages import (
    _force_correct_identity,
    _nom_matches_identity,
)
```

Append these tests to `tests/test_generate_wiki_pages.py`:

```python
# --- STU-318: identity repair helpers ---

def _verin_entity():
    return {
        "canonical_name": "Verin",
        "type": "PERSON",
        "aliases": ["Verin", "Lord Verin"],
    }


def test_nom_matches_identity_true_for_partial_canonical():
    entity = {"canonical_name": "Nehemia Ytger", "type": "PERSON", "aliases": []}
    assert _nom_matches_identity("Nehemia", entity) is True


def test_nom_matches_identity_true_for_known_alias():
    entity = {"canonical_name": "Chaol", "type": "PERSON",
              "aliases": ["Captain Westfall", "Chaol Westfall"]}
    assert _nom_matches_identity("Captain Westfall", entity) is True


def test_nom_matches_identity_false_for_swapped_name():
    assert _nom_matches_identity("Kaltain", _verin_entity()) is False


def test_nom_matches_identity_true_for_empty_nom():
    assert _nom_matches_identity("", _verin_entity()) is True


def test_force_correct_identity_rewrites_swapped_nom():
    page = {"infobox_fields": {"nom": "Kaltain", "rôle": "Dame de la cour"},
            "content": "## Biographie\n\nTexte."}
    changed = _force_correct_identity(page, _verin_entity())
    assert changed is True
    assert page["infobox_fields"]["nom"] == "Verin"
    assert page["_identity_corrected"] is True


def test_force_correct_identity_noop_when_clean():
    page = {"infobox_fields": {"nom": "Verin"}, "content": "x"}
    changed = _force_correct_identity(page, _verin_entity())
    assert changed is False
    assert "_identity_corrected" not in page


def test_force_correct_identity_strips_sibling_swapped_alias():
    page = {"infobox_fields": {"nom": "Verin", "alias": "Kaltain, Le Fléau"},
            "content": "x"}
    changed = _force_correct_identity(page, _verin_entity(),
                                      sibling_canonicals={"Kaltain Rompier"})
    assert changed is True
    assert page["infobox_fields"]["alias"] == "Le Fléau"


def test_force_correct_identity_keeps_own_alias_even_if_sibling_token_overlaps():
    entity = {"canonical_name": "Kaltain Rompier", "type": "PERSON",
              "aliases": ["Kaltain", "Kaltain Rompier"]}
    page = {"infobox_fields": {"nom": "Kaltain Rompier", "alias": "Kaltain"},
            "content": "x"}
    changed = _force_correct_identity(page, entity, sibling_canonicals={"Kaltain Rompier"})
    assert page["infobox_fields"]["alias"] == "Kaltain"
    assert changed is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd .claude/worktrees/stu-318 && python -m pytest tests/test_generate_wiki_pages.py -k "identity" -q`
Expected: FAIL — `ImportError` / `cannot import name '_force_correct_identity'`.

- [ ] **Step 3: Implement the helpers**

Near the top of `scripts/generate_wiki_pages.py`, after the existing
`from wiki_creator.paths import book_paths_from_yaml` import, add:

```python
from scripts.wiki_page_validator import _normalize_name
```

Add these functions just below `_check_forbidden_names` (around line 438):

```python
def _nom_matches_identity(nom: str, entity: dict) -> bool:
    """True if nom matches (accent/case-insensitively) the entity's own
    canonical_name or any known alias. Empty nom counts as a match: there is
    nothing authored to be wrong."""
    nom_n = _normalize_name(nom)
    if not nom_n:
        return True
    candidates = [entity.get("canonical_name", ""), *entity.get("aliases", [])]
    for cand in candidates:
        cand_n = _normalize_name(cand)
        if cand_n and (nom_n in cand_n or cand_n in nom_n):
            return True
    return False


def _force_correct_identity(
    page: dict, entity: dict, sibling_canonicals: set[str] | None = None
) -> bool:
    """Repair infobox identity fields in place. PERSON-only (caller gates on
    type). Rewrites a swapped `nom` to canonical_name and drops any `alias`
    value that belongs to a *sibling* batch entity. Returns True if changed."""
    infobox = page.get("infobox_fields") or {}
    canonical = entity.get("canonical_name", "")
    changed = False

    nom = str(infobox.get("nom", "")).strip()
    if nom and not _nom_matches_identity(nom, entity):
        infobox["nom"] = canonical
        changed = True

    sib_norm = {n for n in (_normalize_name(s) for s in (sibling_canonicals or set())) if n}
    if sib_norm and infobox.get("alias"):
        kept = []
        for value in str(infobox["alias"]).split(","):
            v_n = _normalize_name(value)
            is_swap = bool(v_n) and not _nom_matches_identity(value, entity) and any(
                v_n == s or v_n in s or s in v_n for s in sib_norm
            )
            if is_swap:
                changed = True
            else:
                kept.append(value.strip())
        infobox["alias"] = ", ".join(k for k in kept if k)
        if not infobox["alias"]:
            infobox.pop("alias", None)

    if changed:
        page["infobox_fields"] = infobox
        page["_identity_corrected"] = True
    return changed
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd .claude/worktrees/stu-318 && python -m pytest tests/test_generate_wiki_pages.py -k "identity" -q`
Expected: PASS (8 new tests).

- [ ] **Step 5: Commit**

```bash
cd .claude/worktrees/stu-318
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(stu-318): identity repair helpers for generated PERSON pages

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wire recovery + force-correct into generation flow

**Files:**
- Modify: `scripts/generate_wiki_pages.py` (`_run_generation_for_entity`, `main`; add `_rejection_is_identity_only`, `_recover_identity_rejected_page`)
- Test: `tests/test_generate_wiki_pages.py`

**Interfaces:**
- Consumes: `_force_correct_identity` (Task 1), existing `_load_studio_stage_output(run_id, stage_name) -> dict | None`, `parse_response`, `make_stub_page`, `_save_generation_debug_artifact`.
- Produces:
  - `_rejection_is_identity_only(run_id: str) -> bool`
  - `_recover_identity_rejected_page(*, entity, item_result, sibling_canonicals=None) -> dict | None`
  - `_run_generation_for_entity(...)` gains keyword param `sibling_canonicals: set[str] | None = None`.

- [ ] **Step 1: Write the failing tests**

Add to the import block in `tests/test_generate_wiki_pages.py`:

```python
from scripts.generate_wiki_pages import _rejection_is_identity_only
```

Append these tests to `tests/test_generate_wiki_pages.py`:

```python
# --- STU-318: recovery + force-correct wiring ---

def _verin_entity_ctx():
    return {
        "canonical_name": "Verin",
        "importance": "secondary",
        "type": "PERSON",
        "aliases": ["Verin", "Lord Verin"],
        "context_by_chapter": {"ch01": ["Verin entre dans la cour."]},
    }


def test_force_correct_on_success_path_keeps_page(monkeypatch, tmp_path):
    def fake_runner(**kwargs):
        return {
            "title": "Verin",
            "importance": "secondary",
            "entity_type": "PERSON",
            "infobox_fields": {"nom": "Kaltain"},
            "content": "## Biographie\n\nVerin est un lord.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=_verin_entity_ctx(),
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
        sibling_canonicals={"Kaltain Rompier"},
    )

    assert page.get("_failed") is not True
    assert page["infobox_fields"]["nom"] == "Verin"
    assert page["_identity_corrected"] is True


def test_recovers_and_corrects_on_identity_only_rejection(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"error": "studio_run_failed", "run_metadata": {"run_id": "r1"}},
    )

    def fake_stage_output(run_id, stage_name):
        if stage_name == "wiki-page-validator":
            return {"valid": False,
                    "errors": ["❌ Infobox 'nom: Kaltain' ne correspond pas à l'entité 'Verin'"]}
        return {
            "title": "Verin",
            "importance": "secondary",
            "entity_type": "PERSON",
            "infobox_fields": {"nom": "Kaltain"},
            "content": "## Biographie\n\nVerin est un lord.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._load_studio_stage_output", fake_stage_output)

    page = _run_generation_for_entity(
        entity=_verin_entity_ctx(),
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
        sibling_canonicals={"Kaltain Rompier"},
    )

    assert page.get("_failed") is not True
    assert page["infobox_fields"]["nom"] == "Verin"
    assert page["_identity_corrected"] is True


def test_does_not_recover_on_non_identity_rejection(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"error": "studio_run_failed", "run_metadata": {"run_id": "r1"}},
    )

    def fake_stage_output(run_id, stage_name):
        if stage_name == "wiki-page-validator":
            return {"valid": False,
                    "errors": ["❌ Nom non ancré dans les extraits source : Yrene"]}
        return {"title": "Verin", "importance": "secondary", "entity_type": "PERSON",
                "infobox_fields": {"nom": "Kaltain"}, "content": "x"}

    monkeypatch.setattr("scripts.generate_wiki_pages._load_studio_stage_output", fake_stage_output)

    page = _run_generation_for_entity(
        entity=_verin_entity_ctx(),
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
        sibling_canonicals={"Kaltain Rompier"},
    )

    assert page.get("_failed") is True


def test_does_not_recover_when_no_run_id(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"error": "studio_run_timeout", "run_metadata": {}},
    )
    page = _run_generation_for_entity(
        entity=_verin_entity_ctx(),
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
    )
    assert page.get("_failed") is True


def test_non_person_success_page_not_touched(monkeypatch, tmp_path):
    entity = {"canonical_name": "Rifthold", "importance": "secondary", "type": "PLACE",
              "aliases": [], "context_by_chapter": {"ch01": ["Rifthold est une cité."]}}

    monkeypatch.setattr(
        "scripts.generate_wiki_pages._run_wiki_page_item",
        lambda **_: {"title": "Rifthold", "importance": "secondary", "entity_type": "PLACE",
                     "infobox_fields": {"nom": "Adarlan"}, "content": "## Description\n\nx"},
    )

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox"],
        max_tokens=800,
        dry_run=False,
        debug_dir=tmp_path / "debug",
        sibling_canonicals={"Adarlan"},
    )

    assert page["infobox_fields"]["nom"] == "Adarlan"
    assert "_identity_corrected" not in page


def test_rejection_is_identity_only(monkeypatch):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._load_studio_stage_output",
        lambda run_id, stage: {"errors": ["❌ Infobox 'nom: X' ne correspond pas à l'entité 'Y'"]},
    )
    assert _rejection_is_identity_only("r1") is True


def test_rejection_is_identity_only_false_when_mixed(monkeypatch):
    monkeypatch.setattr(
        "scripts.generate_wiki_pages._load_studio_stage_output",
        lambda run_id, stage: {"errors": [
            "❌ Infobox 'nom: X' ne correspond pas à l'entité 'Y'",
            "❌ Nom non ancré dans les extraits source : Z",
        ]},
    )
    assert _rejection_is_identity_only("r1") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd .claude/worktrees/stu-318 && python -m pytest tests/test_generate_wiki_pages.py -k "recover or force_correct_on or rejection_is or non_person or run_id" -q`
Expected: FAIL — `cannot import name '_rejection_is_identity_only'` / unexpected `sibling_canonicals` kwarg.

- [ ] **Step 3: Add the recovery helpers**

Add just below `_force_correct_identity` in `scripts/generate_wiki_pages.py`:

```python
# Kept in sync with check_identity_match in scripts/wiki_page_validator.py:
# these are the only validator errors that identity confusion produces.
_IDENTITY_ERROR_MARKERS = ("≠ entité demandée", "ne correspond pas à l'entité")


def _rejection_is_identity_only(run_id: str) -> bool:
    """True iff the validator rejected the run and *every* error it reported is
    an identity error. Guards against smuggling a page past grounding/language
    validators when we recover it."""
    vout = _load_studio_stage_output(str(run_id), "wiki-page-validator")
    errors = (vout or {}).get("errors") or []
    return bool(errors) and all(
        any(marker in str(e) for marker in _IDENTITY_ERROR_MARKERS) for e in errors
    )


def _recover_identity_rejected_page(
    *, entity: dict, item_result: dict, sibling_canonicals: set[str] | None = None
) -> dict | None:
    """Recover a PERSON page from an identity-only rejected run and force-correct
    its identity fields. Returns the kept page, or None if not recoverable."""
    if entity.get("type") != "PERSON":
        return None
    run_id = str((item_result.get("run_metadata") or {}).get("run_id") or "").strip()
    if not run_id or not _rejection_is_identity_only(run_id):
        return None
    recovered = _load_studio_stage_output(run_id, "wiki-page-item")
    if not isinstance(recovered, dict):
        return None
    page = parse_response(json.dumps(recovered, ensure_ascii=False), entity)
    if page.get("_failed"):
        return None
    _force_correct_identity(page, entity, sibling_canonicals)
    page["_identity_corrected"] = True
    return page
```

- [ ] **Step 4: Wire into `_run_generation_for_entity`**

Change the signature (add the new param) — locate:

```python
def _run_generation_for_entity(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    sections: list[str],
    max_tokens: int,
    dry_run: bool,
    debug_dir: Path,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
) -> dict:
```

and add `sibling_canonicals: set[str] | None = None,` immediately before `) -> dict:`.

Replace the error branch:

```python
    if isinstance(item_result, dict) and item_result.get("error"):
        _save_generation_debug_artifact(debug_dir, entity, item_result)
        return make_stub_page(entity, failed=True)
```

with:

```python
    if isinstance(item_result, dict) and item_result.get("error"):
        recovered = _recover_identity_rejected_page(
            entity=entity,
            item_result=item_result,
            sibling_canonicals=sibling_canonicals,
        )
        _save_generation_debug_artifact(debug_dir, entity, item_result)
        if recovered is not None:
            print(" ⚠ identity-corrected from rejected run", file=sys.stderr, end="", flush=True)
            return recovered
        return make_stub_page(entity, failed=True)
```

Replace the final `return item_result` (last line of the function) with:

```python
    if (
        entity.get("type") == "PERSON"
        and isinstance(item_result, dict)
        and "content" in item_result
        and _force_correct_identity(item_result, entity, sibling_canonicals)
    ):
        print(" ⚠ nom force-corrected", file=sys.stderr, end="", flush=True)

    return item_result
```

- [ ] **Step 5: Thread `sibling_canonicals` from `main`**

In `main`, inside `for path, batch in batches:` after `entities = batch.get("entities", [])`, add:

```python
            batch_canonicals = {
                e.get("canonical_name", "") for e in entities if e.get("canonical_name")
            }
```

In the `_run_generation_for_entity(...)` call inside the per-entity `try`, add
as the last keyword argument (after `grounding=grounding_cfg,`):

```python
                        sibling_canonicals=batch_canonicals - {name},
```

- [ ] **Step 6: Run the new tests to verify they pass**

Run: `cd .claude/worktrees/stu-318 && python -m pytest tests/test_generate_wiki_pages.py -k "recover or force_correct_on or rejection_is or non_person or run_id" -q`
Expected: PASS.

- [ ] **Step 7: Run the full suite + types**

Run: `cd .claude/worktrees/stu-318 && python -m pytest -q && mypy wiki_creator/`
Expected: `pytest` ≥ `743 passed, 31 skipped` (baseline 735 + 15 new, minus none removed); `mypy` clean.

- [ ] **Step 8: Commit**

```bash
cd .claude/worktrees/stu-318
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(stu-318): recover + force-correct identity-rejected PERSON pages

Terminal safety net: on identity-only rejection after RALPH retries,
recover the generation output and force-correct nom/alias instead of
stubbing. Belt-and-suspenders force-correct on the success path too.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Reuse `_normalize_name` → Task 1 import. ✓
- `_nom_matches_identity` aliases-aware → Task 1. ✓
- `_force_correct_identity` (nom rewrite + sibling-alias strip + tag) → Task 1. ✓
- Identity-only rejection gate → Task 2 `_rejection_is_identity_only`. ✓
- Error-path recovery via `_load_studio_stage_output` → Task 2 `_recover_identity_rejected_page`. ✓
- Success-path belt-and-suspenders → Task 2 Step 4. ✓
- `sibling_canonicals` threading → Task 2 Step 5. ✓
- PERSON-only gating → helpers + wiring both gate on `type`. ✓
- Non-identity rejection preserves stub → Task 2 test `test_does_not_recover_on_non_identity_rejection`. ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `_force_correct_identity(page, entity, sibling_canonicals=None)` and `_nom_matches_identity(nom, entity)` signatures match between definition (Task 1) and all call sites (Task 2). `_recover_identity_rejected_page` and `_rejection_is_identity_only` used exactly as defined.

**Note on test count:** Step 7's expected count assumes the current baseline (`735 passed`) and 15 added tests; adjust the exact number to whatever `pytest -q` reports if the baseline has since moved — the pass/skip *green* is the gate, not the literal integer.
