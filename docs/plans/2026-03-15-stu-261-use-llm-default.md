# STU-261: Enable use_llm in alias resolution by default Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `use_llm: true` to the default book YAML and emit a visible warning in `alias_resolution.py` when `use_llm` is absent/false.

**Architecture:** Two-part change: (1) a one-line warning in `main()` when `use_llm` is falsy; (2) `use_llm: true` + `llm_model: qwen2.5` added to the committed book YAML. The warning fires unconditionally so operators always see it in logs if they opt out.

**Tech Stack:** Python `warnings` module (already imported), YAML book config.

---

### Task 1: Add warning when use_llm is False

**Files:**
- Modify: `scripts/alias_resolution.py:524-535`
- Test: `tests/test_alias_resolution.py`

**Step 1: Write the failing test**

Add after the existing `test_script_use_llm_false_by_default` test (around line 418):

```python
def test_script_use_llm_false_emits_warning(tmp_path):
    """use_llm absent → warning printed to stderr."""
    book_yaml = tmp_path / "library" / "a" / "s" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n")
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(json.dumps({"persons_full": {}}))

    payload = {
        "previous_outputs": {"resolve-clusters": {"entities": [], "narrator": None}},
        "additional_context": f"file_path: {book_yaml}\n",
    }
    result = subprocess.run(
        [sys.executable, "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, result.stderr
    assert "use_llm" in result.stderr.lower() or "llm alias" in result.stderr.lower()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_alias_resolution.py::test_script_use_llm_false_emits_warning -v
```

Expected: FAIL (no warning currently emitted)

**Step 3: Add warning in `scripts/alias_resolution.py`**

Replace the block at line 524:

```python
    use_llm = ctx.get("use_llm", False)
    if use_llm:
```

with:

```python
    use_llm = ctx.get("use_llm", False)
    if not use_llm:
        warnings.warn(
            "LLM alias confirmation is disabled (use_llm not set in book config). "
            "Title-based aliases (e.g. 'Captain Westfall', 'Crown Prince') will NOT be resolved. "
            "Set use_llm: true in your book YAML to enable.",
            stacklevel=1,
        )
    if use_llm:
```

**Step 4: Run tests to verify**

```bash
pytest tests/test_alias_resolution.py -v -k "use_llm"
```

Expected: all `use_llm`-related tests PASS (including the existing `test_script_use_llm_false_by_default` which only checks `"ollama" not in stderr` — unaffected).

**Step 5: Run full suite**

```bash
pytest -q
```

Expected: all 288+ tests pass.

**Step 6: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-261): warn when use_llm is disabled in alias_resolution"
```

---

### Task 2: Enable use_llm in the default book YAML

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Step 1: Add use_llm config to book YAML**

Open `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml` and add after the `coref: false` line:

```yaml
use_llm: true
llm_model: qwen2.5
```

**Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml'))"
```

Expected: no output (no parse errors).

**Step 3: Run full suite**

```bash
pytest -q
```

Expected: all tests pass.

**Step 4: Commit**

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(STU-261): enable use_llm by default in throne-of-glass book config"
```
