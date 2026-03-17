# STU-261 Title-Alias Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a third detection path in `alias_resolution.py` that routes title-based alias pairs (e.g. "Captain Westfall" → "Chaol Westfall") to the LLM confirmer, using `role_words` from the book YAML.

**Architecture:** New pure function `_detect_title_alias(entity_a, entity_b, role_words)` inserted between `_detect_pattern_match` and `_detect_reveal_signal` in `resolve_aliases()`. If an entity's name starts with a role_word and the remainder appears in the other entity's canonical name, the pair is sent to the LLM confirmer. The LLM always has the final say — no deterministic merge.

**Tech Stack:** Python 3.11+, pytest, existing `alias_resolution.py` patterns.

---

### Task 1: Add `crown prince` to book YAML `role_words`

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Step 1: Edit `role_words` in the YAML**

Open `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`.

Find the `role_words:` list (currently starts with `- assassin`). Add `crown prince` as the first entry:

```yaml
  role_words:
    - crown prince
    - assassin
    - champion
    - "king's champion"
    - "adarlan's assassin"
    - queen
    - king
    - prince
    - princess
    - lady
    - lord
    - captain
    - guard
```

**Step 2: Verify the file parses cleanly**

```bash
python -c "import yaml; yaml.safe_load(open('library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml'))"
```

Expected: no output (no error).

**Step 3: Run existing tests to make sure nothing broke**

```bash
pytest tests/test_pipeline_configs.py -q
```

Expected: all pass.

**Step 4: Commit**

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(STU-261): add crown prince to role_words in throne-of-glass config"
```

---

### Task 2: Add `_detect_title_alias` — failing tests first

**Files:**
- Test: `tests/test_alias_resolution.py`

**Context:** The test file imports from `scripts.alias_resolution`. New tests go at the bottom of the file, before the script-level tests. The existing pattern for unit-testing a detection function is to call it directly with minimal dicts (see `test_explicit_alias_pattern_merges_person_entities` at line 56 for style reference).

**Step 1: Write the failing tests**

Append these tests to `tests/test_alias_resolution.py`:

```python
# ---------------------------------------------------------------------------
# _detect_title_alias
# ---------------------------------------------------------------------------

def test_detect_title_alias_captain_westfall():
    from scripts.alias_resolution import _detect_title_alias
    entity_title = {"canonical_name": "Captain Westfall", "aliases": ["Captain Westfall"]}
    entity_full  = {"canonical_name": "Chaol Westfall",   "aliases": ["Chaol Westfall", "Chaol"]}
    result = _detect_title_alias(entity_title, entity_full, role_words=["captain"])
    assert result is not None
    assert result["method"] == "title_alias"
    assert result["confidence"] == "medium"


def test_detect_title_alias_crown_prince():
    from scripts.alias_resolution import _detect_title_alias
    entity_title = {"canonical_name": "Crown Prince", "aliases": ["Crown Prince"]}
    entity_full  = {"canonical_name": "Dorian Havilliard", "aliases": ["Dorian Havilliard", "Dorian"]}
    result = _detect_title_alias(entity_title, entity_full, role_words=["crown prince"])
    assert result is not None
    assert result["method"] == "title_alias"


def test_detect_title_alias_no_match_remainder_absent():
    from scripts.alias_resolution import _detect_title_alias
    # "Princess Nehemia" — remainder "nehemia" not in "Dorian Havilliard"
    entity_title = {"canonical_name": "Princess Nehemia", "aliases": ["Princess Nehemia"]}
    entity_full  = {"canonical_name": "Dorian Havilliard", "aliases": ["Dorian Havilliard"]}
    assert _detect_title_alias(entity_title, entity_full, role_words=["princess"]) is None


def test_detect_title_alias_no_match_empty_remainder():
    from scripts.alias_resolution import _detect_title_alias
    # "Captain" alone — no remainder after role_word
    entity_a = {"canonical_name": "Captain", "aliases": ["Captain"]}
    entity_b = {"canonical_name": "Chaol Westfall", "aliases": ["Chaol Westfall"]}
    assert _detect_title_alias(entity_a, entity_b, role_words=["captain"]) is None


