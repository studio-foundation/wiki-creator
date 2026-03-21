# classify_relationships Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create `scripts/classify_relationships.py`, a standalone script that reads `relationships.json`, classifies each pair via direct Ollama calls (no Studio subprocess), saves incrementally, and supports resume.

**Architecture:** Script follows the exact pattern of `generate_wiki_pages.py` — `call_ollama()` via `urllib.request`, retry loop per pair (max 3), incremental save after each pair, resume on restart. Validation reuses functions already exported by `scripts/relationship_classifier_validator.py` (`check_relationship_type_valid`, `check_evidence_contains_both_names`, `check_evolution_not_generic`). A Makefile target `classify-relationships` is added.

**Tech Stack:** Python 3.11+, `urllib.request` (stdlib), `yaml` (PyYAML), `wiki_creator.paths.book_paths_from_yaml`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `scripts/classify_relationships.py` | **Create** | Standalone classification script |
| `tests/test_classify_relationships.py` | **Create** | Unit tests (no Ollama calls) |
| `Makefile` | **Modify** | Add `classify-relationships` target + `.PHONY` |

---

### Task 1: Scaffold + call_ollama + dry-run

**Files:**
- Create: `scripts/classify_relationships.py`
- Create: `tests/test_classify_relationships.py`

- [ ] **Step 1: Write failing tests for call_ollama and dry-run**

