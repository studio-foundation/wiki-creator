# Design: Split wiki-pipeline into 3 pipelines + orchestrator (STU-243)

## Problem

`wiki-pipeline` runs 10+ stages end-to-end. If wiki-generation crashes, the full 40+ min extraction is re-run. No restart points, no retry granularity.

## Solution

Split into 3 independent Studio pipelines orchestrated by `run_wiki.py`.

---

## Pipeline Split

### `wiki-extraction.pipeline.yaml` — run once, never rerun

Stages: `epub-parse → entity-extraction → entity-clustering → split-clusters`

- Identical to the first 4 stages of the current `wiki-pipeline`
- Output: `processing_output/splits.json` (written by orchestrator after run completes)

### `wiki-resolution.pipeline.yaml` — run once, re-runnable independently

Stages: `entity-resolution (parallel group, 5 types) → merge-entities → relationship-extraction → entity-classification`

- Reads `processing_output/splits.json` via `additional_context` in input YAML
- Output: `processing_output/entities_classified.json` (written by orchestrator)

### `wiki-generation.pipeline.yaml` — fully re-runnable, batchable

Stages: `wiki-preparation → wiki-generation (writer-lite) → wiki-export`

- Reads `processing_output/entities_classified.json` via `additional_context`
- `wiki-preparation` already handles batch splitting (no separate `batch-calculation` script needed)
- `wiki-generation` uses `writer-lite` agent (specialized, single-purpose)
- Replaces/absorbs the existing `wiki-page.pipeline.yaml`

---

## Inter-Pipeline Data Handoff

Each pipeline reads predecessor output from `processing_output/` on disk, not from Studio's internal run state. The orchestrator writes these files after each pipeline completes.

```
processing_output/
  splits.json                 ← written after wiki-extraction completes
  entities_classified.json    ← written after wiki-resolution completes
```

Scripts that currently read from `previous_outputs["entity-classification"]` will read from `payload["additional_context"]` (file path injected by the orchestrator into the input YAML).

---

## Orchestrator: `run_wiki.py`

Single script at project root. Manages the 3-pipeline sequence.

### State file: `.wiki_runs/<book_slug>/current_run.json`

```json
{
  "book": "le-jeu-de-lange",
  "stages": {
    "wiki-extraction": {"status": "completed", "run_id": "..."},
    "wiki-resolution": {"status": "completed", "run_id": "..."},
    "wiki-generation": {"status": "failed", "attempt": 2}
  }
}
```

### CLI flags

```bash
python run_wiki.py --book books/le-jeu-de-lange.yaml            # full run
python run_wiki.py --book books/le-jeu-de-lange.yaml --restart wiki-resolution
python run_wiki.py --book books/le-jeu-de-lange.yaml --batch 0,2,5
python run_wiki.py --book books/le-jeu-de-lange.yaml --retries 5
python run_wiki.py --book books/le-jeu-de-lange.yaml --status
```

### Behaviour

- **Progress tracking**: reads/writes `.wiki_runs/<slug>/current_run.json`
- **Restart**: skips already-completed pipelines; `--restart wiki-resolution` forces re-run from that point
- **Retry**: max 3 attempts per pipeline (configurable with `--retries`); on failure, updates state and aborts (or continues with next pipeline if non-blocking)
- **Batch selection**: `--batch 0,2,5` injects a `batch_filter` into the generation input YAML so `wiki-preparation` only emits the requested batches
- **Output extraction**: after each `studio run`, captures JSON output, extracts the relevant stage output field, writes to `processing_output/`

---

## Files to Create

| File | Description |
|------|-------------|
| `.studio/pipelines/wiki-extraction.pipeline.yaml` | Stages 1–4 of current wiki-pipeline |
| `.studio/pipelines/wiki-resolution.pipeline.yaml` | Stages 5–8 (resolution group + classification) |
| `.studio/pipelines/wiki-generation.pipeline.yaml` | Stages 9–11 (preparation + generation + export) |
| `run_wiki.py` | Orchestrator script |
| `books/carlos-ruiz-zafon/le-jeu-de-lange.yaml` | Book config file (input for orchestrator) |

## Files to Delete / Deprecate

| File | Action |
|------|--------|
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Delete (replaced by 3 pipelines) |
| `.studio/pipelines/wiki-page.pipeline.yaml` | Delete (absorbed into wiki-generation) |

## Files to Modify

| File | Change |
|------|--------|
| `scripts/wiki_preparation.py` | Read from `additional_context` (file path) instead of `previous_outputs["entity-classification"]`; support `batch_filter` param |
| `scripts/wiki_export.py` | Read from `additional_context` if needed |
| `scripts/relationship_extraction.py` | Read splits from `additional_context` |
| `scripts/entity_classification.py` | Read from `additional_context` |

---

## Acceptance Criteria (from STU-243)

- [ ] `wiki-extraction.yaml`: `epub-parse` → `split-clusters`
- [ ] `wiki-resolution.yaml`: `entity-resolution` (parallel) → `entity-classification`
- [ ] `wiki-generation.yaml`: `wiki-preparation` → `wiki-export`
- [ ] `processing_output/` with `splits.json` and `entities_classified.json`
- [ ] `run_wiki.py` with all flags functional
- [ ] Three pipelines run independently (E2E test)
- [ ] Progress logs saved in `.wiki_runs/`
