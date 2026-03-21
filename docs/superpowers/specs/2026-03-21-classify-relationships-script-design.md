# classify_relationships Script Design

## Goal

Replace the Studio-based relationship classification pipeline with a standalone Python script
that calls Ollama directly — same pattern as `generate_wiki_pages.py`.

## Context

The `wiki-resolution` pipeline's `relationship-extraction` stage has a `classify: true` option
that calls Ollama through Studio (`relationship-classifier-item.pipeline.yaml`) one pair at a
time. Each call spawns a Studio subprocess with JSONL logging and DB overhead, adding ~90s per
pair. With ~57 pairs, total time exceeds the 600s pipeline timeout.

`generate_wiki_pages.py` bypasses Studio entirely by calling `POST /api/generate` via
`urllib.request` directly. This design applies the same approach to relationship classification.

## Architecture

### New file: `scripts/classify_relationships.py`

Standalone script. Reads `relationships.json` (output of `relationship-extraction` with
`classify: false`), classifies each pair via direct Ollama calls, writes
`relationships_classified.json`.

**CLI:**
```
python scripts/classify_relationships.py --book library/.../book.yaml
python scripts/classify_relationships.py --book library/.../book.yaml --model qwen2.5
python scripts/classify_relationships.py --book library/.../book.yaml --dry-run
```

**Input:** `processing_output/<slug>/relationships.json`
**Output:** `processing_output/<slug>/relationships_classified.json`

### Prompt

System prompt copied verbatim from `.studio/agents/relationship-classifier.agent.yaml`.
Per-pair user prompt: JSON object with `entity_a`, `entity_b`, `cooccurrence_count`,
`sample_contexts`, `novel_summary`.

### Retry loop (per pair, max 3 attempts)

```python
for attempt in range(MAX_ATTEMPTS):
    raw = call_ollama(prompt, model)
    result = parse_json(raw)
    errors = validate_classification(result, pair)
    if not errors:
        break
# Fallback: keep original pair unclassified if all attempts fail
```

### Validation

Import validation functions from `scripts/relationship_classifier_validator.py` directly
(no subprocess). Functions used:
- `check_relationship_type_valid`
- `check_evidence_contains_both_names`
- `check_key_moments_format`
- Any other `check_*` functions exported by the validator

### Filtering (`_should_classify_pair`)

Copy `_should_classify_pair` logic from `relationship_extraction.py`: skip pairs where
either entity has type `PLACE` or `OTHER`. Entity types read from `entities` list in
`relationships.json`.

### Ollama call

```python
def call_ollama(prompt: str, model: str, timeout: int = 120) -> str | None:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read()).get("response", "")
```

## Makefile target

```makefile
classify-relationships:
    python scripts/classify_relationships.py --book $(BOOK)
```

Added to the `.PHONY` list.

## What does NOT change

- `relationship_extraction.py`: `classify_relationships()` and `_run_studio_classifier_item`
  remain intact (used by `--classify` CLI flag and existing tests)
- `relationship-classifier-item.pipeline.yaml`: not touched
- `relationship_classifier_validator.py`: imported, not duplicated
- Book YAML: `classify: false` stays during `wiki-resolution`; classification is now a
  separate explicit step

## Testing

- Unit tests in `tests/test_classify_relationships.py`
- Test: dry-run produces stubs with `relationship_type: null`
- Test: validation rejects invalid `relationship_type`
- Test: retry loop calls Ollama up to 3x on failure, then falls back gracefully
- Test: `_should_classify_pair` skips PLACE/OTHER entities
- Integration: `pytest -q` must stay green
