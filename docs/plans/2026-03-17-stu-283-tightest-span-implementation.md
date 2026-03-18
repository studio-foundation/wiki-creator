# STU-283 — Tightest Span sample_contexts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix `build_cooccurrence_graph` so `sample_contexts` always contain the two entity names instead of storing `window[0]` (the first sentence, which may be irrelevant).

**Architecture:** Add a pure helper `_tightest_span(window, name_a, name_b) -> str` that returns the minimal contiguous sub-sequence of the window containing both names. Replace the single `window[0]` line with a call to this function. No schema changes.

**Tech Stack:** Python, regex (`re`), `pytest -q`

---

### Task 1: Write failing test for `_tightest_span`

**Files:**
- Modify: `tests/test_relationship_extraction.py` (append at end)

**Step 1: Add the failing test**

```python
# ---------------------------------------------------------------------------
# STU-283: _tightest_span returns minimal span containing both names
# ---------------------------------------------------------------------------

def test_tightest_span_returns_sentence_with_both_names():
    """When both names are in the same sentence, return just that sentence."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "The snow fell hard.",
        "Dorian and Hollin argued bitterly.",
        "The king watched from afar.",
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert "Dorian" in result
    assert "Hollin" in result
    assert "snow" not in result


def test_tightest_span_spans_two_sentences_when_names_separated():
    """When names are in different sentences, return the span between them."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Dorian entered the hall.",
        "The fireplace crackled.",
        "Hollin ran toward him.",
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert "Dorian" in result
    assert "Hollin" in result


def test_tightest_span_fallback_when_name_not_found():
    """If a name is not found at all, return window[0] as a safe fallback."""
    from scripts.relationship_extraction import _tightest_span
    window = ["Some unrelated sentence.", "Another sentence."]
    result = _tightest_span(window, "dorian", "hollin")
    assert result == "Some unrelated sentence."


def test_tightest_span_name_matching_is_case_insensitive():
    """Name lookup must be case-insensitive (matching the detection regex)."""
    from scripts.relationship_extraction import _tightest_span
    window = ["DORIAN met hollin at the gate."]
    result = _tightest_span(window, "dorian", "hollin")
    assert "DORIAN" in result
    assert "hollin" in result
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_relationship_extraction.py::test_tightest_span_returns_sentence_with_both_names tests/test_relationship_extraction.py::test_tightest_span_spans_two_sentences_when_names_separated tests/test_relationship_extraction.py::test_tightest_span_fallback_when_name_not_found tests/test_relationship_extraction.py::test_tightest_span_name_matching_is_case_insensitive -v
```

Expected: `ImportError: cannot import name '_tightest_span'`

---

### Task 2: Implement `_tightest_span`

**Files:**
- Modify: `scripts/relationship_extraction.py`

Find the `build_cooccurrence_graph` function (around line 88). Add `_tightest_span` **just before** it.

**Step 1: Insert the function**

Place this immediately before `def build_cooccurrence_graph(`:

```python
def _tightest_span(window: list[str], name_a: str, name_b: str) -> str:
    """Return the minimal contiguous sub-sequence of ``window`` that contains
    both ``name_a`` and ``name_b`` (case-insensitive, word-boundary match).

    Falls back to ``window[0]`` if either name is not found in any sentence.
    """
    idx_a: int | None = None
    idx_b: int | None = None
    for i, sent in enumerate(window):
        sent_lower = sent.lower()
        if idx_a is None and re.search(r'\b' + re.escape(name_a.lower()) + r'\b', sent_lower):
            idx_a = i
        if idx_b is None and re.search(r'\b' + re.escape(name_b.lower()) + r'\b', sent_lower):
            idx_b = i
    if idx_a is None or idx_b is None:
        return window[0]
    lo, hi = min(idx_a, idx_b), max(idx_a, idx_b)
    return " ".join(window[lo : hi + 1])
```

**Step 2: Run the 4 new tests**

```bash
pytest tests/test_relationship_extraction.py::test_tightest_span_returns_sentence_with_both_names tests/test_relationship_extraction.py::test_tightest_span_spans_two_sentences_when_names_separated tests/test_relationship_extraction.py::test_tightest_span_fallback_when_name_not_found tests/test_relationship_extraction.py::test_tightest_span_name_matching_is_case_insensitive -v
```

Expected: 4 PASSED

**Step 3: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(relationship-extraction): add _tightest_span helper (STU-283)"
```

---

### Task 3: Wire `_tightest_span` into `build_cooccurrence_graph`

**Files:**
- Modify: `scripts/relationship_extraction.py` line ~180

**Step 1: Replace `window[0]` with `_tightest_span`**

Find this block (around line 179):

```python
                    if len(cooc[key]["contexts"]) < 3:
                        cooc[key]["contexts"].append(window[0])
```

Replace with:

```python
                    if len(cooc[key]["contexts"]) < 3:
                        cooc[key]["contexts"].append(_tightest_span(window, a, b))
```

Note: `a` and `b` are the canonical names (already lowercased-compared in detection). Pass them directly — `_tightest_span` lowercases internally.

**Step 2: Write a new integration test for `build_cooccurrence_graph`**

Add to `tests/test_relationship_extraction.py`:

```python
def test_build_cooccurrence_graph_sample_contexts_contain_both_names():
    """sample_contexts must contain both entity names (STU-283)."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Dorian", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Hollin", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    mentions = {
        "Dorian": {
            "ch01": [
                "The snow fell hard.",
                "Dorian entered the hall.",
                "Hollin ran toward him.",
                "They spoke quietly.",
                "The king watched.",
            ]
        },
        "Hollin": {
            "ch01": [
                "The snow fell hard.",
                "Dorian entered the hall.",
                "Hollin ran toward him.",
                "They spoke quietly.",
                "The king watched.",
            ]
        },
    }
    rels, _ = build_cooccurrence_graph(entities, mentions, window_size=5, min_cooccurrence=1, min_chapters_together=1)
    assert rels, "Expected at least one relationship"
    for rel in rels:
        for ctx in rel["sample_contexts"]:
            assert "Dorian" in ctx or "dorian" in ctx.lower(), f"Missing Dorian in: {ctx}"
            assert "Hollin" in ctx or "hollin" in ctx.lower(), f"Missing Hollin in: {ctx}"
```

**Step 3: Run the new integration test**

```bash
pytest tests/test_relationship_extraction.py::test_build_cooccurrence_graph_sample_contexts_contain_both_names -v
```

Expected: PASSED

**Step 4: Run all relationship extraction tests**

```bash
pytest tests/test_relationship_extraction.py -v
```

Expected: all PASSED

**Step 5: Run the full test suite**

```bash
pytest -q
```

Expected: all 489+ tests pass (485 existing + 5 new)

**Step 6: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "fix(relationship-extraction): use tightest span for sample_contexts (STU-283)"
```
