# Split wiki-pipeline into 3 Pipelines Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Split the monolithic `wiki-pipeline` into three independent Studio pipelines (`wiki-extraction`, `wiki-resolution`, `wiki-generation`) orchestrated by `run_wiki.py`, enabling restart points, retry, and batch selection without re-running expensive upstream stages.

**Architecture:** Each pipeline writes its key output to `processing_output/` as a side effect (scripts already do this for `*_full.json` files). Subsequent pipelines start with thin "loader" stages (named identically to the original stages they replace) that read those files and re-emit the data — so all downstream stage lookups by name still work with zero changes to `wiki_preparation.py` or `wiki_export.py`.

**Tech Stack:** Python 3.11+, Studio YAML pipelines, argparse for `run_wiki.py`

---

## Task 1: Bootstrap — gitignore + processing_output/ dir

**Files:**
- Modify: `.gitignore`

**Step 1: Add entries to .gitignore**

Open `.gitignore` and append:
```
processing_output/
.wiki_runs/
```

**Step 2: Create processing_output directory**

```bash
mkdir -p processing_output
touch processing_output/.gitkeep
```

Add to gitignore exception so the directory is tracked but contents are not:
```
!processing_output/.gitkeep
```

**Step 3: Commit**

```bash
git add .gitignore processing_output/.gitkeep
git commit -m "chore: add processing_output/ and .wiki_runs/ to gitignore"
```

---

## Task 2: parse_epub.py — write side-effect to processing_output/epub_data.json

**Files:**
- Modify: `scripts/parse_epub.py`

**Context:** `parse_epub.py` is the first script in the pipeline. It outputs title, author, chapters, pov_detection. After wiki-extraction runs, the `wiki-generation` pipeline needs this data (for `wiki_export.py`). The script must write a copy to disk.

**Step 1: Locate the `main()` function in parse_epub.py**

Find the line where `json.dump(result, sys.stdout)` is called (near the end of `main()`).

**Step 2: Add file write before the stdout dump**

Add these lines immediately before the final `json.dump(result, sys.stdout)`:

```python
import os as _os
_os.makedirs("processing_output", exist_ok=True)
with open("processing_output/epub_data.json", "w", encoding="utf-8") as _f:
    import json as _json
    _json.dump(result, _f, ensure_ascii=False)
```

> Note: `result` is the dict built in `main()` that gets dumped to stdout. Add the file write just before the stdout dump.

**Step 3: Run parse_epub standalone to verify it doesn't crash**

```bash
echo '{"additional_context": "file_path: books/carlos-ruiz-zafon/le-jeu-de-lange.epub\nspacy_model: fr_core_news_lg\n", "previous_outputs": {}}' | python scripts/parse_epub.py > /dev/null
ls processing_output/epub_data.json
```

Expected: file exists with JSON content.

**Step 4: Commit**

```bash
git add scripts/parse_epub.py
git commit -m "feat(stu-243): parse_epub writes processing_output/epub_data.json"
```

---

## Task 3: split_clusters.py — write side-effect to processing_output/splits.json

**Files:**
- Modify: `scripts/split_clusters.py`

**Context:** `split_clusters.py` outputs the partitioned clusters needed by wiki-resolution. After wiki-extraction, `wiki-resolution` reads from `processing_output/splits.json`.

**Step 1: Locate the `main()` function in split_clusters.py**

Find the final `json.dump(result, sys.stdout, ensure_ascii=False)` call.

**Step 2: Add file write before stdout dump**

```python
import os as _os
_os.makedirs("processing_output", exist_ok=True)
with open("processing_output/splits.json", "w", encoding="utf-8") as _f:
    import json as _json
    _json.dump(result, _f, ensure_ascii=False)
```

**Step 3: Verify**

```bash
python scripts/split_clusters.py --help 2>/dev/null || echo "no --help, OK"
# The script only runs in Studio mode (reads from stdin), so just check syntax
python -c "import scripts.split_clusters"
```

**Step 4: Commit**

```bash
git add scripts/split_clusters.py
git commit -m "feat(stu-243): split_clusters writes processing_output/splits.json"
```

---

## Task 4: entity_classification.py — write side-effect to processing_output/entities_classified.json

