# Alias Resolution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a dedicated `alias-resolution` stage that conservatively merges PERSON aliases after cluster resolution while preserving downstream entity contracts.

**Architecture:** `scripts/resolve_clusters.py` remains a pure mapper. A new `scripts/alias_resolution.py` stage consumes its output plus book-specific PERSON mention registries, applies deterministic heuristics first, optionally supports a bounded LLM confirmation hook, and emits the same `entities` list shape for `merge-entities` to forward downstream.

**Tech Stack:** Python 3, pytest, Studio pipeline YAML, JSON entity registries, YAML payload parsing

---

### Task 1: Add Failing Tests For Stage Wiring

**Files:**
- Modify: `tests/test_merge_entities.py`
- Create: `tests/test_alias_resolution.py`
- Test: `tests/test_alias_resolution.py`
- Test: `tests/test_merge_entities.py`

**Step 1: Write the failing test**

Add tests covering:
- `merge-entities` prefers `alias-resolution` output when present
- the new stage passes non-PERSON entities through unchanged
- the new stage returns passthrough output when no alias evidence exists

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_alias_resolution.py tests/test_merge_entities.py -q`
Expected: FAIL because `scripts/alias_resolution.py` and the new merge preference do not exist yet.

**Step 3: Write minimal implementation**

Create a skeletal `scripts/alias_resolution.py` with a callable `resolve_aliases(...)` entrypoint and update `scripts/merge_entities.py` to prefer `alias-resolution`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_alias_resolution.py tests/test_merge_entities.py -q`
Expected: PASS for the wiring and passthrough tests.

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py scripts/merge_entities.py tests/test_alias_resolution.py tests/test_merge_entities.py
git commit -m "feat(alias-resolution): add stage boundary and merge wiring"
```

### Task 2: Add Failing Tests For Deterministic Alias Heuristics

**Files:**
- Modify: `tests/test_alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

**Step 1: Write the failing test**

Add tests for:
- explicit alias pattern merges two PERSON entities
- plain co-occurrence without reveal cues does not merge
- canonical-name selection prefers the more specific or more frequent name
- merged aliases and `source_ids` are deduplicated deterministically

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_alias_resolution.py -q`
Expected: FAIL because the scoring and merge logic is still stubbed.

**Step 3: Write minimal implementation**

Implement:
- mention-context loading from `persons_full.json`
- deterministic alias pattern detection
- conservative merge decisioning
- canonical-name and alias/source aggregation helpers

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_alias_resolution.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(alias-resolution): add deterministic person alias heuristics"
```

### Task 3: Add Failing Tests For Payload And File Loading Compatibility

**Files:**
- Modify: `tests/test_alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

**Step 1: Write the failing test**

Add tests covering:
- payload parsing from `additional_context.file_path`
- CLI/script stdin contract output shape
- graceful fallback when `persons_full.json` is missing

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_alias_resolution.py -q`
Expected: FAIL because file loading and script entrypoint handling are incomplete.

**Step 3: Write minimal implementation**

Add:
- `_paths_from_payload(...)`
- registry loading helper
- `main()` stdin/stdout handling with conservative passthrough on missing registry data

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_alias_resolution.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(alias-resolution): support studio payload and registry loading"
```

### Task 4: Wire The New Stage Into `wiki-resolution`

**Files:**
- Modify: `.studio/pipelines/wiki-resolution.pipeline.yaml`
- Modify: `tests/test_pipeline_configs.py`
- Test: `tests/test_pipeline_configs.py`

**Step 1: Write the failing test**

Assert that:
- `wiki-resolution.pipeline.yaml` contains an `alias-resolution` stage
- it appears after `resolve-clusters` and before `merge-entities`
- it runs `scripts/alias_resolution.py`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: FAIL because the new pipeline stage is not present yet.

**Step 3: Write minimal implementation**

Insert the new stage in `.studio/pipelines/wiki-resolution.pipeline.yaml` with `previous_stage_output` context.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add .studio/pipelines/wiki-resolution.pipeline.yaml tests/test_pipeline_configs.py
git commit -m "feat(alias-resolution): add wiki-resolution pipeline stage"
```

### Task 5: Add Optional LLM Hook Boundary Without Requiring It

**Files:**
- Modify: `scripts/alias_resolution.py`
- Modify: `tests/test_alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

**Step 1: Write the failing test**

Add tests verifying:
- medium-confidence candidates do not merge when the LLM hook is disabled
- an injectable LLM confirmer can approve a medium-confidence merge
- LLM errors degrade gracefully to no merge and increment stats

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_alias_resolution.py -q`
Expected: FAIL because there is no LLM confirmation boundary yet.

**Step 3: Write minimal implementation**

Implement:
- an optional injected confirmer callable
- medium-confidence gating
- stage stats for LLM attempts, confirmations, and failures

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_alias_resolution.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(alias-resolution): add optional llm confirmation hook"
```

### Task 6: Full Verification

**Files:**
- Test: `tests/test_alias_resolution.py`
- Test: `tests/test_merge_entities.py`
- Test: `tests/test_pipeline_configs.py`

**Step 1: Run the targeted suite**

Run: `pytest tests/test_alias_resolution.py tests/test_merge_entities.py tests/test_pipeline_configs.py -q`
Expected: PASS.

**Step 2: Run the broader shared-script suite**

Run: `pytest tests/test_alias_resolution.py tests/test_merge_entities.py tests/test_pipeline_configs.py tests/test_relationship_extraction.py tests/test_entity_classification.py -q`
Expected: PASS.

**Step 3: Run repo baseline verification**

Run: `pytest -q`
Expected: PASS.

**Step 4: Commit**

```bash
git add .studio/pipelines/wiki-resolution.pipeline.yaml scripts/alias_resolution.py scripts/merge_entities.py tests/test_alias_resolution.py tests/test_merge_entities.py tests/test_pipeline_configs.py docs/plans/2026-03-10-alias-resolution-architecture-design.md docs/plans/2026-03-10-alias-resolution-implementation.md
git commit -m "feat(alias-resolution): add conservative post-cluster alias merging"
```
