# Wiki Page Templates — Slice D Design (recover dropped entity types)

**Date:** 2026-07-11
**Status:** Design approved (conversation), pending spec review
**Reshape context:** A (schema) → B (batch-bound) → C (extracted-fact titles) → **D (recover ORG/EVENT/PLACE from extraction)** → E (section-scoped prose)
**Method:** found via systematic-debugging (root cause proven, not guessed)

## Root cause (proven)

The audit's three symptoms — `events_full.json = 0`, `orgs_full.json = 0`,
`places_full.json` = only misfires — all trace to **one config gap**.

The book uses a **custom** NER model (`models/wiki-ner-en/model-best`) whose
label set is `{PERSON, PLACE, FACTION, ORG, EVENT}`. But
`scripts/entity_extraction.py` was written for **standard** spaCy models:

```python
KEPT_LABELS = {"PER", "LOC", "ORG", "PERSON", "GPE", "FAC", "NORP"}   # line 122
...
if ent.label_ not in KEPT_LABELS:      # line 581
    continue
"type": LABEL_TO_TYPE.get(ent.label_, "OTHER"),   # line 599
```

The custom labels `PLACE`, `FACTION`, `EVENT` are **absent** from `KEPT_LABELS`,
so they are silently dropped. Reproduction (model run on a 62k-char sample):

```
EMITTED:  PLACE: 57   PERSON: 154   FACTION: 7
DROPPED:  PLACE: 57 (Adarlan, Endovier, Erilea, Eyllwe, Rifthold, Terrasen…)
          FACTION: 7 (Duke, Fae…)
```

- **places_full garbage** — the 57 real places are dropped; the only survivors
  are PERSON→PLACE cue-retag misfires (Arobynn Hamel).
- **orgs_full = 0** — the model labels organizations `FACTION` (dropped); it
  never emits standard `ORG`.
- **events_full = 0** — the model's `EVENT` label is dropped.

Confirmed downstream: `entities_classified.json` = `{PERSON: 13, OTHER: 4, PLACE: 1}`.

## Goal

1. **Map the custom labels** so they survive extraction: `PLACE→PLACE`,
   `FACTION→ORG`, `EVENT→EVENT`, keeping the standard labels for books that use
   a standard model.
2. **Neutralize the PERSON→PLACE cue-retag** — a band-aid for a model that
   didn't detect places, now actively harmful (mis-types Arobynn). The custom
   model labels places directly, so a PERSON it labeled PERSON is trusted.

Out of scope: FACTION model noise (`Duke`/`Fae` mislabels — a model-quality
issue, not a mapping issue; downstream `min_mentions`/importance filter some);
`affiliation` binding (a later slice consuming the recovered ORGs); the
PERSON→EVENT retag (already conservative, left as-is).

## Design

### 1. Label maps — `scripts/entity_extraction.py`

Add the custom labels to `LABEL_TO_TYPE` and **derive `KEPT_LABELS` from it** so
the two can never drift again:

```python
LABEL_TO_TYPE = {
    "PER": "PERSON", "PERSON": "PERSON",
    "LOC": "PLACE", "GPE": "PLACE", "FAC": "PLACE", "PLACE": "PLACE",
    "ORG": "ORG", "NORP": "ORG", "FACTION": "ORG",
    "EVENT": "EVENT",
}
KEPT_LABELS = frozenset(LABEL_TO_TYPE)   # keep = anything we can type
```

`KEPT_LABELS` today equals `set(LABEL_TO_TYPE)` already (all 7 members are keys),
so deriving it is behavior-preserving for standard models and adds the 3 custom
labels in one place. This is structural label→type mapping, **not** domain
vocabulary — it does not belong in `cue_words` (the CLAUDE.md invariant is about
word lists, not NER label taxonomy).

### 2. Neutralize PERSON→PLACE retag — `scripts/entity_extraction.py`

In `_retag_entity_type_from_context`, remove the rule:

```python
if current == "PERSON" and place_score >= 2 and place_score > max(event_score, person_score):
    return "PLACE"
```

Keep the other rules (PERSON→EVENT on strong event cues; ORG/PLACE→PERSON on
person cues). Update the docstring: the function no longer retags PERSON→PLACE.
Rationale: with the model now labeling places directly, retagging a
model-asserted PERSON to PLACE on ambient place words is a net loss (Arobynn's
introduction is place-dense but he is a person).

## Blast radius & verification (critical)

This changes **what entities exist** for every downstream stage: clustering,
relationships, classification, preparation, generation. Recovering ~places +
factions is the intended effect, but it means:

- **Existing extraction tests** that assert the old dropped behavior or specific
  entity counts will change — update them to the correct behavior (do not weaken
  assertions; assert the new, correct outputs).
- **End-to-end verification is mandatory** (this is a foundational-stage change):
  re-run extraction on the committed book and confirm `places_full.json` now
  contains real places (Endovier, Rifthold, …), `orgs_full.json` contains the
  factions, and Arobynn is `PERSON` — then confirm the full `pytest -q` suite is
  green.

## Files

- Modify: `scripts/entity_extraction.py` (label maps; retag rule + docstring)
- Test: `tests/test_entity_extraction.py` (or the existing retag/label tests) —
  label-map assertions; retag-keeps-PERSON test; update any test asserting the
  old dropped/retagged behavior.

## Testing strategy

- `LABEL_TO_TYPE`/`KEPT_LABELS`: `FACTION→ORG`, `PLACE→PLACE`, `EVENT→EVENT`
  present; `KEPT_LABELS` contains all three; standard labels still map.
- `_retag_entity_type_from_context`: a PERSON with a place-dense context
  (Arobynn fixture: `raw_mentions=["Arobynn Hamel"]`, a mentions_by_chapter
  sentence with `keep`/`border`/`river` place cues) returns `PERSON`, not
  `PLACE`. The ORG/PLACE→PERSON and PERSON→EVENT rules still fire on their
  fixtures.
- End-to-end (manual, gated by model availability): re-run extraction; assert
  real places/orgs recovered and Arobynn is PERSON.