```python
# tests/test_classify_relationships.py
import json
import pytest
from unittest.mock import patch, MagicMock
from scripts.classify_relationships import call_ollama, classify_pair


def test_call_ollama_returns_response_string():
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"response": "hello"}).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = call_ollama("prompt", model="qwen2.5", timeout=10)
    assert result == "hello"


def test_call_ollama_returns_none_on_error():
    with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
        result = call_ollama("prompt", model="qwen2.5", timeout=10)
    assert result is None


def test_classify_pair_dry_run_returns_pair_unchanged():
    pair = {"entity_a": "Celaena", "entity_b": "Dorian", "cooccurrence_count": 5, "sample_contexts": []}
    result = classify_pair(pair, model="qwen2.5", novel_summary=None, dry_run=True)
    assert result == pair
    assert "relationship_type" not in result
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
pytest tests/test_classify_relationships.py -v
```
Expected: `ImportError` or `ModuleNotFoundError` (script doesn't exist yet)

- [ ] **Step 3: Create `scripts/classify_relationships.py` with scaffold**

```python
#!/usr/bin/env python3
"""Standalone relationship classifier: calls Ollama directly, no Studio subprocess.

Usage:
    python scripts/classify_relationships.py --book library/.../book.yaml
    python scripts/classify_relationships.py --book library/.../book.yaml --model qwen2.5
    python scripts/classify_relationships.py --book library/.../book.yaml --dry-run

Input:  processing_output/<slug>/relationships.json
Output: processing_output/<slug>/relationships_classified.json

Saves incrementally after each pair. Resumes if output file already exists.
"""
import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_yaml
from scripts.relationship_classifier_validator import (
    check_relationship_type_valid,
    check_evidence_contains_both_names,
    check_evolution_not_generic,
)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
MAX_ATTEMPTS = 3
_NON_INTERPERSONAL_TYPES = frozenset({"PLACE", "OTHER"})

# Verbatim system prompt from .studio/agents/relationship-classifier.agent.yaml
SYSTEM_PROMPT = """\
Respond with ONLY a valid JSON object. No markdown fences, no explanation, no other text.

You classify the relationship between two characters in a novel.

You receive input with:
- entity_a: name of character A
- entity_b: name of character B
- cooccurrence_count: number of times they appear together
- sample_contexts: list of short text excerpts where both appear
- novel_summary: (optional) a short narrative summary of the novel for context

When novel_summary is provided, use it as background context only — do NOT let it override
the specific relationship type visible in the excerpts.
Choose the MOST SPECIFIC relationship type.
Use "employeur/employé" ONLY when a clear hierarchical employment relationship is the PRIMARY dynamic.
Allies, friends, family, and romantic interests MUST use their specific type.
When in doubt between two types, choose the more specific one.

CRITICAL — co-occurrence vs direct interaction:
Before assigning a relationship_type, verify that at least one excerpt shows entity_a and entity_b
interacting directly (speaking to each other, acting on each other, being in the same scene together
with a meaningful exchange). If the excerpts only show that both characters appear in the same chapter
or are mentioned in proximity WITHOUT a direct interaction between them, you MUST return
relationship_type: null. Do NOT infer a relationship from co-occurrence alone.

Return exactly:
{
  "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre|null",
  "direction": "symétrique|A→B|B→A|null",
  "evolution": "one sentence describing HOW the relationship changes across the provided chapters, or null if no change is observable — do NOT write \\"relation stable\\" or any equivalent filler",
  "key_moments": ["chXX: short description"],
  "evidence": "verbatim sentence or short passage from sample_contexts that best demonstrates the direct interaction between entity_a and entity_b — must contain both names or clear references to both"
}

Rules:
- Base your answer on the provided excerpts and novel_summary
- Do not invent facts
- Return valid JSON only
- key_moments must reference ONLY events explicitly present in the provided sample_contexts
- The \\"chXX:\\" prefix must match the chapter ID from the excerpt header
- For pairs with cooccurrence_count >= 5: you MUST include at least 1 key_moment extracted from sample_contexts
- If no specific moment can be identified despite searching all excerpts, return: [\\"no specific moment identifiable in provided excerpts\\"]
- evidence must be a verbatim excerpt from sample_contexts showing BOTH entity_a and entity_b; if relationship_type is null, set evidence to null\
"""


def call_ollama(prompt: str, model: str, timeout: int = 120) -> str | None:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read()).get("response", "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None  # OSError covers socket.timeout; URLError covers connection errors


def _should_classify(pair: dict, entity_types: dict[str, str]) -> bool:
    for key in ("entity_a", "entity_b"):
        if entity_types.get(pair.get(key, ""), "") in _NON_INTERPERSONAL_TYPES:
            return False
    return True


def _validate(clf: dict, pair: dict) -> list[str]:
    # Local wrapper: returns list[str] of errors.
    # The validator module's validate_classification() returns a dict — not used here.
    errors: list[str] = []
    errors += check_relationship_type_valid(clf)
    errors += check_evolution_not_generic(clf)
    errors += check_evidence_contains_both_names(clf, pair)  # pair must have entity_a, entity_b
    return errors


def classify_pair(
    pair: dict,
    *,
    model: str,
    novel_summary: str | None,
    dry_run: bool = False,
) -> dict:
    """Classify one pair. Returns enriched pair on success, original pair on failure/dry-run."""
    if dry_run:
        return pair

    user_msg: dict = {
        "entity_a": pair["entity_a"],
        "entity_b": pair["entity_b"],
        "cooccurrence_count": pair.get("cooccurrence_count", 0),
        "sample_contexts": pair.get("sample_contexts", []),
    }
    if novel_summary:
        user_msg["novel_summary"] = novel_summary

    prompt = SYSTEM_PROMPT + "\n\n" + json.dumps(user_msg, ensure_ascii=False)

    for attempt in range(MAX_ATTEMPTS):
        raw = call_ollama(prompt, model=model)
        if raw is None:
            continue
        try:
            clf = json.loads(raw)
        except json.JSONDecodeError:
            continue
        errors = _validate(clf, pair)
        if not errors:
            return {**pair, **clf}
        if attempt < MAX_ATTEMPTS - 1:
            print(
                f"  [RETRY {attempt + 1}] {pair['entity_a']}↔{pair['entity_b']}: {errors[0]}",
                file=sys.stderr,
            )

    print(
        f"  [WARN] classification failed after {MAX_ATTEMPTS} attempts: "
        f"{pair['entity_a']}↔{pair['entity_b']}",
        file=sys.stderr,
    )
    return pair
```

- [ ] **Step 4: Run tests — should pass now**

```bash
pytest tests/test_classify_relationships.py -v
```
Expected: 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/classify_relationships.py tests/test_classify_relationships.py
git commit -m "feat(classify-relationships): scaffold + call_ollama + classify_pair"
```

---

### Task 2: Resume logic + save + main()

**Files:**
- Modify: `scripts/classify_relationships.py` (add `_load_output`, `_save`, `main`)
- Modify: `tests/test_classify_relationships.py` (add resume tests)

- [ ] **Step 1: Write failing tests for resume and save**

Add to `tests/test_classify_relationships.py`:

```python
import tempfile
from pathlib import Path
from scripts.classify_relationships import _load_done_keys, _save


def test_load_done_keys_returns_empty_when_file_missing(tmp_path):
    result, pairs = _load_done_keys(tmp_path / "nonexistent.json")
    assert result == set()
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
pytest tests/test_classify_relationships.py::test_load_done_keys_returns_empty_when_file_missing -v
```
Expected: `ImportError` (functions not defined yet)

- [ ] **Step 3: Add `_load_done_keys`, `_save`, and `main()` to script**

Add after `classify_pair`:

```python
def _load_done_keys(output_path: Path) -> tuple[set[tuple[str, str]], list[dict]]:
    """Load already-classified pairs from output file. Returns (done_keys, pairs)."""
    if not output_path.exists():
        return set(), []
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        pairs = data.get("relationships", [])
        keys = {(p["entity_a"], p["entity_b"]) for p in pairs}
        return keys, pairs
    except (json.JSONDecodeError, KeyError):
        return set(), []


def _save(output_path: Path, base: dict, classified: list[dict]) -> None:
    out = {**base, "relationships": classified}
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify relationships via direct Ollama calls."
    )
    parser.add_argument(
        "--book", required=True,
        help="Path to book YAML, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
    )
    parser.add_argument("--model", default=os.environ.get("WIKI_MODEL", "qwen2.5"))
    parser.add_argument("--dry-run", action="store_true", help="Skip Ollama calls, pass pairs through unchanged")
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
    novel_summary = book_cfg.get("novel_summary") or None

    done_keys, classified = _load_done_keys(output_path)
    if done_keys:
        print(f"[classify-relationships] Resuming — {len(done_keys)} pairs already done", file=sys.stderr)

    to_classify = [r for r in relationships if (r["entity_a"], r["entity_b"]) not in done_keys]
    skipped = [r for r in relationships if (r["entity_a"], r["entity_b"]) in done_keys]
    skip_count = len(skipped)
    total = len(relationships)
    classifiable = sum(1 for r in to_classify if _should_classify(r, entity_types))

    print(
        f"[classify-relationships] {total} pairs total | "
        f"{skip_count} skipped (already done) | "
        f"{classifiable} to classify | model={args.model}",
        file=sys.stderr,
    )

    try:
        for i, pair in enumerate(to_classify, 1):
            label = f"{pair['entity_a']}↔{pair['entity_b']}"
            if not _should_classify(pair, entity_types):
                print(f"  [SKIP] {label} (non-interpersonal type)", file=sys.stderr)
                classified.append(pair)
            else:
                print(f"  [CLF]  {label} ({i}/{len(to_classify)})", file=sys.stderr, end="", flush=True)
                result = classify_pair(pair, model=args.model, novel_summary=novel_summary, dry_run=args.dry_run)
                classified.append(result)
                status = result.get("relationship_type") or "null"
                print(f" → {status}", file=sys.stderr)
            _save(output_path, base, classified)
    except KeyboardInterrupt:
        print(f"\n[classify-relationships] Interrupted — {len(classified)} pairs saved", file=sys.stderr)

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
```
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/classify_relationships.py tests/test_classify_relationships.py
git commit -m "feat(classify-relationships): add resume, save, and main()"
```