def test_detect_title_alias_empty_role_words():
    from scripts.alias_resolution import _detect_title_alias
    entity_a = {"canonical_name": "Captain Westfall", "aliases": ["Captain Westfall"]}
    entity_b = {"canonical_name": "Chaol Westfall", "aliases": ["Chaol Westfall"]}
    assert _detect_title_alias(entity_a, entity_b, role_words=[]) is None


def test_detect_title_alias_symmetric():
    from scripts.alias_resolution import _detect_title_alias
    # Order of arguments should not matter
    entity_title = {"canonical_name": "Captain Westfall", "aliases": ["Captain Westfall"]}
    entity_full  = {"canonical_name": "Chaol Westfall",   "aliases": ["Chaol Westfall"]}
    assert _detect_title_alias(entity_full, entity_title, role_words=["captain"]) is not None
```

**Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_alias_resolution.py::test_detect_title_alias_captain_westfall -v
```

Expected: `ImportError` or `AttributeError: module has no attribute '_detect_title_alias'`

---

### Task 3: Implement `_detect_title_alias`

**Files:**
- Modify: `scripts/alias_resolution.py` — insert after `_detect_reveal_signal` (line 371), before `detect_named_aliases` (line 374)

**Step 1: Add the function**

Insert after the closing of `_detect_reveal_signal` (after line 371):

```python
def _detect_title_alias(
    entity_a: dict,
    entity_b: dict,
    role_words: list[str],
) -> dict | None:
    """
    Return evidence dict if one entity's name starts with a role_word and the
    remainder appears in the other entity's canonical name.

    Example: "Captain Westfall" + role_word "captain"
             → remainder "westfall" in "Chaol Westfall" → match.
    """
    if not role_words:
        return None
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for names_title, names_full in ((names_a, names_b), (names_b, names_a)):
        for name in names_title:
            name_lower = name.lower()
            for role in role_words:
                role_lower = role.lower()
                if not name_lower.startswith(role_lower + " "):
                    continue
                remainder = name_lower[len(role_lower) + 1:].strip()
                if not remainder:
                    continue
                for full_name in names_full:
                    if remainder in full_name.lower():
                        return {
                            "method": "title_alias",
                            "confidence": "medium",
                            "snippet": f"{name} / {full_name}",
                        }
    return None
```

**Step 2: Run the failing tests**

```bash
pytest tests/test_alias_resolution.py -k "detect_title_alias" -v
```

Expected: all 6 tests PASS.

**Step 3: Run full test suite to check for regressions**

```bash
pytest -q
```

Expected: all pass (same count as before).

**Step 4: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-261): add _detect_title_alias function with tests"
```

---

### Task 4: Update `_empty_stats` to track `title_alias` merges

**Files:**
- Modify: `scripts/alias_resolution.py:72-81`

**Step 1: Write the failing test**

Add to `tests/test_alias_resolution.py`:

```python
def test_empty_stats_has_title_alias_key():
    from scripts.alias_resolution import _empty_stats
    stats = _empty_stats()
    assert "title_alias" in stats["merges_by_method"]
    assert stats["merges_by_method"]["title_alias"] == 0
```

**Step 2: Run to confirm it fails**

```bash
pytest tests/test_alias_resolution.py::test_empty_stats_has_title_alias_key -v
```

Expected: `AssertionError` (key missing).

**Step 3: Update `_empty_stats`**

In `scripts/alias_resolution.py`, find `_empty_stats()` (line 72) and add `"title_alias": 0`:

```python
def _empty_stats() -> dict:
    return {
        "candidates_considered": 0,
        "merges_applied": 0,
        "merges_by_method": {"pattern": 0, "cooccurrence": 0, "llm": 0, "title_alias": 0},
        "ambiguous_pairs": 0,
        "llm_attempts": 0,
        "llm_confirmed": 0,
        "llm_failed": 0,
    }
```

**Step 4: Run test**

```bash
pytest tests/test_alias_resolution.py::test_empty_stats_has_title_alias_key -v
```

Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-261): track title_alias in stats"
```

---

### Task 5: Wire `_detect_title_alias` into `resolve_aliases` — tests first

**Files:**
- Test: `tests/test_alias_resolution.py`
- Modify: `scripts/alias_resolution.py:428-501`

**Step 1: Write failing integration tests**

Add to `tests/test_alias_resolution.py`:

