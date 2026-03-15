# STU-255 Mixed-Type Entity Clustering Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow `entity-clustering` to merge matching entities across conflicting extracted types and resolve each cluster to one dominant type deterministically.

**Architecture:** Keep the change local to `scripts/entity_clustering.py`. Union-find will no longer reject candidate pairs solely due to type mismatch, and final cluster typing will be resolved from member evidence using weighted mention counts with a fixed tie-break order. The emitted cluster contract stays unchanged so downstream stages do not need structural changes.

**Tech Stack:** Python, pytest, Studio pipeline scripts

---

### Task 1: Add failing mixed-type clustering tests

**Files:**
- Modify: `tests/test_entity_clustering.py`
- Test: `tests/test_entity_clustering.py`

**Step 1: Write the failing test**

Add tests covering:

- same-name or alias-compatible entities with different extracted types merging into one cluster
- resolved cluster type following the largest weighted evidence total
- deterministic type tie-breaking

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_entity_clustering.py -q`
Expected: FAIL on the new mixed-type assertions because current code blocks cross-type merges.

**Step 3: Write minimal implementation**

Do not change production code in this task.

**Step 4: Run test to verify it still fails**

Run: `pytest tests/test_entity_clustering.py -q`
Expected: same failure.

**Step 5: Commit**

```bash
git add tests/test_entity_clustering.py
git commit -m "test: cover mixed-type entity clustering"
```

### Task 2: Implement dominant-type resolution in clustering

**Files:**
- Modify: `scripts/entity_clustering.py`
- Test: `tests/test_entity_clustering.py`

**Step 1: Write the failing test**

Use the tests from Task 1 as the red state.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_entity_clustering.py -q`
Expected: FAIL on mixed-type clustering behavior.

**Step 3: Write minimal implementation**

Implement:

- cluster member weighting helper based on `mention_count` fallback
- deterministic type precedence helper
- dominant-type selection for cluster and single wrappers
- removal of the same-type union guard in `build_clusters`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_entity_clustering.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/entity_clustering.py tests/test_entity_clustering.py
git commit -m "feat: resolve mixed-type entity clusters by dominant type"
```

### Task 3: Verify pipeline compatibility

**Files:**
- Modify: none expected
- Test: `tests/test_entity_clustering.py`
- Test: `tests/test_split_clusters.py`
- Test: `tests/test_verify_entity_types.py`

**Step 1: Write the failing test**

No new test required if current downstream tests already cover the contract.

**Step 2: Run test to verify it fails**

Not applicable unless a downstream regression appears.

**Step 3: Write minimal implementation**

Only patch downstream code if the unchanged cluster contract still causes failures.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_entity_clustering.py tests/test_split_clusters.py tests/test_verify_entity_types.py -q`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/entity_clustering.py tests/test_entity_clustering.py tests/test_split_clusters.py tests/test_verify_entity_types.py
git commit -m "test: verify clustering contract compatibility"
```

### Task 4: Run shared verification

**Files:**
- Modify: none
- Test: `tests/`

**Step 1: Write the failing test**

No new test.

**Step 2: Run test to verify it fails**

Not applicable.

**Step 3: Write minimal implementation**

No code changes expected.

**Step 4: Run test to verify it passes**

Run: `pytest -q`
Expected: PASS

**Step 5: Commit**

```bash
git add docs/plans/2026-03-11-stu-255-mixed-type-entity-clustering-design.md docs/plans/2026-03-11-stu-255-mixed-type-entity-clustering-plan.md scripts/entity_clustering.py tests/test_entity_clustering.py
git commit -m "docs: plan mixed-type entity clustering"
```