**Files:**
- Modify: `scripts/entity_classification.py`

**Context:** `entity_classification.py` is the last stage of wiki-resolution. Its output is the input for `wiki-preparation` in wiki-generation. After wiki-resolution, `wiki-generation` reads from `processing_output/entities_classified.json`.

**Step 1: Locate `run_studio_mode()` in entity_classification.py**

Find the final `json.dump({...}, sys.stdout, ensure_ascii=False)` call in `run_studio_mode()`.

**Step 2: Build the output dict first, then write it twice**

The current code does `json.dump({"entities": enriched, "relationships": ..., ...}, sys.stdout, ...)`.
Refactor to assign to a variable first, then write to file AND stdout:

```python
output = {
    "entities": enriched,
    "relationships": relationships,
    "stats": {
        "principal": importance_counts.get("principal", 0),
        "secondary": importance_counts.get("secondary", 0),
        "figurant": importance_counts.get("figurant", 0),
        "ignored": importance_counts.get("ignored", 0),
        "thresholds_used": "auto" if thresholds_config == "auto" else "explicit",
    },
    "narrator": narrator,
}

import os as _os
_os.makedirs("processing_output", exist_ok=True)
with open("processing_output/entities_classified.json", "w", encoding="utf-8") as _f:
    json.dump(output, _f, ensure_ascii=False)

json.dump(output, sys.stdout, ensure_ascii=False)
```

**Step 3: Verify test mode still works**

```bash
python scripts/entity_classification.py --test
```

Expected: prints entity importance tiers, no errors.

**Step 4: Commit**

```bash
git add scripts/entity_classification.py
git commit -m "feat(stu-243): entity_classification writes processing_output/entities_classified.json"
```

---

## Task 5: Create loader scripts

**Files:**
- Create: `scripts/load_splits.py`
- Create: `scripts/load_epub_data.py`
- Create: `scripts/load_classified_entities.py`

**Context:** These are thin "loader" stages placed at the start of wiki-resolution and wiki-generation pipelines. They read a file from `processing_output/` and re-emit it as their output — so downstream stages see the data in `previous_outputs["<stage-name>"]` exactly as if the original stage had run in this pipeline.

**Step 1: Create scripts/load_splits.py**

```python
#!/usr/bin/env python3
"""
Loader stage for wiki-resolution pipeline.
Reads processing_output/splits.json and re-emits it as stage output.
Named 'split-clusters' in the pipeline so entity-resolution group conditions work unchanged.
"""
import json
import sys

def main() -> None:
    json.load(sys.stdin)  # consume stdin (Studio requires it)
    with open("processing_output/splits.json", encoding="utf-8") as f:
        data = json.load(f)
    json.dump(data, sys.stdout, ensure_ascii=False)

if __name__ == "__main__":
    main()
```

**Step 2: Create scripts/load_epub_data.py**

```python
#!/usr/bin/env python3
"""
Loader stage for wiki-generation pipeline.
Reads processing_output/epub_data.json and re-emits it as stage output.
Named 'epub-parse' in the pipeline so wiki_export.py finds it in previous_outputs.
"""
import json
import sys

def main() -> None:
    json.load(sys.stdin)  # consume stdin
    with open("processing_output/epub_data.json", encoding="utf-8") as f:
        data = json.load(f)
    json.dump(data, sys.stdout, ensure_ascii=False)

if __name__ == "__main__":
    main()
```

**Step 3: Create scripts/load_classified_entities.py**

```python
#!/usr/bin/env python3
"""
Loader stage for wiki-generation pipeline.
Reads processing_output/entities_classified.json and re-emits it as stage output.
Named 'entity-classification' in the pipeline so wiki_preparation.py finds it unchanged.
"""
import json
import sys

def main() -> None:
    json.load(sys.stdin)  # consume stdin
    with open("processing_output/entities_classified.json", encoding="utf-8") as f:
        data = json.load(f)
    json.dump(data, sys.stdout, ensure_ascii=False)

if __name__ == "__main__":
    main()
```

**Step 4: Make them executable and verify syntax**

