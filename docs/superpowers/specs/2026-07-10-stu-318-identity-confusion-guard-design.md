# STU-318 — Identity-confusion terminal safety net for generated PERSON pages

**Linear:** [STU-318](https://linear.app/studioag/issue/STU-318/confusions-identitaires-llm-validation-post-generation-canonical-name)
**Date:** 2026-07-10
**Status:** Design approved, ready for planning

## Problem

Run 15 produced three *pure LLM hallucinations* — identity confusions between
distinct characters, with no upstream file containing the bad association:

1. **Nehemia** described as "de son vrai nom Yrene Astellaris" — *prose-level*.
2. **Verin** infobox `nom: Kaltain` — *infobox-level* swap.
3. **Kaltain Rompier** described as "confidente de la reine Elena Havilliard du
   royaume de Ruhn" — *prose-level*.

## Critical context: detection already shipped (commit #41, same day)

STU-318 was filed 2026-04-02; **the identity-confusion *detection* it asks for
landed 2026-07-10 in commit `4b8f6bd` (#41)** — after the issue was filed.
[`check_identity_match`](../../../scripts/wiki_page_validator.py) already:

- verifies the infobox `nom`/`name`/`titre` and the page `title` match the
  requested `canonical_name` (accent/case-insensitive containment),
- **explicitly targets Verin→Kaltain** (named in its docstring; covered by a
  passing test asserting `{"title": "Verin"}` + `nom: Kaltain` returns errors),
- is wired as a **hard validation stage** in the `wiki-page-item` pipeline inside
  a `max_iterations: 3` RALPH group, so a detected confusion already triggers up
  to 3 regenerations.

**Therefore STU-318's detection half is done.** The remaining, un-shipped gap is
the *terminal behaviour*: when the confusion survives all 3 retries, the run
rejects → [`_run_wiki_page_item`](../../../scripts/generate_wiki_pages.py) returns
an error → `generate_wiki_pages` emits a **failed stub**, discarding the whole
(possibly-good) biography. This spec closes that gap.

## Scope

### In scope — Design A: terminal safety net

Leave the validator and the 3× RALPH retries **untouched** — the LLM keeps its 3
chances to self-correct (best-quality outcome). Change only what happens *after*
exhaustion, in `scripts/generate_wiki_pages.py`, for `entity_type == "PERSON"`:

1. **Recover** the generation output of a rejected run instead of stubbing, using
   the existing [`_load_studio_stage_output(run_id, "wiki-page-item")`](../../../scripts/generate_wiki_pages.py)
   (already used elsewhere as a fallback; reads the run's `.jsonl` log).
2. **Force-correct** the recovered page's identity fields and **keep** it:
   - infobox `nom` → `canonical_name` if it matches neither the entity's own
     `canonical_name` nor any known alias;
   - drop any infobox `alias` value that matches a *sibling* batch entity's
     canonical_name (the **sibling-swap** cross-check — genuinely new; the
     validator only compares against the entity's own name);
   - tag `page["_identity_corrected"] = True`, write a debug artifact, log.
3. **Belt-and-suspenders:** apply the same force-correct on the *success* path
   too (a no-op when `nom` already matches), so a bad `nom` that slips the
   validator for any reason is still repaired.

### Out of scope (deferred, conscious decisions)

- **Re-implementing detection** in `generate_wiki_pages.py` — rejected; would
  duplicate `check_identity_match` and create two sources of truth.
- **Page templates / deterministic identity fields** → [STU-436](https://linear.app/studioag/issue/STU-436/page-templates-make-wiki-page-identityinfobox-fields-deterministic).
- **Promoting "Yrene Astellaris" into code `validation.forbidden_names`** — dropped.
- **`nehemia.json` GT edit** (issue action #2) — the GT files feed the human
  `validate-wiki-run` audit skill, not pipeline code; dropped by explicit decision.

Cases #1 and #3 are *prose-level* confusions in the LLM-authored biography; this
guard targets the *infobox* class (case #2) plus the page-loss regression. The
`forbidden_names` guard remains the mechanism for prose.

## Design

### Reuse the validator's normalization primitive

Import [`_normalize_name`](../../../scripts/wiki_page_validator.py) (NFKD, strip
combining marks, lowercase, strip) from `scripts.wiki_page_validator` — one
normalization definition shared with the detector, so the repair decision uses
the same rule that flagged the page. Do **not** duplicate normalization.

### Identity match (aliases-aware)

`check_identity_match` compares only against the entity's *title* (canonical) and
ignores aliases — that is fine for *flagging*, but the *repair* must not clobber a
legitimately alias-derived `nom` (e.g. Chaol's `nom: "Captain Westfall"`). So the
repair's self-match consults `{canonical_name} ∪ aliases`:

```python
def _nom_matches_identity(nom: str, entity: dict) -> bool:
    """True if nom (accent/case-insensitively) matches canonical_name or any alias."""
    nom_n = _normalize_name(nom)
    if not nom_n:
        return True  # nothing authored to be wrong
    candidates = [entity.get("canonical_name", ""), *entity.get("aliases", [])]
    for cand in candidates:
        cand_n = _normalize_name(cand)
        if cand_n and (nom_n in cand_n or cand_n in nom_n):
            return True
    return False
```

Containment (not token-set equality) mirrors `check_identity_match` and handles
multi-word names: `"Nehemia"` matches `"Nehemia Ytger"`; `"Kaltain"` matches
neither `"Verin"` nor its aliases → repaired.

### Force-correct

```python
def _force_correct_identity(
    page: dict, entity: dict, sibling_canonicals: set[str] | None = None
) -> bool:
    """Repair infobox identity fields in-place. Returns True if changed.

    PERSON-only; caller gates on entity_type. Reuses _normalize_name.
    """
    infobox = page.get("infobox_fields") or {}
    changed = False
    canonical = entity.get("canonical_name", "")

    nom = str(infobox.get("nom", "")).strip()
    if nom and not _nom_matches_identity(nom, entity):
        infobox["nom"] = canonical
        changed = True

    sib_norm = {_normalize_name(s) for s in (sibling_canonicals or set()) if _normalize_name(s)}
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

The alias-swap strip is conservative: it only removes a value that matches a
sibling *and* does not match this entity's own identity, so a legitimate alias is
never dropped.

### Wire into `_run_generation_for_entity`

Add a PERSON-gated block after the existing forbidden_names handling:

- **Success path** (`item_result` has `"content"`): call
  `_force_correct_identity(item_result, entity, sibling_canonicals)`; if it
  changed anything, write a debug artifact and log a warning. Return the page.
- **Error path** (`item_result.get("error")`): recover **only** when the
  rejection was *identity-only* — otherwise keeping the page would smuggle
  content past legitimate validators (grounding, French-contamination, forbidden
  series). Steps: read `run_id` from `item_result["run_metadata"]`; fetch the
  validator output `_load_studio_stage_output(run_id, "wiki-page-validator")`;
  if its `errors` are **all** identity errors, then recover the generation output
  `_load_studio_stage_output(run_id, "wiki-page-item")`, run it through
  `parse_response(json.dumps(recovered), entity)`, `_force_correct_identity(...)`,
  keep it (tag `_identity_corrected`), write a debug artifact, log. Any
  non-identity error, missing `run_id`, or unrecoverable output → existing
  failed-stub behaviour.

Only PERSON entities take this path; non-PERSON keeps today's behaviour.

#### Identity-only rejection gate

`check_identity_match` is the only validator that emits errors containing the
markers `"≠ entité demandée"` or `"ne correspond pas à l'entité"`. Gate recovery
on *every* validator error matching one of those markers:

```python
_IDENTITY_ERROR_MARKERS = ("≠ entité demandée", "ne correspond pas à l'entité")

def _rejection_is_identity_only(run_id: str) -> bool:
    """True iff the validator rejected and *all* its errors are identity errors.
    Keeps in sync with check_identity_match in wiki_page_validator.py."""
    vout = _load_studio_stage_output(str(run_id), "wiki-page-validator")
    errors = (vout or {}).get("errors") or []
    return bool(errors) and all(
        any(m in str(e) for m in _IDENTITY_ERROR_MARKERS) for e in errors
    )
```

This couples to the validator's error strings; the plan adds a regression test
asserting a *non*-identity rejection is **not** recovered, so drift is caught.

### Thread `sibling_canonicals`

`main` builds, per batch, `all_canonicals = {e["canonical_name"] for e in entities}`
and passes `sibling_canonicals = all_canonicals - {name}` into
`_run_generation_for_entity` (new optional param, default `None`, so existing
callers/tests are unaffected).

## Testing

Unit tests for the new pure functions:

- `_nom_matches_identity`: `"Nehemia"` vs entity canonical `"Nehemia Ytger"` → True;
  `"Kaltain"` vs entity `"Verin"` (+ its aliases) → False; `"Captain Westfall"`
  vs entity `"Chaol"` with that alias → True (legit alias not clobbered);
  empty nom → True.
- `_force_correct_identity`:
  - `nom: "Kaltain"` on entity `"Verin"` → nom rewritten to `"Verin"`,
    `_identity_corrected` True, returns True.
  - clean `nom` matching canonical → no change, returns False.
  - `alias: "Kaltain, Le Fléau"` with `"Kaltain Rompier"` a sibling → the
    Kaltain value stripped, `"Le Fléau"` kept.
  - legit alias equal to an own alias but token-overlapping a sibling → kept
    (conservative rule).

Guard-flow tests (monkeypatch `_run_wiki_page_item` / `_load_studio_stage_output`,
mirroring the existing forbidden_names tests):

- **Success path with bad nom:** runner returns a page with `nom: "Kaltain"` for
  entity `"Verin"` → returned page is kept (not a stub), `nom == "Verin"`,
  `_identity_corrected is True`, debug artifact written.
- **Error path recovery (identity-only):** runner returns
  `{"error": ..., "run_metadata": {"run_id": "r1"}}`; `_load_studio_stage_output`
  monkeypatched so `"wiki-page-validator"` → `{"errors": ["❌ Infobox 'nom: Kaltain'
  ne correspond pas à l'entité 'Verin'"]}` and `"wiki-page-item"` → a page with
  bad `nom` → returned page is kept, force-corrected, `_identity_corrected is
  True` — **not** a `_failed` stub.
- **Error path, non-identity rejection:** validator errors include a grounding
  error (e.g. `"❌ Nom non ancré…"`) → recovery is **refused**, existing
  failed-stub behaviour preserved (no smuggling past grounding).
- **Error path, unrecoverable:** runner error with no `run_id` (or recovery
  returns None) → existing failed-stub behaviour preserved.
- **Non-PERSON:** an ORG/PLACE entity with a "wrong" nom is left untouched (guard
  skipped).

Run `pytest -q` and `mypy wiki_creator/` before claiming completion.

## Follow-up issue

Tracked as [STU-436](https://linear.app/studioag/issue/STU-436/page-templates-make-wiki-page-identityinfobox-fields-deterministic)
— page templates that make identity fields deterministic (prevention over
detection). Related to STU-318 and STU-319.
