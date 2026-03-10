# Chapter Summary Studio Ralph Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move chapter-summary LLM generation to Studio/Ralph per chapter while preserving incremental save and resume behavior.

**Architecture:** `scripts/chapter_summary.py` remains the outer incremental orchestrator and launches a nested Studio pipeline for one chapter at a time. The nested pipeline owns LLM generation plus contract validation and Ralph retries; the outer script owns aggregate persistence, resume behavior, debug logging, and extractive fallback.

**Tech Stack:** Python 3, pytest, Studio pipeline YAML, Studio contracts, Ralph validation, JSON file persistence

---

### Task 1: Add Failing Tests For Nested Per-Chapter Execution

**Files:**
- Modify: `tests/test_chapter_summary.py`
- Test: `tests/test_chapter_summary.py`

**Step 1: Write the failing tests**

Add tests for:
- launching a nested item runner in `llm` mode and saving immediately after one successful chapter
- resuming from existing `chapter_summaries.json` without rerunning completed chapters
- logging a debug artifact when the nested item runner fails
- falling back to extractive after nested runner failure

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_summary.py -q`
Expected: FAIL because nested Studio runner helpers do not exist yet.

**Step 3: Write minimal implementation**

In `scripts/chapter_summary.py`, introduce helper boundaries only:
- a function that runs one chapter through Studio
- a function that converts item output into aggregate chapter summary entries
- incremental orchestration that uses the helper

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chapter_summary.py -q`
Expected: PASS for the new orchestration tests.

**Step 5: Commit**

```bash
git add tests/test_chapter_summary.py scripts/chapter_summary.py
git commit -m "feat(chapter-summary): add nested studio runner orchestration"
```

### Task 2: Create Item-Level Studio Contract

**Files:**
- Create: `.studio/contracts/chapter-summary-item.contract.yaml`
- Test: `tests/test_pipeline_configs.py`

**Step 1: Write the failing test**

Add a config test asserting:
- `.studio/contracts/chapter-summary-item.contract.yaml` exists
- it requires `chapter_id`, `chapter_title`, and `summary_bullets`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: FAIL because the contract file does not exist yet.

**Step 3: Write minimal implementation**

Create the contract file with a strict item schema comment and required fields.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: PASS for the new contract existence/shape assertion.

**Step 5: Commit**

```bash
git add .studio/contracts/chapter-summary-item.contract.yaml tests/test_pipeline_configs.py
git commit -m "feat(chapter-summary): add chapter summary item contract"
```

### Task 3: Create Item-Level Studio Pipeline With Ralph

**Files:**
- Create: `.studio/pipelines/chapter-summary-item.pipeline.yaml`
- Create: `.studio/agents/chapter-summary.agent.yaml`
- Modify: `tests/test_pipeline_configs.py`
- Test: `tests/test_pipeline_configs.py`

**Step 1: Write the failing test**

Add tests asserting:
- the item pipeline YAML exists and parses
- it contains a stage using `contract: chapter-summary-item`
- the LLM stage has a `ralph:` block

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: FAIL because the pipeline and agent files do not exist yet.

**Step 3: Write minimal implementation**

Create:
- `chapter-summary-item.pipeline.yaml`
- `chapter-summary.agent.yaml`

Ensure the pipeline accepts one chapter, uses the contract, and enables Ralph on the generation stage.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: PASS for the new pipeline assertions.

**Step 5: Commit**

```bash
git add .studio/pipelines/chapter-summary-item.pipeline.yaml .studio/agents/chapter-summary.agent.yaml tests/test_pipeline_configs.py
git commit -m "feat(chapter-summary): add item pipeline with ralph validation"
```

### Task 4: Wire `chapter_summary.py` To Launch Nested Studio Runs

**Files:**
- Modify: `scripts/chapter_summary.py`
- Test: `tests/test_chapter_summary.py`

**Step 1: Write the failing test**

Add tests that monkeypatch the nested runner and verify:
- `llm` mode uses the nested runner instead of direct Ollama HTTP
- successful item outputs are normalized into aggregate chapter summaries
- failure payloads create debug artifacts and fallback correctly

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_summary.py -q`
Expected: FAIL because the script still uses direct Ollama helpers for generation.

**Step 3: Write minimal implementation**

Refactor `scripts/chapter_summary.py` to:
- isolate current direct Ollama helper behind a replaceable interface
- call the nested Studio runner in `llm` mode
- keep extractive mode unchanged
- keep incremental save/resume unchanged

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chapter_summary.py -q`
Expected: PASS for all chapter summary tests.

**Step 5: Commit**

```bash
git add scripts/chapter_summary.py tests/test_chapter_summary.py
git commit -m "feat(chapter-summary): route llm mode through studio item runs"
```

### Task 5: Add Failure Logging And Run Metadata Capture

**Files:**
- Modify: `scripts/chapter_summary.py`
- Modify: `tests/test_chapter_summary.py`
- Test: `tests/test_chapter_summary.py`

**Step 1: Write the failing test**

Add tests asserting debug artifacts include:
- `chapter_id`
- `chapter_title`
- terminal error code
- nested run metadata when available
- raw invalid output when available

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chapter_summary.py -q`
Expected: FAIL because the artifact does not yet capture nested run metadata fully.

**Step 3: Write minimal implementation**

Extend the debug artifact writer to record nested run identifiers and terminal payload details returned by the Studio runner.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chapter_summary.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/chapter_summary.py tests/test_chapter_summary.py
git commit -m "feat(chapter-summary): log nested studio run failures"
```

### Task 6: Validate Pipeline Configuration And End-To-End Safety

**Files:**
- Modify: `tests/test_pipeline_configs.py`
- Test: `tests/test_pipeline_configs.py`
- Test: `tests/test_chapter_summary.py`

**Step 1: Write the verification checks**

Ensure coverage for:
- new pipeline YAML parses
- new contract file parses
- existing chapter-summary stages remain wired correctly
- item pipeline is referenced consistently

**Step 2: Run test to verify full suite**

Run: `pytest tests/test_pipeline_configs.py tests/test_chapter_summary.py tests/test_entity_extraction.py -q`
Expected: PASS.

**Step 3: Run a YAML sanity check**

Run:
```bash
python - <<'PY'
from pathlib import Path
import yaml
for path in sorted((Path('.studio/pipelines')).glob('*.pipeline.yaml')):
    yaml.safe_load(open(path, encoding='utf-8'))
    print(path.name, 'OK')
PY
```
Expected: all pipeline YAML files print `OK`.

**Step 4: Commit**

```bash
git add tests/test_pipeline_configs.py .studio/pipelines/chapter-summary-item.pipeline.yaml .studio/contracts/chapter-summary-item.contract.yaml .studio/agents/chapter-summary.agent.yaml scripts/chapter_summary.py tests/test_chapter_summary.py
git commit -m "feat(chapter-summary): enable studio-validated per-chapter summaries"
```