```bash
chmod +x scripts/load_splits.py scripts/load_epub_data.py scripts/load_classified_entities.py
python -c "import ast; ast.parse(open('scripts/load_splits.py').read()); print('OK')"
python -c "import ast; ast.parse(open('scripts/load_epub_data.py').read()); print('OK')"
python -c "import ast; ast.parse(open('scripts/load_classified_entities.py').read()); print('OK')"
```

**Step 5: Commit**

```bash
git add scripts/load_splits.py scripts/load_epub_data.py scripts/load_classified_entities.py
git commit -m "feat(stu-243): add loader scripts for cross-pipeline data handoff"
```

---

## Task 6: Create wiki-extraction.pipeline.yaml

**Files:**
- Create: `.studio/pipelines/wiki-extraction.pipeline.yaml`

**Context:** Stages 1–4 of the current `wiki-pipeline`. Identical to the first four stages. No changes needed — `split_clusters.py` already writes to `processing_output/` after Task 3.

**Step 1: Create the file**

```yaml
name: wiki-extraction
description: Parse EPUB and extract/cluster entities — run once per book
version: 1

stages:
  - name: epub-parse
    kind: extraction
    executor: script
    runtime: python
    script: scripts/parse_epub.py
    contract: epub-parse
    context:
      include:
        - input

  - name: entity-extraction
    kind: extraction
    executor: script
    runtime: python
    script: scripts/entity_extraction.py
    contract: entity-extraction
    timeout_ms: 600000
    context:
      include:
        - input
        - previous_stage_output

  - name: entity-clustering
    kind: extraction
    executor: script
    runtime: python
    script: scripts/entity_clustering.py
    contract: entity-clustering
    context:
      include:
        - previous_stage_output

  - name: split-clusters
    kind: extraction
    executor: script
    runtime: python
    script: scripts/split_clusters.py
    contract: split-clusters
    context:
      include:
        - previous_stage_output
```

**Step 2: Validate YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-extraction.pipeline.yaml'))" && echo "OK"
```

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-extraction.pipeline.yaml
git commit -m "feat(stu-243): add wiki-extraction.pipeline.yaml"
```

---

## Task 7: Create wiki-resolution.pipeline.yaml

**Files:**
- Create: `.studio/pipelines/wiki-resolution.pipeline.yaml`

**Context:** Stages 5–8 of the current pipeline, prepended with a `split-clusters` loader stage. The loader is named `split-clusters` so the entity-resolution group's `condition:` expressions (`stages.split-clusters.output.stats.multi_EVENT > 0`) still resolve correctly.

**Step 1: Create the file**

```yaml
name: wiki-resolution
description: Resolve entities and extract relationships — run once per book
version: 1

stages:
  - name: split-clusters
    kind: extraction
    executor: script
    runtime: python
    script: scripts/load_splits.py
    contract: split-clusters
    context:
      include:
        - input

  - group: entity-resolution
    mode: parallel
    max_iterations: 1
    on_failure: collect-all
    stages:
      - name: entity-resolution-PERSON
        kind: analysis
        agent: resolver
        contract: entity-resolution
        ralph:
          max_attempts: 3
        context:
          include:
            - previous_stage_output
            - stage_name

      - name: entity-resolution-PLACE
        kind: analysis
        agent: resolver
        contract: entity-resolution
        ralph:
          max_attempts: 3
        context:
          include:
            - previous_stage_output
            - stage_name

      - name: entity-resolution-ORG
        kind: analysis
        agent: resolver
        contract: entity-resolution
        ralph:
          max_attempts: 3
        context:
          include:
            - previous_stage_output
            - stage_name

      - name: entity-resolution-EVENT
        kind: analysis
        agent: resolver
        contract: entity-resolution
        condition: "stages.split-clusters.output.stats.multi_EVENT > 0"
        ralph:
          max_attempts: 2
        context:
          include:
            - previous_stage_output
            - stage_name

      - name: entity-resolution-OTHER
        kind: analysis
        agent: resolver
        contract: entity-resolution
        condition: "stages.split-clusters.output.stats.multi_OTHER > 0"
        ralph:
          max_attempts: 2
        context:
          include:
            - previous_stage_output
            - stage_name

  - name: merge-entities
    kind: extraction
    executor: script
    runtime: python
    script: scripts/merge_entities.py
    contract: merge-entities
    context:
      include:
        - all_stage_outputs

  - name: relationship-extraction
    kind: analysis
    executor: script
    runtime: python
    script: scripts/relationship_extraction.py
    contract: relationship-extraction
    context:
      include:
        - input
        - previous_stage_output

  - name: entity-classification
    kind: extraction
    executor: script
    runtime: python
    script: scripts/entity_classification.py
    contract: entity-classification
    context:
      include:
        - input
        - previous_stage_output
```