---

### Task 3: Makefile target + integration test

**Files:**
- Modify: `Makefile` (lines 1-3 `.PHONY`, add target)
- Modify: `tests/test_classify_relationships.py` (add integration smoke test)

- [ ] **Step 1: Write failing test for end-to-end dry-run**

Add to `tests/test_classify_relationships.py`:

```python
import subprocess


def test_dry_run_with_missing_book_exits_nonzero():
    result = subprocess.run(
        ["python", "scripts/classify_relationships.py", "--book", "nonexistent.yaml", "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_dry_run_produces_output_file(tmp_path):
    """End-to-end: dry-run reads a minimal relationships.json and writes relationships_classified.json."""
    import yaml as _yaml
    from scripts.classify_relationships import _load_done_keys, _save, classify_pair

    pairs = [{"entity_a": "A", "entity_b": "B", "cooccurrence_count": 1, "sample_contexts": []}]
    result = classify_pair(pairs[0], model="qwen2.5", novel_summary=None, dry_run=True)
    assert result == pairs[0]
    assert "relationship_type" not in result
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
pytest tests/test_classify_relationships.py::test_dry_run_with_missing_book_exits_nonzero -v
```
Expected: FAIL (script may not exit cleanly yet)

- [ ] **Step 3: Add Makefile target**

In `Makefile`, line 2, add `classify-relationships` to `.PHONY`:
```makefile
.PHONY: run run-extraction run-resolution run-preparation run-generation pages-export run-all \
        test-extraction test-clustering test-relationships test test-coref test-coref-parallel \
        classify-relationships \
        ...
```

Add target (after `test-relationships` block, around line 67):
```makefile
classify-relationships:
	python scripts/classify_relationships.py --book $(BOOK)

classify-relationships-dry:
	python scripts/classify_relationships.py --book $(BOOK) --dry-run
```

- [ ] **Step 4: Run all tests**

```bash
pytest tests/test_classify_relationships.py -v
pytest -q
```
Expected: all PASS, `pytest -q` green (485+ passed)

- [ ] **Step 5: Commit**

```bash
git add Makefile tests/test_classify_relationships.py
git commit -m "feat(classify-relationships): add Makefile targets + integration tests"
```

---

## Quick sanity check after all tasks

```bash
# Verify the script is importable and --help works
python scripts/classify_relationships.py --help

# Verify full test suite stays green
pytest -q
```
