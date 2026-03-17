# STU-274 — Add `evidence` field to reduce relationship hallucinations

## Problem

The `evolution` field in relationship classification hallucinates narrative arcs not supported by the provided excerpts. The LLM extrapolates freely because no grounding is required before concluding.

## Fix

Add an `evidence` field as the first key in the classification JSON schema. Placing it first forces chain-of-thought: the model must cite a supporting excerpt before assigning a `relationship_type` or writing `evolution`.

Two rule lines are appended to the prompt to constrain `evolution` further.

## Changes

### `scripts/relationship_extraction.py` — prompt

Update the JSON schema in `classify_relationships()`:

```json
{
  "evidence": "une phrase : ce que dans les extraits justifie directement le relationship_type",
  "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre",
  "direction": "symétrique|A→B|B→A",
  "evolution": "en une phrase, comment la relation évolue",
  "key_moments": ["chXX: description courte"]
}
```

Add after the schema:

```
Règles :
- evolution doit être directement inférable des extraits fournis, non inventée
- Si aucune évolution n'est observable, écris "relation stable dans les extraits fournis"
```

### `scripts/relationship_extraction.py` — output handling

Read `evidence` from the classification dict and store it in the relationship dict alongside the other LLM-filled fields.

### `wiki_creator/types.py`

Add `evidence: str | None = None` to `RelationshipEntry`.

### `tests/test_relationship_extraction.py`

Update `test_classify_relationships_populates_type_on_success` mock response to include `"evidence"` and assert it is stored on the result.

## Acceptance criteria

- `evidence` is present and coherent with `relationship_type` in LLM output
- `evolution` no longer contains invented arcs without excerpt support
- `pytest -q` passes