**Step 2: Validate YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-resolution.pipeline.yaml'))" && echo "OK"
```

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-resolution.pipeline.yaml
git commit -m "feat(stu-243): add wiki-resolution.pipeline.yaml"
```

---

## Task 8: Create wiki-generation.pipeline.yaml

**Files:**
- Create: `.studio/pipelines/wiki-generation.pipeline.yaml`

**Context:** Stages 9–11 of the current pipeline, prepended with two loader stages. `epub-parse` and `entity-classification` loaders are named identically to the original stages so `wiki_export.py` (which reads `previous_outputs["epub-parse"]`) and `wiki_preparation.py` (which reads `previous_outputs["entity-classification"]`) need zero changes.

**Step 1: Create the file**

```yaml
name: wiki-generation
description: Generate wiki pages from classified entities — re-runnable per batch
version: 1

stages:
  - name: epub-parse
    kind: extraction
    executor: script
    runtime: python
    script: scripts/load_epub_data.py
    contract: epub-parse
    context:
      include:
        - input

  - name: entity-classification
    kind: extraction
    executor: script
    runtime: python
    script: scripts/load_classified_entities.py
    contract: entity-classification
    context:
      include:
        - input

  - name: wiki-preparation
    kind: extraction
    executor: script
    runtime: python
    script: scripts/wiki_preparation.py
    contract: wiki-preparation
    context:
      include:
        - input
        - previous_stage_output

  - name: wiki-generation
    kind: analysis
    agent: writer-lite
    contract: wiki-page
    ralph:
      max_attempts: 3
    hooks:
      on_stage_complete:
        - command: "echo '{\"pages\": {{output.pages | tojson}}}' | python scripts/copyright_check.py --epub {{input.file_path}}"
          on_failure: reject
    context:
      include:
        - input
        - previous_stage_output

  - name: wiki-export
    kind: extraction
    executor: script
    runtime: python
    script: scripts/wiki_export.py
    contract: wiki-export
    context:
      include:
        - input
        - epub-parse
        - previous_stage_output
```

**Step 2: Validate YAML syntax**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-generation.pipeline.yaml'))" && echo "OK"
```

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-generation.pipeline.yaml
git commit -m "feat(stu-243): add wiki-generation.pipeline.yaml"
```

---

## Task 9: Create books/le-jeu-de-lange.yaml

**Files:**
- Create: `books/le-jeu-de-lange.yaml`

**Context:** The orchestrator `run_wiki.py` accepts `--book books/le-jeu-de-lange.yaml` as its input. This file is the book-level config (same content as `.studio/inputs/book.input.yaml`) placed in a `books/` directory for per-book organization. Studio pipelines reference it as the input file.

**Step 1: Create books/ directory and book config**

```bash
mkdir -p books/carlos-ruiz-zafon
```

Copy the content of `.studio/inputs/book.input.yaml` verbatim to `books/carlos-ruiz-zafon/le-jeu-de-lange.yaml`. The file should be identical — no changes to the YAML keys.

**Step 2: Commit**

```bash
git add books/
git commit -m "feat(stu-243): add books/ directory with le-jeu-de-lange.yaml"
```

---

## Task 10: Create run_wiki.py orchestrator

**Files:**
- Create: `run_wiki.py`

**Context:** Sequences the three `studio run` calls. Reads/writes `.wiki_runs/<book_slug>/current_run.json` for progress tracking. Supports `--restart`, `--batch`, `--retries`, `--status` flags.

**Step 1: Create run_wiki.py**

