# STU-272: Novel Summary Anchor for Relationship Classifier

**Date:** 2026-03-17
**Issue:** [STU-272](https://linear.app/studioag/issue/STU-272/fix-relationship-type-diversifier-les-types-au-dela-de)

## Problem

The `relationship-classifier` returns `employeur/employé` for nearly every pair because the LLM receives only isolated `sample_contexts` excerpts with no narrative grounding. Without knowing the story, the model defaults to the statistically most frequent relationship type it can infer from supervision/guard/competition co-occurrences.

## Solution

Add an optional `novel_summary` field (5–10 lines of plain prose) to the book YAML. This summary is passed through `additional_context` into the classifier prompt, anchoring the LLM in the narrative reality of the book before it sees the per-pair excerpts.

## Data & Config

### Book YAML

Add optional `novel_summary` field:

```yaml
novel_summary: |
  Celaena Sardothien is a legendary assassin serving as a slave in the salt mines of Endovier.
  Prince Dorian offers her freedom if she competes in a tournament to become the king's Champion.
  Captain Chaol Westfall escorts and trains her. Dorian and Chaol are close friends.
  Duke Perrington serves as the king's enforcer and antagonist to Celaena.
  The tournament pits competitors against each other in deadly trials.
```

If absent, the classifier falls back to current behavior (no summary injected — backward-compatible).

### `additional_context` flow

`novel_summary` is read in the same `yaml.safe_load` block as `classify`, `llm_model`, `workers`, etc. in `relationship_extraction.py`. No new config channel needed.

## Classifier Prompt Change

`classify_relationships()` gains an optional `novel_summary: str | None = None` parameter. When provided, the prompt is prefixed with:

```
Contexte du roman :
<novel_summary>

Voici des extraits où deux personnages apparaissent ensemble.
...
```

Call site in the stdin handler passes `novel_summary` from `additional_context`.

## Agent YAML

`relationship-classifier.agent.yaml` system prompt updated to mention that input may contain a `novel_summary` field for narrative context.

## Testing

- Unit test: assert `novel_summary` text appears in the built prompt when provided
- Unit test: assert prompt is unchanged when `novel_summary` is absent (backward compat)

## Acceptance Criteria

- `ami` appears for Chaol/Dorian
- `antagoniste` appears for Duke Perrington/Celaena
- Types `amoureux`, `allié`, `famille` appear in results with realistic distribution
- All existing tests pass (`pytest -q`)
