# Wiki Page Templates — Slice D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop dropping the custom NER model's `PLACE`/`FACTION`/`EVENT` entities, and neutralize the PERSON→PLACE cue-retag that mis-types people — recovering the empty ORG/EVENT categories and the real places.

**Architecture:** Two focused edits to `scripts/entity_extraction.py`: (1) add the custom labels to `LABEL_TO_TYPE` and derive `KEPT_LABELS` from it; (2) remove the PERSON→PLACE rule in `_retag_entity_type_from_context`. Plus test updates and a mandatory end-to-end verification (foundational-stage change).

**Tech Stack:** Python 3, spaCy (custom model `wiki-ner-en`), `pytest`.

## Global Constraints

- `LABEL_TO_TYPE`/`KEPT_LABELS` are structural NER label→type mapping, NOT domain vocabulary — they stay in the script (the CLAUDE.md no-hardcoded-vocab invariant is about word lists like cue_words, not label taxonomy).
- Deriving `KEPT_LABELS = frozenset(LABEL_TO_TYPE)` must be behavior-preserving for standard models (all 7 current members are already keys).
- Do not weaken tests: where a test asserted the old dropped/retagged behavior, update it to assert the new *correct* behavior.
- Baseline: current `main` full suite is green (report actual numbers). Run `pytest -q` before each commit.
- This is a foundational-stage change (blast radius = every downstream stage) → the end-to-end verification (after Task 2) is mandatory before the branch is considered done.

---

### Task 1: Map the custom labels (PLACE / FACTION / EVENT)

**Files:**
- Modify: `scripts/entity_extraction.py`
- Test: `tests/test_entity_extraction.py`

**Interfaces:**
- Produces: `LABEL_TO_TYPE` maps `PLACE→PLACE`, `FACTION→ORG`, `EVENT→EVENT` (plus the existing standard mappings); `KEPT_LABELS = frozenset(LABEL_TO_TYPE)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_entity_extraction.py` (it already imports `KEPT_LABELS`; add `LABEL_TO_TYPE` to the import from `scripts.entity_extraction`):

```python
def test_custom_model_labels_are_mapped_and_kept():
    from scripts.entity_extraction import LABEL_TO_TYPE, KEPT_LABELS
    # custom wiki-ner-en model labels: {PERSON, PLACE, FACTION, ORG, EVENT}
    assert LABEL_TO_TYPE["PLACE"] == "PLACE"
    assert LABEL_TO_TYPE["FACTION"] == "ORG"
    assert LABEL_TO_TYPE["EVENT"] == "EVENT"
    for lab in ("PLACE", "FACTION", "EVENT"):
        assert lab in KEPT_LABELS
    # standard-model labels still mapped (backward compat)
    assert LABEL_TO_TYPE["PERSON"] == "PERSON"
    assert LABEL_TO_TYPE["GPE"] == "PLACE"
    assert LABEL_TO_TYPE["ORG"] == "ORG"
    # KEPT_LABELS is derived from the map (can't drift)
    assert KEPT_LABELS == frozenset(LABEL_TO_TYPE)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_entity_extraction.py::test_custom_model_labels_are_mapped_and_kept -v`
Expected: FAIL — `KeyError: 'PLACE'` (not yet in `LABEL_TO_TYPE`).

- [ ] **Step 3: Write the implementation**

In `scripts/entity_extraction.py`, replace the `KEPT_LABELS`/`LABEL_TO_TYPE` block (lines ~122-132) with:

```python
# Map every NER label we can type to its canonical entity type. Covers both
# standard spaCy models (PER/LOC/GPE/FAC/ORG/NORP/PERSON) and the project's
# custom fantasy-NER model (wiki-ner-en: PERSON/PLACE/FACTION/ORG/EVENT).
LABEL_TO_TYPE = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "LOC": "PLACE",
    "GPE": "PLACE",
    "FAC": "PLACE",
    "PLACE": "PLACE",
    "ORG": "ORG",
    "NORP": "ORG",
    "FACTION": "ORG",
    "EVENT": "EVENT",
}
# Keep any label we know how to type — derived so the two can never drift.
KEPT_LABELS = frozenset(LABEL_TO_TYPE)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_entity_extraction.py::test_custom_model_labels_are_mapped_and_kept -v`
Expected: PASS.

- [ ] **Step 5: Run the full extraction test module + suite**

Run: `pytest tests/test_entity_extraction.py -q` then `pytest -q`
Expected: green. If a pre-existing test now fails because it assumed `PLACE`/`FACTION`/`EVENT` were dropped, that assumption was the bug — update it to the correct behavior and report which test and why. (Do not weaken assertions.)