```python
#!/usr/bin/env python3
"""
Orchestrator for wiki creation pipeline.

Usage:
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --restart wiki-resolution
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --batch 0,2,5
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --retries 5
    python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --status
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PIPELINES = ["wiki-extraction", "wiki-resolution", "wiki-generation"]

REQUIRED_FILES = {
    "wiki-extraction": [
        "processing_output/splits.json",
        "processing_output/epub_data.json",
    ],
    "wiki-resolution": [
        "processing_output/entities_classified.json",
    ],
    "wiki-generation": [],
}


def book_slug(book_path: str) -> str:
    return Path(book_path).stem


def state_path(book_path: str) -> Path:
    return Path(".wiki_runs") / book_slug(book_path) / "current_run.json"


def load_state(book_path: str) -> dict:
    path = state_path(book_path)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"book": book_slug(book_path), "stages": {}}


def save_state(book_path: str, state: dict) -> None:
    path = state_path(book_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def run_pipeline(pipeline: str, book_path: str, extra_args: list[str] | None = None) -> bool:
    """Run a Studio pipeline. Returns True on success."""
    cmd = [
        "studio", "run", pipeline,
        "--input-file", book_path,
        "--live",
    ]
    if extra_args:
        cmd.extend(extra_args)
    print(f"\n{'='*60}", flush=True)
    print(f"Running: {' '.join(cmd)}", flush=True)
    print(f"{'='*60}", flush=True)
    result = subprocess.run(cmd)
    return result.returncode == 0


def check_outputs(pipeline: str) -> list[str]:
    """Return list of missing output files for a pipeline."""
    return [f for f in REQUIRED_FILES.get(pipeline, []) if not os.path.exists(f)]


def print_status(book_path: str) -> None:
    state = load_state(book_path)
    print(f"\nBook: {state.get('book', '?')}")
    for pipeline in PIPELINES:
        stage_state = state.get("stages", {}).get(pipeline, {})
        status = stage_state.get("status", "not_started")
        attempt = stage_state.get("attempt", 0)
        suffix = f" (attempt {attempt})" if attempt > 1 else ""
        print(f"  {pipeline}: {status}{suffix}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Wiki creation orchestrator")
    parser.add_argument("--book", required=True, help="Path to book YAML config")
    parser.add_argument("--restart", choices=PIPELINES, help="Restart from this pipeline")
    parser.add_argument("--batch", help="Comma-separated batch IDs for wiki-generation (e.g. 0,2,5)")
    parser.add_argument("--retries", type=int, default=3, help="Max attempts per pipeline")
    parser.add_argument("--status", action="store_true", help="Show run status and exit")
    args = parser.parse_args()

    if args.status:
        print_status(args.book)
        return

    state = load_state(args.book)

    # Determine start pipeline
    start_idx = 0
    if args.restart:
        start_idx = PIPELINES.index(args.restart)
        # Mark restarted pipeline and all subsequent as pending
        for pipeline in PIPELINES[start_idx:]:
            state.setdefault("stages", {}).pop(pipeline, None)
        save_state(args.book, state)

    for pipeline in PIPELINES[start_idx:]:
        stage_state = state.setdefault("stages", {}).get(pipeline, {})

        # Skip if already completed (unless we're restarting)
        if stage_state.get("status") == "completed":
            print(f"  {pipeline}: already completed, skipping")
            continue

        attempt = 0
        success = False
        while attempt < args.retries:
            attempt += 1
            state.setdefault("stages", {})[pipeline] = {
                "status": "running",
                "attempt": attempt,
            }
            save_state(args.book, state)

            extra = []
            if pipeline == "wiki-generation" and args.batch:
                extra = ["--batch", args.batch]

            ok = run_pipeline(pipeline, args.book, extra)

            if ok:
                missing = check_outputs(pipeline)
                if missing:
                    print(f"\n[WARN] {pipeline} succeeded but expected files are missing:")
                    for f in missing:
                        print(f"  {f}")
                    ok = False

            if ok:
                state["stages"][pipeline] = {"status": "completed", "attempt": attempt}
                save_state(args.book, state)
                success = True
                break
            else:
                state["stages"][pipeline] = {
                    "status": "failed",
                    "attempt": attempt,
                }
                save_state(args.book, state)
                if attempt < args.retries:
                    print(f"\n  {pipeline} failed (attempt {attempt}/{args.retries}), retrying...")

        if not success:
            print(f"\n[ERROR] {pipeline} failed after {args.retries} attempts. Aborting.")
            print(f"  Tip: fix the issue then run: python run_wiki.py --book {args.book} --restart {pipeline}")
            sys.exit(1)

    print("\nDone! All pipelines completed successfully.")
    print_status(args.book)


if __name__ == "__main__":
    main()
```