```python
def test_resolve_aliases_title_alias_with_llm_merges():
    """Title alias pair is merged when LLM confirms same_person."""
    from scripts.alias_resolution import resolve_aliases
    captain = {
        "canonical_name": "Captain Westfall",
        "type": "PERSON",
        "aliases": ["Captain Westfall"],
        "source_ids": [],
        "relevant": True,
    }
    chaol = {
        "canonical_name": "Chaol Westfall",
        "type": "PERSON",
        "aliases": ["Chaol Westfall", "Chaol"],
        "source_ids": [],
        "relevant": True,
    }

    def confirm_yes(candidate):
        return {"same_person": True, "confidence": "high", "evidence": "same person"}

    result = resolve_aliases(
        [captain, chaol],
        persons_full={},
        llm_confirmer=confirm_yes,
        role_words=["captain"],
    )
    assert len(result["entities"]) == 1
    entity = result["entities"][0]
    assert "Captain Westfall" in entity["aliases"] or "Chaol Westfall" in entity["aliases"]
    assert result["stats"]["merges_applied"] == 1
    assert result["stats"]["llm_confirmed"] == 1


def test_resolve_aliases_title_alias_without_llm_increments_ambiguous():
    """Title alias pair is not merged when no LLM confirmer available."""
    from scripts.alias_resolution import resolve_aliases
    captain = {
        "canonical_name": "Captain Westfall",
        "type": "PERSON",
        "aliases": ["Captain Westfall"],
        "source_ids": [],
        "relevant": True,
    }
    chaol = {
        "canonical_name": "Chaol Westfall",
        "type": "PERSON",
        "aliases": ["Chaol Westfall"],
        "source_ids": [],
        "relevant": True,
    }
    result = resolve_aliases(
        [captain, chaol],
        persons_full={},
        llm_confirmer=None,
        role_words=["captain"],
    )
    assert len(result["entities"]) == 2
    assert result["stats"]["merges_applied"] == 0
    assert result["stats"]["ambiguous_pairs"] == 1


def test_resolve_aliases_title_alias_llm_rejects_no_merge():
    """Title alias pair is not merged when LLM says same_person=False."""
    from scripts.alias_resolution import resolve_aliases
    captain = {
        "canonical_name": "Captain Flint",
        "type": "PERSON",
        "aliases": ["Captain Flint"],
        "source_ids": [],
        "relevant": True,
    }
    flint = {
        "canonical_name": "Flint",
        "type": "PERSON",
        "aliases": ["Flint"],
        "source_ids": [],
        "relevant": True,
    }

    def confirm_no(candidate):
        return {"same_person": False, "confidence": "high", "evidence": "different people"}

    result = resolve_aliases(
        [captain, flint],
        persons_full={},
        llm_confirmer=confirm_no,
        role_words=["captain"],
    )
    assert len(result["entities"]) == 2
    assert result["stats"]["merges_applied"] == 0
```

**Step 2: Run to confirm they fail**

```bash
pytest tests/test_alias_resolution.py -k "resolve_aliases_title_alias" -v
```

Expected: `TypeError` (unexpected keyword argument `role_words`).

---

### Task 6: Update `resolve_aliases` signature and inner loop

**Files:**
- Modify: `scripts/alias_resolution.py:428-501`

**Step 1: Add `role_words` parameter to `resolve_aliases`**

Change the function signature at line 428:

```python
def resolve_aliases(
    entities: list[dict],
    persons_full: dict,
    narrator=None,
    llm_confirmer=None,
    reveal_words=_REVEAL_WORDS,
    role_words: list[str] | None = None,
) -> dict:
```

Add at the start of the function body (after `stats = _empty_stats()`):

```python
    role_words = role_words or []
```

**Step 2: Insert title-alias detection into the inner loop**

In the inner loop, after the `_detect_pattern_match` block (after line 461 `break`) and before the `_detect_reveal_signal` call (line 463), insert:

```python
            title = _detect_title_alias(entity, candidate, role_words)
            if title:
                if llm_confirmer is None:
                    stats["ambiguous_pairs"] += 1
                    continue
                stats["llm_attempts"] += 1
                try:
                    decision = llm_confirmer({
                        "entity_a": entity,
                        "entity_b": candidate,
                        "evidence": title,
                        "persons_full": persons_full,
                    }) or {}
                except Exception:
                    stats["llm_failed"] += 1
                    stats["ambiguous_pairs"] += 1
                    continue
                if decision.get("same_person"):
                    merged_evidence = {
                        "method": "title_alias",
                        "confidence": decision.get("confidence", "medium"),
                        "snippet": decision.get("evidence", title["snippet"]),
                    }
                    merged = _merge_entities(entity, candidate, merged_evidence, persons_full)
                    stats["merges_applied"] += 1
                    stats["merges_by_method"]["title_alias"] += 1
                    stats["llm_confirmed"] += 1
                    consumed.add(candidate_index)
                    break
                stats["ambiguous_pairs"] += 1
                continue
```

**Step 3: Run integration tests**

```bash
pytest tests/test_alias_resolution.py -k "resolve_aliases_title_alias" -v
```

Expected: all 3 tests PASS.

**Step 4: Run full test suite**

```bash
pytest -q
```

Expected: all pass.

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-261): wire _detect_title_alias into resolve_aliases"
```

---

### Task 7: Propagate `role_words` from `main()`

**Files:**
- Modify: `scripts/alias_resolution.py:504-548` (the `main()` function)

**Step 1: Write the failing test**

Add to `tests/test_alias_resolution.py`:

```python
def test_script_role_words_propagated_from_ctx(tmp_path):
    """main() passes role_words from book YAML ctx to resolve_aliases."""
    import subprocess, json, textwrap
    # Minimal book YAML with role_words
    ctx_yaml = textwrap.dedent("""
        file_path: dummy.epub
        use_llm: false
        role_words:
          - captain
    """)
    # Two PERSON entities: Captain X + X — if role_words reaches resolve_aliases,
    # they become an ambiguous_pair (no LLM). Without role_words, they'd be skipped.
    payload = {
        "additional_context": ctx_yaml,
        "previous_outputs": {
            "resolve-clusters": {
                "entities": [
                    {"canonical_name": "Captain Xander", "type": "PERSON",
                     "aliases": ["Captain Xander"], "source_ids": [], "relevant": True},
                    {"canonical_name": "Xander", "type": "PERSON",
                     "aliases": ["Xander"], "source_ids": [], "relevant": True},
                ],
                "narrator": None,
            }
        },
        "all_stage_outputs": {},
    }
    result = subprocess.run(
        ["python", "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=str(tmp_path.parent.parent.parent.parent.parent),  # project root
    )
    # Should not crash
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    # With use_llm=false and a title-alias pair, we get an ambiguous_pair recorded
    assert output["stats"]["ambiguous_pairs"] >= 1
```

> **Note:** This test uses subprocess to call `main()` because it exercises the full stdin/stdout contract. If the test is flaky due to `tmp_path` path resolution, replace the `cwd` with the hardcoded project root from `Path(__file__).parents[1]`.

**Step 2: Run to confirm it fails or passes ambiguously (role_words not yet wired)**

```bash
pytest tests/test_alias_resolution.py::test_script_role_words_propagated_from_ctx -v
```

Expected: FAIL — `ambiguous_pairs == 0` because `role_words` not propagated yet.

**Step 3: Update `main()` to read and pass `role_words`**

In `scripts/alias_resolution.py`, in `main()`, after the line `reveal_words = tuple(...)` (line 515), add:

```python
    role_words: list[str] = list(ctx.get("role_words", []))
```

Then update the `resolve_aliases(...)` call (line 544) to pass `role_words`:

```python
    result = resolve_aliases(
        entities, persons_full=persons_full, narrator=narrator,
        llm_confirmer=llm_confirmer, reveal_words=reveal_words,
        role_words=role_words,
    )
```

**Step 4: Run the test**

```bash
pytest tests/test_alias_resolution.py::test_script_role_words_propagated_from_ctx -v
```

Expected: PASS.

**Step 5: Run full test suite**

```bash
pytest -q
```

Expected: all pass.

**Step 6: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-261): propagate role_words from book YAML ctx to resolve_aliases"
```

---

### Task 8: Final verification

**Step 1: Run full test suite one last time**

```bash
pytest -q
```

Expected: all pass (288+ tests).

**Step 2: Confirm `mypy` is clean on the modified file**

```bash
mypy scripts/alias_resolution.py
```

Expected: `Success: no issues found`.

**Step 3: Commit if any fixes were needed; otherwise done**

If mypy raised issues, fix and commit. Otherwise, the implementation is complete.
