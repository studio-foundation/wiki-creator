# classify_relationships Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `scripts/classify_relationships.py` — a standalone script that reads `relationships.json`, calls `studio run relationship-classifier-item` for each pair (reusing the existing `_run_studio_classifier_item` function), saves incrementally after each pair, and supports resume.

**Architecture:** Script imports `_run_studio_classifier_item` and `_should_classify_pair` from `scripts/relationship_extraction.py`. Studio handles LLM calls, ralph retries, and validation. The script handles the loop, filtering, incremental save, and resume. Pattern matches `generate_wiki_pages.py`.

**Tech Stack:** Python 3.11+, stdlib only (no new deps), `wiki_creator.paths.book_paths_from_yaml`, PyYAML (already in project deps)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `scripts/classify_relationships.py` | **Create** | Standalone classification script |
| `tests/test_classify_relationships.py` | **Create** | Unit tests (no Studio/Ollama calls) |
| `Makefile` | **Modify** | Add `classify-relationships` + `classify-relationships-dry` targets |

---

### Task 1: Scaffold + _load_done_keys + _save + tests

**Files:**
- Create: `scripts/classify_relationships.py`
- Create: `tests/test_classify_relationships.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_classify_relationships.py
import json
from pathlib import Path
import pytest
from scripts.classify_relationships import _load_done_keys, _save


def test_load_done_keys_returns_empty_when_file_missing(tmp_path):
    keys, pairs = _load_done_keys(tmp_path / "nonexistent.json")
    assert keys == set()
    assert pairs == []


def test_load_done_keys_returns_existing_pairs(tmp_path):
    output = tmp_path / "out.json"
    data = {
        "relationships": [
            {"entity_a": "A", "entity_b": "B", "relationship_type": "ami"},
        ]
    }
    output.write_text(json.dumps(data))
    keys, pairs = _load_done_keys(output)
    assert ("A", "B") in keys
    assert len(pairs) == 1


def test_load_done_keys_returns_empty_on_corrupt_file(tmp_path):
    output = tmp_path / "corrupt.json"
    output.write_text("not valid json")
    keys, pairs = _load_done_keys(output)
    assert keys == set()
    assert pairs == []


def test_load_done_keys_skips_malformed_pairs(tmp_path):
    """A pair missing entity_a/entity_b is skipped, not a full reset."""
    output = tmp_path / "out.json"
    data = {
        "relationships": [
            {"entity_a": "A", "entity_b": "B", "relationship_type": "ami"},
            {"broken": True},  # malformed — no entity_a/entity_b
        ]
    }
    output.write_text(json.dumps(data))
    keys, pairs = _load_done_keys(output)
    assert ("A", "B") in keys
    assert len(pairs) == 2  # both pairs loaded, only valid ones keyed


def test_save_writes_valid_json(tmp_path):
    output = tmp_path / "out.json"
    base = {"entities": [], "stats": {}, "narrator": None}
    pairs = [{"entity_a": "A", "entity_b": "B"}]
    _save(output, base, pairs)
    written = json.loads(output.read_text())
    assert written["relationships"] == pairs
    assert written["entities"] == []
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
pytest tests/test_classify_relationships.py -v
```
Expected: `ImportError` or `ModuleNotFoundError` (script doesn't exist yet)

- [ ] **Step 3: Create `scripts/classify_relationships.py` with scaffold**

```python
#!/usr/bin/env python3
"""Standalone relationship classifier: calls studio run relationship-classifier-item per pair.

Usage:
    python scripts/classify_relationships.py --book library/.../book.yaml
    python scripts/classify_relationships.py --book library/.../book.yaml --dry-run

Input:  processing_output/<slug>/relationships.json
Output: processing_output/<slug>/relationships_classified.json

Saves incrementally after each pair. Resumes if output file already exists.
Studio handles LLM calls, ralph retries, and validation.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_yaml
from scripts.relationship_extraction import (
    _run_studio_classifier_item,
    _should_classify_pair,
)


def _load_done_keys(output_path: Path) -> tuple[set[tuple[str, str]], list[dict]]:
    """Load already-classified pairs from output file. Returns (done_keys, pairs).

    Malformed pairs (missing entity_a/entity_b) are skipped individually — they do NOT
    cause a full reset of resume state.
    """
    if not output_path.exists():
        return set(), []
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        pairs = data.get("relationships", [])
        keys = {
            (p["entity_a"], p["entity_b"])
            for p in pairs
            if "entity_a" in p and "entity_b" in p
        }
        return keys, pairs
    except json.JSONDecodeError:
        return set(), []


def _save(output_path: Path, base: dict, classified: list[dict]) -> None:
    out = {**base, "relationships": classified}
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests — should pass**

```bash
pytest tests/test_classify_relationships.py -v
```
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/classify_relationships.py tests/test_classify_relationships.py
git commit -m "feat(classify-relationships): scaffold + _load_done_keys + _save"
```

---

### Task 2: main() with Studio loop + resume

**Files:**
- Modify: `scripts/classify_relationships.py` (add `main()`)
- Modify: `tests/test_classify_relationships.py` (add dry-run test)

- [ ] **Step 1: Write failing test for dry-run**

Add to `tests/test_classify_relationships.py`:

```python
import subprocess


def test_dry_run_with_missing_book_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "scripts/classify_relationships.py",
         "--book", "nonexistent.yaml", "--dry-run"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode != 0
```

- [ ] **Step 2: Run to confirm test fails**

```bash
pytest tests/test_classify_relationships.py::test_dry_run_with_missing_book_exits_nonzero -v
```
Expected: FAIL (no `main()` yet)

- [ ] **Step 3: Add `main()` to the script**

Add at the bottom of `scripts/classify_relationships.py`:

```python
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify relationships via Studio (relationship-classifier-item pipeline)."
    )
    parser.add_argument(
        "--book", required=True,
        help="Path to book YAML, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Studio calls, pass pairs through unchanged",
    )
    args = parser.parse_args()

    book_paths = book_paths_from_yaml(args.book)
    input_path = book_paths.processing / "relationships.json"
    output_path = book_paths.processing / "relationships_classified.json"

    if not input_path.exists():
        print(f"[ERROR] Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(input_path.read_text(encoding="utf-8"))
    relationships = data.get("relationships", [])
    entity_types = {e["canonical_name"]: e.get("type", "") for e in data.get("entities", [])}
    base = {k: v for k, v in data.items() if k != "relationships"}

    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}
    novel_summary = book_cfg.get("novel_summary") or ""

    done_keys, classified = _load_done_keys(output_path)
    if done_keys:
        print(
            f"[classify-relationships] Resuming — {len(done_keys)} pairs already done",
            file=sys.stderr,
        )

    to_classify = [r for r in relationships if (r.get("entity_a"), r.get("entity_b")) not in done_keys]
    skip_count = len(relationships) - len(to_classify)
    classifiable = sum(1 for r in to_classify if _should_classify_pair(r, entity_types))

    print(
        f"[classify-relationships] {len(relationships)} pairs total | "
        f"{skip_count} skipped (already done) | "
        f"{classifiable} to classify",
        file=sys.stderr,
    )

    try:
        for i, pair in enumerate(to_classify, 1):
            label = f"{pair.get('entity_a', '?')}↔{pair.get('entity_b', '?')}"
            if not _should_classify_pair(pair, entity_types):
                print(f"  [SKIP] {label} (non-interpersonal type)", file=sys.stderr)
                classified.append(pair)
            elif args.dry_run:
                print(f"  [DRY]  {label}", file=sys.stderr)
                classified.append(pair)
            else:
                print(f"  [CLF]  {label} ({i}/{len(to_classify)})", file=sys.stderr, end="", flush=True)
                classification = _run_studio_classifier_item(
                    pair,
                    novel_summary=novel_summary,
                    additional_context="",
                )
                if classification and not classification.get("error"):
                    result = {**pair, **classification}
                else:
                    print(
                        f"\n  [WARN] Studio failed for {label}: "
                        f"{classification.get('error', 'unknown') if classification else 'no response'}",
                        file=sys.stderr,
                    )
                    result = pair
                classified.append(result)
                status = result.get("relationship_type") or "null"
                print(f" → {status}", file=sys.stderr)
            _save(output_path, base, classified)
    except KeyboardInterrupt:
        print(
            f"\n[classify-relationships] Interrupted — {len(classified)} pairs saved",
            file=sys.stderr,
        )

    succeeded = sum(1 for r in classified if r.get("relationship_type") is not None)
    print(
        f"\n[classify-relationships] Done — {len(classified)} total, {succeeded} classified",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_classify_relationships.py -v
pytest -q
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/classify_relationships.py tests/test_classify_relationships.py
git commit -m "feat(classify-relationships): main() with Studio loop + resume"
```

---

### Task 3: Makefile targets

**Files:**
- Modify: `Makefile`

- [ ] **Step 1: Read current Makefile `.PHONY` and targets (lines 1-5, 64-77)**

```bash
head -5 Makefile
sed -n '64,77p' Makefile
```

- [ ] **Step 2: Add to `.PHONY` line 2**

Add `classify-relationships classify-relationships-dry \` to the `.PHONY` declaration.

- [ ] **Step 3: Add targets after `test-relationships` block (around line 67)**

```makefile
classify-relationships:
	python scripts/classify_relationships.py --book $(BOOK)

classify-relationships-dry:
	python scripts/classify_relationships.py --book $(BOOK) --dry-run
```

- [ ] **Step 4: Verify**

```bash
make classify-relationships-dry --dry-run
pytest -q
```
Expected: make prints the command, pytest green

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "feat(classify-relationships): add Makefile targets"
```

---

## Quick sanity check after all tasks

```bash
python scripts/classify_relationships.py --help
pytest -q
```
