# Alias Resolution Architecture Design

**Date:** 2026-03-10  
**Scope:** Add a dedicated post-cluster alias-resolution stage in `wiki-resolution` to conservatively merge PERSON entities that represent nicknames, reveal names, or explicit renamings.

## Problem
`scripts/resolve_clusters.py` currently performs a pure mapping from split clusters to resolved entities. That is the right contract for fuzzy clustering, but it leaves unresolved cases where the same character is introduced under unrelated proper names or later revealed under a different identity. Those cases produce duplicate PERSON pages, split relationship counts, and fragmented mention totals downstream.

The repo already expects the resolved entity shape to carry:
- `canonical_name`
- `aliases`
- `type`
- `source_ids`
- `relevant`

The architecture should preserve that contract and avoid folding nickname inference into cluster mapping or downstream relationship logic.

## Decision
Add a new `alias-resolution` stage after `resolve-clusters` and before `merge-entities` in `.studio/pipelines/wiki-resolution.pipeline.yaml`.

This stage will:
- read the resolved entity list from `resolve-clusters`
- load raw PERSON mention context from `processing_output/persons_full.json`
- score candidate PERSON-to-PERSON merges conservatively
- merge only when evidence is strong
- emit the same entity list shape, with optional audit metadata that downstream code may ignore

`merge-entities` will prefer `alias-resolution` output when present and otherwise keep its current fallback behavior.

## Why This Placement
### Not in `resolve-clusters`
`resolve-clusters` is intentionally a pure mapper. Extending it with nickname and reveal heuristics would mix two unrelated concerns:
- fuzzy co-reference clustering based on surface similarity
- semantic identity resolution across unrelated names

That would make the stage harder to reason about and harder to test.

### Not in `merge-entities`
`merge-entities` is currently a composition boundary. Turning it into a heuristic merge stage would make its name misleading and would blur whether a merge came from cluster resolution or alias inference.

### Dedicated boundary
A dedicated stage keeps the heuristic bounded, makes STU-252 easier to build on later, and lets us add an optional LLM fallback without disturbing the rest of the pipeline.

## Data Flow
Input to `alias-resolution`:
- `previous_outputs.resolve-clusters.entities`
- `additional_context.file_path` for locating book-specific processing outputs
- `processing_output/persons_full.json` for mention windows by chapter

Output from `alias-resolution`:
```json
{
  "entities": [
    {
      "canonical_name": "Celaena Sardothien",
      "type": "PERSON",
      "aliases": ["Celaena", "Lillian Gordaina"],
      "source_ids": ["entity_001", "entity_044"],
      "relevant": true,
      "alias_resolution": {
        "merged_from": ["Lillian Gordaina"],
        "evidence": [
          {
            "method": "pattern",
            "confidence": "high",
            "snippet": "You may call me Lillian Gordaina."
          }
        ],
        "confidence": "high",
        "method": "pattern"
      }
    }
  ],
  "narrator": null,
  "stats": {
    "candidates_considered": 12,
    "merges_applied": 2,
    "merges_by_method": {
      "pattern": 1,
      "cooccurrence": 0,
      "llm": 1
    },
    "ambiguous_pairs": 3,
    "llm_attempts": 1,
    "llm_confirmed": 1,
    "llm_failed": 0
  }
}
```

Downstream compatibility rules:
- `entities` remains the primary contract
- `narrator` remains passthrough
- `stats` is additive and optional
- per-entity `alias_resolution` metadata is additive and optional

## Stage Algorithm
The stage is PERSON-scoped. Non-PERSON entities pass through unchanged.

### 1. Candidate generation
Build bounded PERSON-to-PERSON candidate pairs using cheap filters:
- skip entities already sharing normalized canonical/alias surface forms
- skip irrelevant entities
- prefer pairs with overlapping chapter coverage from source mentions
- prefer pairs with nearby first-seen chapters or shared chapter neighborhoods
- allow explicit textual trigger matches to force consideration even when overlap is sparse

The goal is to avoid all-pairs comparison on large books.

### 2. Deterministic scoring
Apply two heuristic families.

#### Explicit alias pattern detector
Look for mention snippets containing clear identity cues, for example:
- `X, also known as Y`
- `formerly known as`
- `called her Y`
- `you may call me Y`
- equivalent French formulations where practical

This is the strongest signal and may produce immediate high-confidence merges.

#### Reveal/co-occurrence detector
Look for reveal-style contexts where two PERSON entities co-occur with cue words suggesting identity rather than ordinary interaction.

This detector must not merge on plain co-occurrence alone. Co-occurrence becomes actionable only when paired with reveal language or repeated strong local evidence.

### 3. Optional LLM fallback
Only candidate pairs in a medium-confidence band may invoke the optional LLM path.

LLM input should be tightly scoped:
- candidate entity A
- candidate entity B
- canonical names and aliases
- a short list of supporting snippets

LLM output target:
```json
{
  "same_person": true,
  "confidence": "medium",
  "evidence": "brief rationale"
}
```

If the LLM hook is disabled, unavailable, times out, or returns invalid output, the stage keeps deterministic results only and records the failure in stage stats.

## Merge Policy
Bias toward false negatives over false positives.

Rules:
- deterministic `high` confidence merges automatically
- deterministic `medium` confidence merges only with LLM confirmation
- deterministic `low` confidence never merges automatically
- non-PERSON pairs are never considered

Canonical name selection should prefer:
1. the more frequent name across source mentions
2. then the more specific multi-token name
3. then a stable lexical tie-breaker

All alternate names must be preserved in `aliases`, deduplicated and sorted deterministically.

## Error Handling
The stage must not fail the pipeline because alias evidence is uncertain.

Hard failures are reserved for:
- malformed stage input
- unreadable required registry files
- broken payload contracts

Soft failures include:
- no usable PERSON registry data
- invalid optional LLM response
- timeout or runtime errors in optional LLM execution

Soft failures should:
- log to stderr
- record counters in `stats`
- continue with deterministic passthrough behavior

## Testing Strategy
### Unit tests
Cover:
- explicit alias-pattern merges for PERSON entities
- plain co-occurrence does not merge
- reveal-style repeated evidence can merge
- canonical-name selection is deterministic
- non-PERSON entities pass through untouched

### Stage tests
Cover:
- passthrough when no candidates exist
- merged `canonical_name`, `aliases`, and `source_ids`
- additive audit metadata does not break downstream consumers
- LLM path is skipped cleanly when disabled
- LLM path only affects medium-confidence candidates

### Pipeline wiring tests
Cover:
- `wiki-resolution.pipeline.yaml` contains `alias-resolution` in the correct order
- `merge-entities` prefers `alias-resolution` output when present
- `relationship_extraction.py` still consumes the same effective entity shape via `merge-entities`

## Acceptance Criteria
- A dedicated `alias-resolution` stage exists in `wiki-resolution`
- PERSON alias merges are conservative and evidence-driven
- Existing downstream scripts continue to work without required contract changes
- Audit metadata is available for debugging but optional for consumers
- Optional LLM support is architected as a bounded fallback, not a requirement for deterministic operation
