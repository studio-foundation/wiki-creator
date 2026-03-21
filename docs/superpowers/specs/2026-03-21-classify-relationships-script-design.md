# classify_relationships Script Design

## Goal

Move relationship classification out of the `wiki-resolution` pipeline timeout into a
standalone Python script that calls `studio run relationship-classifier-item` for each pair,
saves incrementally, and supports resume.

## Context

The `wiki-resolution` pipeline's `relationship-extraction` stage times out (600s) when
`classify: true` because classification runs synchronously inside the pipeline stage.
With ~57 pairs at ~90s each via Studio, the total exceeds the timeout.

The fix is NOT to bypass Studio — Studio's ralph retry loop and validator give quality
guarantees we want to keep. The fix is to move the classification loop into a standalone
script that runs outside the pipeline timeout, saves after each pair, and can be resumed.

`_run_studio_classifier_item` already exists in `scripts/relationship_extraction.py` and
does exactly one Studio call per pair. The new script reuses it directly.

## Architecture

### New file: `scripts/classify_relationships.py`

Standalone script. Reads `relationships.json` (output of `relationship-extraction` with
`classify: false`), calls Studio for each eligible pair, writes
`relationships_classified.json`.

**CLI:**
```
python scripts/classify_relationships.py --book library/.../book.yaml
python scripts/classify_relationships.py --book library/.../book.yaml --dry-run
```

**Input:** `processing_output/<slug>/relationships.json`

Shape:
```json
{
  "entities": [{"canonical_name": "Celaena Sardothien", "type": "PERSON"}, ...],
  "relationships": [
    {
      "entity_a": "Celaena Sardothien",
      "entity_b": "Dorian",
      "cooccurrence_count": 61,
      "chapters": ["C25.xhtml", ...],
      "sample_contexts": ["excerpt...", ...]
    }
  ],
  "stats": {...},
  "narrator": null
}
```

**Output:** `processing_output/<slug>/relationships_classified.json`

Same structure. Each classified relationship is enriched with:
`relationship_type`, `direction`, `evolution`, `key_moments`, `evidence`.
Pairs that fail Studio classification are written as-is (original fields only).
Downstream consumers treat absent `relationship_type` as unclassified.

### Studio call (per pair)

Reuse `_run_studio_classifier_item` and `_should_classify_pair` imported directly from
`scripts/relationship_extraction.py`. No new LLM logic in this script.

```python
from scripts.relationship_extraction import (
    _run_studio_classifier_item,
    _should_classify_pair,
)

classification = _run_studio_classifier_item(
    pair,
    novel_summary=novel_summary or "",
    additional_context="",
)
if classification and not classification.get("error"):
    pair = {**pair, **classification}
```

Studio handles: model selection, ralph retries, validation loop, JSONL logging.

### Filtering

`_should_classify_pair(pair, entity_types)` from `relationship_extraction.py`:
skips pairs where either entity has type `PLACE` or `OTHER`.

Entity types built from the `entities` list in `relationships.json`:
```python
entity_types = {e["canonical_name"]: e.get("type", "") for e in data["entities"]}
```

### novel_summary

Read from the book YAML field `novel_summary`. If absent, `None`, or empty string,
passed as empty string `""` to `_run_studio_classifier_item` (which expects a string).

### Resume / incremental save

Same pattern as `generate_wiki_pages.py`:
- On startup, if `relationships_classified.json` already exists, load it and skip pairs
  whose `(entity_a, entity_b)` key is already present.
- After each pair is processed (success or fallback), write the full output file.
- On `KeyboardInterrupt`, catch and write final state before exiting.
- Malformed pairs in the resume file (missing `entity_a`/`entity_b`) are skipped
  individually, not cause a full reset.

Identity key: `(rel["entity_a"], rel["entity_b"])` tuple.

### Dry-run mode

With `--dry-run`, skip all Studio calls. Each relationship is output as-is.

## Makefile targets

```makefile
classify-relationships:
    python scripts/classify_relationships.py --book $(BOOK)

classify-relationships-dry:
    python scripts/classify_relationships.py --book $(BOOK) --dry-run
```

Added to the `.PHONY` list.

## What does NOT change

- `relationship_extraction.py`: unchanged — `_run_studio_classifier_item`,
  `_should_classify_pair`, `classify_relationships()` all remain
- `relationship-classifier-item.pipeline.yaml`: unchanged
- Book YAML: `classify: false` stays during `wiki-resolution`; classification is now a
  separate explicit step via `make classify-relationships`

## Testing

- Unit tests in `tests/test_classify_relationships.py`
- Test: `_load_done_keys` returns empty on missing file
- Test: `_load_done_keys` returns existing pairs and keys
- Test: `_load_done_keys` returns empty on corrupt file (not full reset on single bad pair)
- Test: `_save` writes valid JSON with correct structure
- Test: dry-run produces output without classification fields, no Studio calls
- Integration: `pytest -q` must stay green
