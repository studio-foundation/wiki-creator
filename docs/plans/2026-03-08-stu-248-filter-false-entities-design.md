# STU-248 — Filter false entities in relationship_extraction

**Date:** 2026-03-08
**Issue:** https://linear.app/studioag/issue/STU-248
**Branch:** `arianedguay/stu-248-filtrer-les-fausses-entites-dans-relationship_extraction`

---

## Problem

`relationship_extraction.py` produces co-occurrences with non-character entities. Example from A. C. Vidal in *Le Jeu de l'Ange*: `Sériez`, `Auriez`, `Avez`, `Regarde`, `Félicitations`, `Répétez-le-moi`, `Calmez`, `Allons`.

Root cause: `entity_extraction.py` captures capitalized tokens at sentence/dialogue start without verifying they are proper nouns. French verbs conjugated at the start of a dialogue line (`— Regarde`, `— Avez`) pass the NER stage and flow into the co-occurrence graph.

---

## Approach

**Option A selected:** POS filter using spaCy's already-computed POS tags — zero extra NLP cost, semantically correct, matches the issue spec exactly.

---

## Design

### Level 1 — `entity_extraction.py`: POS filter (post-NER)

Add `_is_valid_span(span) -> bool` alongside the existing `_is_valid_mention(text) -> bool`:

```python
_BAD_POS = frozenset({"VERB", "AUX", "ADJ", "ADV"})

def _is_valid_span(span) -> bool:
    tokens = list(span)
    if len(tokens) == 1:
        return tokens[0].pos_ not in _BAD_POS
    # Multi-token: syntactic head must not be a bad POS
    head = span.root
    return head.pos_ not in _BAD_POS or head.pos_ in {"PROPN", "NOUN"}
```

Call site in `extract_entities`, after `_truncate_mention` and `_is_valid_mention`:

```python
mention_text = _truncate_mention(ent)
if not _is_valid_mention(mention_text):
    continue
if not _is_valid_span(ent):   # uses original span, POS tags intact
    continue
```

The `--test` mode gets a capitalized French verb added to `TEST_CHAPTERS` to validate cross-language behavior.

### Level 2 — `relationship_extraction.py`: co-occurrence thresholds

Two new params in `build_cooccurrence_graph` (replacing `threshold`):

| Param | Default | Description |
|-------|---------|-------------|
| `min_cooccurrence` | `3` | Minimum total co-occurrence count |
| `min_chapters_together` | `2` | Minimum distinct chapters the pair co-occurs in |

Filter in output loop:

```python
if data["count"] >= min_cooccurrence and len(data["chapters"]) >= min_chapters_together:
    relationships.append(...)
```

`threshold` is kept as a CLI alias for `min_cooccurrence` (backward compat). When `min_cooccurrence` is provided via YAML, it takes precedence.

YAML config (readable via `additional_context`):

```yaml
min_cooccurrence: 3
min_chapters_together: 2
```

Stats output gains two new fields: `min_cooccurrence`, `min_chapters_together`.

---

## Testing

### `entity_extraction.py --test`
- Add a capitalized French verb (`"— Regarde, il est là."`) to `TEST_CHAPTERS`
- Assert `Regarde` does not appear in extracted entities

### `relationship_extraction.py --test`
- Add a fake `"Regarde"` entity (type PERSON) to the test entities list with low co-occurrence
- Assert it does not appear in the output relationships
- Assert true pairs (Vidal ↔ Cristina, Vidal ↔ Martín) still appear

---

## Acceptance criteria (from issue)

- [ ] Relations de A. C. Vidal ne contiennent plus `Sériez`, `Auriez`, `Avez`, `Regarde`, `Félicitations`, `Répétez-le-moi`
- [ ] `min_cooccurrence` et `min_chapters_together` configurables dans l'input YAML
- [ ] `relationship_extraction.py --test` produit un graphe avec uniquement des noms propres reconnaissables
- [ ] Vraies relations (Vidal ↔ Cristina, Vidal ↔ Martín) non filtrées

---

## Files to modify

| File | Change |
|------|--------|
| `scripts/entity_extraction.py` | Add `_BAD_POS`, `_is_valid_span()`, call in `extract_entities`, update `--test` data |
| `scripts/relationship_extraction.py` | Replace `threshold` with `min_cooccurrence` + `min_chapters_together` in `build_cooccurrence_graph`, parse from YAML, update stats, update `--test` validation |
