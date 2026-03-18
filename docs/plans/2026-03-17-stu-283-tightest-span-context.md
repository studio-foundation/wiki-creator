# STU-283 — relationship-classifier : fix sample_contexts (tightest span)

## Problem

`build_cooccurrence_graph` in `scripts/relationship_extraction.py` stores `window[0]` (the first sentence of the sliding window) as a `sample_context`. Since the window spans 5 sentences, `window[0]` may contain neither entity — leading the LLM classifier to invent relationship types from irrelevant text.

Examples from Run 7:
- `Dorian ↔ Hollin` (brothers) classified `"employeur/employé"` because the context described the King, not the siblings
- `Celaena ↔ Elena` (ancestor/mentor) classified `"employeur/employé"` from a context containing only Celaena's name

## Solution

**Option A — Tightest span**: replace `window[0]` with the minimal contiguous sub-sequence of the window that contains both entity names.

## Design

### New function

```python
def _tightest_span(window: list[str], name_a: str, name_b: str) -> str:
```

Logic:
1. Scan each sentence in `window` for `name_a` and `name_b` using the same `\b`-bounded case-insensitive regex used at detection time (line 166)
2. Find `idx_a` = index of first sentence containing A, `idx_b` = index of first sentence containing B
3. `span = window[min(idx_a, idx_b) : max(idx_a, idx_b) + 1]`
4. Return `" ".join(span)`
5. Fallback to `window[0]` if a name is not found in any sentence (safe default, should not occur)

### Call site

Replace in `build_cooccurrence_graph` (~line 179):

```python
# Before
cooc[key]["contexts"].append(window[0])

# After
cooc[key]["contexts"].append(_tightest_span(window, a, b))
```

### Scope

- **Modified file:** `scripts/relationship_extraction.py` only
- **Tests:** add/update in `tests/test_relationship_extraction.py` — assert that each string in `sample_contexts` contains both entity names
- **Schema:** unchanged — `sample_contexts` remains `list[str]`
- **cooccurrence_count:** unchanged — still counts all window hits

## What does NOT change

- LLM prompt and output schema
- Context count cap (`< 3`)
- All other fields in the relationship dict
