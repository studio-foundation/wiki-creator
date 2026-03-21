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

Same structure as input but each relationship enriched with:
`relationship_type`, `direction`, `evolution`, `key_moments`, `evidence`.
Pairs that fail all 3 attempts are written as-is (original fields only, no classification
fields added, no crash). Downstream consumers should treat absent `relationship_type` as unclassified.

### Resume / incremental save

Same pattern as `generate_wiki_pages.py`:
- On startup, if `relationships_classified.json` already exists, load it and skip pairs whose
  `(entity_a, entity_b)` key is already present (regardless of whether they were classified or not).
- After each pair is processed (success or fallback), write the full output file immediately.
- On `KeyboardInterrupt`, catch and write final state before exiting.

Identity key for deduplication: `(rel["entity_a"], rel["entity_b"])` tuple.

### novel_summary

Read from the book YAML field `novel_summary` (same YAML loaded via `--book`). Passed as-is
in the per-pair prompt. If the field is absent, `None`, or empty string, it is omitted from
the prompt entirely.

### Prompt

`SYSTEM_PROMPT` = verbatim content from `.studio/agents/relationship-classifier.agent.yaml`
`system_prompt` field (hardcoded as a module-level constant).

Per-pair user message: JSON object with `entity_a`, `entity_b`, `cooccurrence_count`,
`sample_contexts`, `novel_summary`.

### Ollama call

```python
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MAX_ATTEMPTS = 3

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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None  # OSError covers socket.timeout; URLError covers connection errors
```

### Retry loop (per pair, max 3 attempts)

```python
for attempt in range(MAX_ATTEMPTS):
    raw = call_ollama(prompt, model)
    if raw is None:
        continue
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        continue
    errors = validate_classification(result, pair)
    if not errors:
        rel = {**rel, **result}
        break
else:
    print(f"[WARN] classification failed for {pair['entity_a']}↔{pair['entity_b']}", file=sys.stderr)
    # pair kept as-is (unclassified)
```

### Validation

Import check functions directly from `scripts/relationship_classifier_validator.py` (no
subprocess, bypass `parse_payload`). Functions that exist and will be used:
- `check_relationship_type_valid(clf)`
- `check_evidence_contains_both_names(clf, meta)`
- `check_evolution_not_generic(clf)`

A local `validate_classification(result, pair)` function calls each, collects errors, returns list.

### Filtering (`_should_classify_pair`)

Skip pairs where either entity has type `PLACE` or `OTHER`. Entity types built from the
`entities` list in `relationships.json`:
```python
entity_types = {e["canonical_name"]: e["type"] for e in data["entities"]}
```
Logic copied from `_should_classify_pair` in `relationship_extraction.py`.

### Dry-run mode

With `--dry-run`, skip all Ollama calls. Each relationship is output as-is (no classification
fields added). Useful for verifying paths and input parsing without a running model.

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
- Book YAML `classify` flag: keep `classify: false` in `wiki-resolution`; the new script is
  the explicit classification step. The `classify: true` path in `relationship_extraction.py`
  remains available for CLI use but is no longer the recommended flow.

## Testing

- Unit tests in `tests/test_classify_relationships.py`
- Test: dry-run writes output without classification fields, no Ollama calls
- Test: `validate_classification` rejects invalid `relationship_type`
- Test: retry loop keeps pair unclassified after 3 consecutive `None` returns from Ollama
- Test: `_should_classify_pair` skips PLACE/OTHER entities
- Integration: `pytest -q` must stay green
