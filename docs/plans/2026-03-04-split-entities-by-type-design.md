# Design — Split entities_full by type

**Date:** 2026-03-04

## Context

`entity_extraction.py` currently writes a single `entities_full.json` containing all entity types (PERSON, PLACE, ORG) merged together. The `writer.agent.yaml` reads this file to correlate resolved entities with their context sentences.

## Goal

Split `entities_full.json` into three separate files by entity type:
- `persons_full.json`
- `places_full.json`
- `orgs_full.json`

## Design

### Approach A — New `split_by_type` function (selected)

Add a dedicated `split_by_type(entities_full: dict) -> dict[str, dict]` function in `entity_extraction.py` that partitions the full entity registry by type. The existing `split_entities` function remains unchanged.

### Changes

#### `scripts/entity_extraction.py`

New function:
```python
def split_by_type(entities_full: dict) -> dict[str, dict]:
    result = {"PERSON": {}, "PLACE": {}, "ORG": {}}
    for entity_id, entity in entities_full.items():
        t = entity.get("type", "OTHER")
        if t in result:
            result[t][entity_id] = entity
    return result
```

In `main()`, replace the single `entities_full.json` write with three writes:
- `persons_full.json` → `{"persons_full": {entity_id: {...}}}`
- `places_full.json` → `{"places_full": {entity_id: {...}}}`
- `orgs_full.json` → `{"orgs_full": {entity_id: {...}}}`

#### `.studio/agents/writer.agent.yaml`

Update system prompt to read 3 files instead of 1:
- `repo_manager-read_file("persons_full.json")`
- `repo_manager-read_file("places_full.json")`
- `repo_manager-read_file("orgs_full.json")`

The writer correlates resolved entities with context using `source_ids` — it looks up each source_id in the file matching the entity's type.

### What does NOT change

- `split_entities` function (handles full/for-resolution split) — unchanged
- `entities_for_resolution` stdout output — unchanged
- Pipeline YAML — unchanged
- `run_test_mode` — updated to exercise `split_by_type` as well
