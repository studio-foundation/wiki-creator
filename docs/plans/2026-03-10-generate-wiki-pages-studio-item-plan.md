# Generate Wiki Pages Studio Item Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move `generate_wiki_pages.py` to Studio-validated one-entity subruns while preserving incremental save and resume behavior.

**Architecture:** `scripts/generate_wiki_pages.py` remains the outer resumable orchestrator and launches one Studio subrun per entity. The nested Studio pipeline owns LLM generation, schema validation, and Ralph retries; the outer script owns persistence, resume, local safety checks, and failed stub handling.

**Tech Stack:** Python 3, pytest, Studio pipeline YAML, Studio contracts, Ralph validation, JSON persistence

---

### Task 1: Add Failing Tests For Per-Entity Studio Runner Boundaries

**Files:**
- Modify: `tests/test_generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages.py`

**Step 1: Write the failing test**

Add tests for:
- using a replaceable item runner in place of direct Ollama calls
- appending one successful page and saving immediately
- resuming from existing `wiki_pages.json`
- writing a failed stub and debug artifact when the item runner fails

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages.py -q`
Expected: FAIL because the item runner boundary does not exist yet.

**Step 3: Write minimal implementation**

Refactor `scripts/generate_wiki_pages.py` to expose:
- one runner function per entity
- one converter from runner output to final page object
- one debug artifact writer

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_generate_wiki_pages.py -q`
Expected: PASS for the new orchestration tests.

**Step 5: Commit**

```bash
git add tests/test_generate_wiki_pages.py scripts/generate_wiki_pages.py
git commit -m "feat(wiki-pages): add per-entity studio runner boundaries"
```

### Task 2: Create Item-Level Page Contract

**Files:**
- Create: `.studio/contracts/wiki-page-item.contract.yaml`
- Modify: `tests/test_pipeline_configs.py`
- Test: `tests/test_pipeline_configs.py`

**Step 1: Write the failing test**

Assert that the contract file exists and requires:
- `title`
- `importance`
- `entity_type`
- `infobox_fields`
- `content`

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: FAIL because the contract file does not exist yet.

**Step 3: Write minimal implementation**

Create `.studio/contracts/wiki-page-item.contract.yaml` with the required fields.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add .studio/contracts/wiki-page-item.contract.yaml tests/test_pipeline_configs.py
git commit -m "feat(wiki-pages): add wiki page item contract"
```

### Task 3: Create Item-Level Studio Pipeline And Agent

**Files:**
- Create: `.studio/pipelines/wiki-page-item.pipeline.yaml`
- Create: `.studio/agents/wiki-page-item.agent.yaml`
- Modify: `tests/test_pipeline_configs.py`
- Test: `tests/test_pipeline_configs.py`

**Step 1: Write the failing test**

Assert that:
- the pipeline file exists and parses
- it uses `contract: wiki-page-item`
- it configures `ralph:`
- the agent file exists

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: FAIL because the pipeline and agent files do not exist yet.

**Step 3: Write minimal implementation**

Create the item pipeline and item agent with Studio-native JSON-only instructions.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_configs.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add .studio/pipelines/wiki-page-item.pipeline.yaml .studio/agents/wiki-page-item.agent.yaml tests/test_pipeline_configs.py
git commit -m "feat(wiki-pages): add studio item pipeline with ralph"
```

### Task 4: Wire `generate_wiki_pages.py` To Use Studio Item Runs

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Modify: `tests/test_generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages.py`

**Step 1: Write the failing test**

Add tests verifying:
- each entity in non-dry mode uses the Studio item runner
- successful item outputs are appended in the same outer `pages` format
- failed item outputs produce retryable `_failed` stubs

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages.py -q`
Expected: FAIL because direct Ollama calls are still used in generation mode.

**Step 3: Write minimal implementation**

Refactor `scripts/generate_wiki_pages.py` to:
- keep prompt construction local if needed for the item input
- call a new Studio item runner instead of `call_ollama`
- preserve `_save`, `_load_existing`, and retry semantics

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_generate_wiki_pages.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(wiki-pages): route entity generation through studio item runs"
```

### Task 5: Capture Studio Run Metadata And Debug Artifacts

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Modify: `tests/test_generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages.py`

**Step 1: Write the failing test**

Assert that failed item runs write debug artifacts containing:
- entity title
- failure code
- raw Studio JSON response
- nested run metadata (`run_id`, return code, command)

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages.py -q`
Expected: FAIL because debug artifacts do not yet include Studio metadata.

**Step 3: Write minimal implementation**

Add a debug artifact writer in `generate_wiki_pages.py` mirroring the pattern used in `chapter_summary.py`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_generate_wiki_pages.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(wiki-pages): log failed studio item runs"
```

### Task 6: Full Verification

**Files:**
- Modify: `tests/test_pipeline_configs.py`
- Test: `tests/test_generate_wiki_pages.py`
- Test: `tests/test_pipeline_configs.py`

**Step 1: Run the targeted suite**

Run: `pytest tests/test_generate_wiki_pages.py tests/test_pipeline_configs.py -q`
Expected: PASS.

**Step 2: Run the broader touched suite**

Run: `pytest tests/test_generate_wiki_pages.py tests/test_pipeline_configs.py tests/test_wiki_preparation.py tests/test_chapter_summary.py -q`
Expected: PASS.

**Step 3: Run YAML sanity checks**

Run:
```bash
python - <<'PY'
from pathlib import Path
import yaml
for path in sorted((Path('.studio/pipelines')).glob('*.pipeline.yaml')):
    yaml.safe_load(open(path, encoding='utf-8'))
    print(path.name, 'OK')
for path in sorted((Path('.studio/contracts')).glob('*.contract.yaml')):
    yaml.safe_load(open(path, encoding='utf-8'))
    print(path.name, 'OK')
PY
```
Expected: all files print `OK`.

**Step 4: Commit**

```bash
git add .studio/pipelines/wiki-page-item.pipeline.yaml .studio/contracts/wiki-page-item.contract.yaml .studio/agents/wiki-page-item.agent.yaml scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py tests/test_pipeline_configs.py
git commit -m "feat(wiki-pages): enable studio-validated per-entity generation"
```
