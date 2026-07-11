# STU-439 — Reconnect the custom NER ontology (PLACE/EVENT/FACTION) in entity extraction

**Linear:** [STU-439](https://linear.app/studioag/issue/STU-439/ner-maison-wiki-ner-en-a-moitie-debranche-kept-labels-jette)
**Date:** 2026-07-11
**Status:** Design approved, ready for planning

## Problem

The fine-tuned NER model `models/wiki-ner-en/model-best` emits the
fiction-native ontology `PERSON / PLACE / ORG / FACTION / EVENT`
(`meta.json` labels, `ner_dataset_generation.py:15-28`), but
`scripts/entity_extraction.py` predates it and only knows the stock
spaCy ontologies:

1. `KEPT_LABELS = {"PER", "LOC", "ORG", "PERSON", "GPE", "FAC", "NORP"}`
   (line 122) contains **neither PLACE, nor EVENT, nor FACTION**. At the
   `if ent.label_ not in KEPT_LABELS: continue` filter (line 581), every
   PLACE/EVENT/FACTION entity from the custom model is **silently
   dropped**. On `01-throne-of-glass` (configured on this model), only
   PERSON and ORG survive — 3/5 of the ontology of a model with a
   reported global f=0.98 (f=1.0 on PLACE) is neutralized.
2. `LABEL_TO_TYPE` (lines 124-132) does not map those labels either.
3. The custom model is a `['tok2vec','ner']` pipeline **without a POS
   tagger**, so the `_BAD_POS` filters in `_is_valid_span`
   (lines 304-337) are silent no-ops: `tok.pos_` is empty, never in
   `_BAD_POS`, and the anti-dialogue-verb compensation never fires.

Likely a contributing cause of STU-431 (King of Adarlan filtered out)
and of missing entities in recent validation runs.

## Decisions taken

| Decision | Choice | Rationale |
|---|---|---|
| FACTION mapping | **FACTION → ORG** | The downstream type vocabulary is frozen at `PERSON/PLACE/ORG/EVENT/OTHER` (`wiki_creator/types.py:22` Literal, plus split_clusters, resolve_clusters, entity_classification, wiki_preparation…). A dedicated FACTION type would ripple through ~8 files and `md2wiki.py` has no FACTION page template. ORG is semantically closest ("groups/orders/guilds that are not formal ORGs"). `entity_classification` can still reclassify later. |
| POS filters without tagger | **Explicit skip + warning** | Detect the missing tagger at model load, log one clear warning, and explicitly short-circuit the `_BAD_POS` check when the doc has no POS annotation. Sourcing a stock tagger into the custom pipeline requires `replace_listeners` (fragile) and costs per-chapter perf; retraining the model with a tagger is out of scope for a 3-point fix (candidate follow-up issue). Observable behaviour is unchanged — but documented and logged instead of silent. |

## Design

All changes in `scripts/entity_extraction.py` unless noted.

### 1. Label mapping (the core fix)

- `KEPT_LABELS` += `PLACE`, `EVENT`, `FACTION`.
- `LABEL_TO_TYPE` += `PLACE → PLACE`, `EVENT → EVENT`, `FACTION → ORG`.
- No behaviour change for stock spaCy models (they never emit these
  labels). For the custom model, PLACE/EVENT entities flow into the
  registry with their own types and FACTION entities flow in as ORG.

### 2. Silent-drop safety net

At model load time, compare the model's NER labels
(`nlp.get_pipe("ner").labels`, when a `ner` pipe exists) against
`KEPT_LABELS`; any label the model can emit that is not in
`KEPT_LABELS` triggers a single `logger.warning` listing the dropped
labels. A future custom ontology can no longer be disconnected
silently.

### 3. Explicit POS no-op (not silent)

- At model load time, if no POS-producing component (`tagger` or
  `morphologizer`) is in `nlp.pipe_names`, log one
  `logger.warning` ("POS filters disabled: model has no tagger …").
- In `_is_valid_span`, explicitly skip the `_BAD_POS` checks when the
  doc carries no POS annotation (`span.doc.has_annotation("POS")`).
  The dialogue-dash rejection does **not** depend on POS and stays
  active in all cases.

### 4. Tests (`tests/`, existing style)

- PLACE/EVENT/FACTION labels are kept and typed PLACE/EVENT/ORG
  respectively.
- A warning is emitted when a loaded model exposes an NER label outside
  `KEPT_LABELS`.
- A warning is emitted when the loaded pipeline has no tagger.
- `_is_valid_span` accepts a verb-like span when POS is absent
  (assumed no-op) and rejects it when POS is present.
- The dialogue-dash rejection still rejects, tagger or no tagger.

## Out of scope

- Retraining `wiki-ner-en` with a tagger (candidate follow-up issue).
- A dedicated downstream FACTION type.
- STU-431 itself — only note in that issue if this fix contributes.

## Error handling

No new failure modes: both safety nets are warnings, never raises. A
model with no `ner` pipe (theoretical) skips the label audit.

## Success criteria

- `pytest -q` green (baseline: 878 passed in the worktree).
- On a custom-model run, PLACE/EVENT/FACTION mentions appear in the
  extraction registry (FACTION as type ORG).
- Loading the custom model logs the no-tagger warning; loading a model
  with out-of-`KEPT_LABELS` labels logs the drop warning.