- [ ] **Step 6: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "fix(extraction): map custom model PLACE/FACTION/EVENT labels (slice D)"
```

---

### Task 2: Neutralize the PERSON→PLACE cue-retag

**Files:**
- Modify: `scripts/entity_extraction.py`
- Test: `tests/test_entity_extraction.py`

**Interfaces:**
- Consumes: `_retag_entity_type_from_context(entity, cue_words=None) -> str`.
- Produces: same signature; it no longer retags `PERSON → PLACE`. The PERSON→EVENT and ORG/PLACE→PERSON rules are unchanged.

- [ ] **Step 1: Write the failing test (the Arobynn regression)**

Append to `tests/test_entity_extraction.py`:

```python
def test_person_with_place_dense_context_stays_person():
    # Arobynn Hamel is a person whose introduction is place-dense. The custom
    # model labels him PERSON; ambient place words must NOT retag him to PLACE.
    entity = {
        "type": "PERSON",
        "raw_mentions": ["Arobynn Hamel"],
        "mentions_by_chapter": {
            "C05": [
                "Arobynn Hamel found her half-submerged on the banks of a frozen "
                "river and brought her to his keep on the border between Adarlan "
                "and Terrasen.",
            ]
        },
    }
    assert _retag_entity_type_from_context(entity) == "PERSON"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_entity_extraction.py::test_person_with_place_dense_context_stays_person -v`
Expected: FAIL — currently returns `"PLACE"` (place_score ≥ 2 from keep/border/banks/river).

- [ ] **Step 3: Remove the PERSON→PLACE rule**

In `_retag_entity_type_from_context`, delete these two lines (the first rule after the score loop):

```python
    if current == "PERSON" and place_score >= 2 and place_score > max(event_score, person_score):
        return "PLACE"
```

Update the function docstring: it retags PERSON→EVENT (strong event cues) and ORG/PLACE→PERSON (person cues); it no longer retags PERSON→PLACE (the custom model labels places directly, so a model-asserted PERSON is trusted).

- [ ] **Step 4: Run the new test to verify it passes**

Run: `pytest tests/test_entity_extraction.py::test_person_with_place_dense_context_stays_person -v`
Expected: PASS.

- [ ] **Step 5: Update the two obsolete PERSON→PLACE tests**

Two existing tests assert the removed behavior (an "Endovier" entity typed PERSON retagged to PLACE): `test_retags_place_from_context` (~line 176-183) and `test_retag_place_cue_standalone_word_still_fires` (~line 810-821). The custom model now labels Endovier as `PLACE` directly, so the retag band-aid is obsolete. Update both to assert the entity **stays `PERSON`** (place cues no longer force PLACE), and rename them to reflect the new intent (e.g. `test_place_cues_no_longer_retag_person_to_place`, `test_standalone_place_cue_word_no_longer_forces_place`). Keep their fixtures. Do NOT touch the EVENT retag test (`test_retags_event_from_context`) or the ORG/PLACE→PERSON tests — those rules are unchanged and must still pass.

- [ ] **Step 6: Run the extraction module + full suite**

Run: `pytest tests/test_entity_extraction.py -q` then `pytest -q`
Expected: green (report actual numbers). All retag tests reflect the new behavior; EVENT and PERSON-recovery retags unchanged.

- [ ] **Step 7: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "fix(extraction): stop retagging PERSON to PLACE on place cues (slice D)"
```

---

## End-to-End Verification (controller-run, MANDATORY)

This is a foundational-stage change; unit tests alone are insufficient. After both
tasks are reviewed clean, the controller re-runs extraction on the committed book
and confirms the recovery, then confirms the full suite:

1. Run extraction for `01-throne-of-glass` (via `make run-extraction` or the
   `scripts/entity_extraction.py` entry with the book's input).
2. Assert on the regenerated `processing_output/01-throne-of-glass/`:
   - `places_full.json` now contains real places (Endovier, Rifthold, Adarlan,
     Terrasen, …) — not just misfires.
   - `orgs_full.json` is non-empty (the model's FACTION entities, e.g. Fae).
   - The entity typed as the Arobynn person is `PERSON`, not `PLACE`.
   - `events_full.json` reflects the model's EVENT output (may be small).
3. `pytest -q` is green.

Record the before/after entity-type counts in the verification note. If the
recovery does not materialize, STOP and re-investigate (do not merge a
foundational change on unit tests alone).

## Self-Review

**Spec coverage** (against `2026-07-11-wiki-page-templates-slice-d-design.md`):
- Map custom labels (PLACE/FACTION/EVENT), derive KEPT_LABELS → Task 1.
- Neutralize PERSON→PLACE retag → Task 2.
- Update tests asserting old behavior → Task 1 Step 5, Task 2 Step 5.
- Blast-radius / end-to-end verification → the mandatory verification section.
- Out of scope (FACTION noise, affiliation, PERSON→EVENT) → untouched; no task.

**Placeholder scan:** No TBD/TODO; complete code in every code step; real assertions.

**Type consistency:** `LABEL_TO_TYPE`/`KEPT_LABELS` referenced identically in Task 1. `_retag_entity_type_from_context` signature unchanged in Task 2 (only a rule and docstring removed). No new symbols introduced elsewhere.