**Step 2: Make executable**

```bash
chmod +x run_wiki.py
```

**Step 3: Verify syntax**

```bash
python -c "import ast; ast.parse(open('run_wiki.py').read()); print('OK')"
python run_wiki.py --help
```

Expected: prints usage with all flags.

**Step 4: Test --status on empty state**

```bash
python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --status
```

Expected: prints all 3 pipelines as `not_started`.

**Step 5: Commit**

```bash
git add run_wiki.py
git commit -m "feat(stu-243): add run_wiki.py orchestrator with restart/retry/batch support"
```

---

## Task 11: Delete old pipelines

**Files:**
- Delete: `.studio/pipelines/wiki-pipeline.pipeline.yaml`
- Delete: `.studio/pipelines/wiki-page.pipeline.yaml`

**Context:** `wiki-pipeline` is replaced by the 3 new pipelines. `wiki-page` is replaced by `wiki-generation` (which now uses `writer-lite` via the `wiki-page` contract directly). Do this last — only after Tasks 1–10 are complete and tested.

**Step 1: Delete the files**

```bash
git rm .studio/pipelines/wiki-pipeline.pipeline.yaml
git rm .studio/pipelines/wiki-page.pipeline.yaml
```

**Step 2: Commit**

```bash
git commit -m "feat(stu-243): remove monolithic wiki-pipeline and wiki-page (replaced by 3 pipelines)"
```

---

## Task 12: E2E smoke test

**Step 1: Verify all 3 pipelines are registered**

```bash
studio run --list 2>/dev/null || ls .studio/pipelines/
```

Expected: `wiki-extraction`, `wiki-resolution`, `wiki-generation` (no `wiki-pipeline`).

**Step 2: Test wiki-extraction with mock provider**

```bash
studio run wiki-extraction --input-file books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --provider mock
```

Expected: completes without error, `processing_output/splits.json` and `processing_output/epub_data.json` exist.

**Step 3: Test wiki-resolution with mock provider**

```bash
studio run wiki-resolution --input-file books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --provider mock
```

Expected: completes, `processing_output/entities_classified.json` exists.

**Step 4: Test wiki-generation with mock provider**

```bash
studio run wiki-generation --input-file books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --provider mock
```

Expected: completes, wiki output files written.

**Step 5: Test orchestrator restart logic**

```bash
# Simulate a completed extraction
python run_wiki.py --book books/carlos-ruiz-zafon/le-jeu-de-lange.yaml --status
# Should show wiki-extraction as completed (from the mock run)
```

**Step 6: Commit any fixups**

```bash
git add -A
git commit -m "fix(stu-243): E2E smoke test fixups"
```

---

## Summary of all file changes

| Action | File |
|--------|------|
| Modify | `scripts/parse_epub.py` — write `processing_output/epub_data.json` |
| Modify | `scripts/split_clusters.py` — write `processing_output/splits.json` |
| Modify | `scripts/entity_classification.py` — write `processing_output/entities_classified.json` |
| Create | `scripts/load_splits.py` |
| Create | `scripts/load_epub_data.py` |
| Create | `scripts/load_classified_entities.py` |
| Create | `.studio/pipelines/wiki-extraction.pipeline.yaml` |
| Create | `.studio/pipelines/wiki-resolution.pipeline.yaml` |
| Create | `.studio/pipelines/wiki-generation.pipeline.yaml` |
| Create | `books/carlos-ruiz-zafon/le-jeu-de-lange.yaml` |
| Create | `run_wiki.py` |
| Modify | `.gitignore` |
| Delete | `.studio/pipelines/wiki-pipeline.pipeline.yaml` |
| Delete | `.studio/pipelines/wiki-page.pipeline.yaml` |

**No changes needed to:** `wiki_preparation.py`, `wiki_export.py`, `relationship_extraction.py`, `entity_classification.py` (studio entrypoint logic), any contracts or agents.
