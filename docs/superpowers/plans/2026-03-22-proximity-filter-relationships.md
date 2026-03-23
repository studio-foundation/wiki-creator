# Proximity Filter for Relationship Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Exclude relationship pairs from classification when their two entity names never appear within 1 sentence of each other — eliminating hallucinated relationships caused by co-presence without direct interaction.

**Architecture:** Change `_tightest_span` to return `None` when the two names are more than `_MAX_DIRECT_INTERACTION_GAP = 1` sentence apart (or when either name is missing). Update `build_cooccurrence_graph` to skip `None` contexts and exclude pairs that end up with zero valid proximity contexts. Pairs excluded this way never reach the classifier.

**Tech Stack:** Python, pytest, `scripts/relationship_extraction.py`, `tests/test_relationship_extraction.py`

---

## Context

The current co-occurrence graph stores up to 3 `sample_contexts` per entity pair using a 5-sentence sliding window. `_tightest_span` currently keeps sentences that mention *either* name (OR logic), so a context can look like:

> "Nehemia insisted on joining. [next sentence] It was clear **Cain** and Celaena would ultimately face each other."

The LLM receives this, sees both names, and invents a relationship. The fix: only store a context when both names appear within 1 sentence of each other. Pairs with zero such contexts are dropped entirely — they never reach the classifier.

---

## Files Changed

| File | Change |
|---|---|
| `scripts/relationship_extraction.py` | New `_MAX_DIRECT_INTERACTION_GAP` constant; rewrite `_tightest_span`; update context storage and output filter in `build_cooccurrence_graph` |
| `tests/test_relationship_extraction.py` | Update 4 tests with stale expected values; add 4 new tests |

---

## Task 1 — Update stale tests to reflect the new expected behavior

These tests currently pass but assert the OLD behavior. They must be updated before implementing, so they become RED (failing) and act as the spec for the new implementation.

**File:** `tests/test_relationship_extraction.py`

- [ ] **Step 1: Update `test_tightest_span_spans_two_sentences_when_names_separated`**

  Change the scenario from gap=2 (names two sentences apart, which will now return `None`) to gap=1 (adjacent sentences), and assert both are in the result.

  ```python
  def test_tightest_span_spans_two_sentences_when_names_separated():
      """Names in adjacent sentences (gap=1) must be returned as a 2-sentence span."""
      from scripts.relationship_extraction import _tightest_span
      window = [
          "Dorian entered the hall.",
          "Hollin ran toward him.",      # gap=1 — valid proximity
          "The king watched from afar.",
      ]
      result = _tightest_span(window, "dorian", "hollin")
      assert result is not None
      assert "Dorian" in result
      assert "Hollin" in result
  ```

- [ ] **Step 2: Update `test_tightest_span_excludes_sentences_with_neither_name`**

  With gap=3 between names, the new impl returns `None`. Assert that.

  ```python
  def test_tightest_span_excludes_sentences_with_neither_name():
      """Names more than 1 sentence apart must return None — no direct interaction evidence."""
      from scripts.relationship_extraction import _tightest_span
      window = [
          "Dorian entered the hall.",
          "The fireplace crackled.",
          "The prince watched from afar.",
          "Hollin ran toward him.",          # gap=3 from Dorian
      ]
      result = _tightest_span(window, "dorian", "hollin")
      assert result is None
  ```

- [ ] **Step 3: Update `test_tightest_span_keeps_sentences_with_one_name`**

  The best match in this window is sent 1 (both names, gap=0). The OR-logic test that expected `"did not answer"` (sent 2, only Hollin) is replaced by a test that confirms only the tight 2-sentence span is returned when names are in adjacent sentences.

  ```python
  def test_tightest_span_returns_closest_pair_span():
      """When names appear multiple times, return the span around the closest pair."""
      from scripts.relationship_extraction import _tightest_span
      window = [
          "Dorian entered the hall.",        # Dorian @ 0
          "Dorian looked at Hollin.",        # both @ 1 — gap=0, best pair
          "Hollin did not answer.",          # Hollin @ 2
      ]
      result = _tightest_span(window, "dorian", "hollin")
      assert result is not None
      # Best pair is sentence 1 (gap=0), so only that sentence is returned
      assert "Dorian" in result
      assert "Hollin" in result
      assert "did not answer" not in result   # sent 2 not included (best gap is 0, not 1)
  ```

- [ ] **Step 4: Update `test_tightest_span_fallback_when_name_not_found`**

  Old behavior: return `window[0]`. New behavior: return `None`.

  ```python
  def test_tightest_span_returns_none_when_name_not_found():
      """If either name is absent from the window, return None — no evidence possible."""
      from scripts.relationship_extraction import _tightest_span
      window = ["Some unrelated sentence.", "Another sentence."]
      result = _tightest_span(window, "dorian", "hollin")
      assert result is None
  ```

- [ ] **Step 5: Run the 4 updated tests, confirm they now FAIL**

  ```bash
  pytest tests/test_relationship_extraction.py::test_tightest_span_spans_two_sentences_when_names_separated \
         tests/test_relationship_extraction.py::test_tightest_span_excludes_sentences_with_neither_name \
         tests/test_relationship_extraction.py::test_tightest_span_returns_closest_pair_span \
         tests/test_relationship_extraction.py::test_tightest_span_returns_none_when_name_not_found \
         -v
  ```

  Expected: **4 FAILED** — the old implementation doesn't match the new assertions.

---

## Task 2 — Add 3 new tests for proximity logic and exclusion

**File:** `tests/test_relationship_extraction.py`

- [ ] **Step 1: Add `test_tightest_span_returns_none_when_names_too_far_apart`**

  Explicitly tests that gap=2 (one sentence between the names) returns `None`.

  ```python
  def test_tightest_span_returns_none_when_names_too_far_apart():
      """Names separated by more than 1 sentence (gap=2) must return None."""
      from scripts.relationship_extraction import _tightest_span
      window = [
          "Nehemia entered the hall.",
          "The crowd murmured.",          # neither name
          "Cain flexed his arms.",        # gap=2 from Nehemia
      ]
      result = _tightest_span(window, "cain", "nehemia")
      assert result is None
  ```

- [ ] **Step 2: Add `test_tightest_span_uses_closest_pair_when_multiple_occurrences`**

  When name_a appears at index 0 (gap=3 from name_b) AND at index 2 (gap=1 from name_b at 3), use the closest pair.

  ```python
  def test_tightest_span_uses_closest_pair_when_multiple_occurrences():
      """When a name appears multiple times, use the pair with minimum gap."""
      from scripts.relationship_extraction import _tightest_span
      window = [
          "Cain entered first.",          # Cain @ 0 — gap=3 from Nehemia @ 3
          "The hall was silent.",
          "Cain looked up.",              # Cain @ 2 — gap=1 from Nehemia @ 3
          "Nehemia stepped forward.",     # Nehemia @ 3
      ]
      result = _tightest_span(window, "cain", "nehemia")
      assert result is not None
      # Should use the closest pair: Cain@2 + Nehemia@3 (gap=1)
      assert "Cain looked up" in result
      assert "Nehemia stepped forward" in result
      assert "Cain entered first" not in result   # farther pair not included
  ```

- [ ] **Step 3: Add `test_build_cooccurrence_graph_excludes_pairs_without_proximity_context`**

  A pair where both names only ever appear in the same window but always more than 1 sentence apart must be excluded from the output entirely.

  ```python
  def test_build_cooccurrence_graph_excludes_pairs_without_proximity_context():
      """Pairs whose names never appear within 1 sentence of each other must be excluded."""
      from scripts.relationship_extraction import build_cooccurrence_graph

      entities = [
          {"canonical_name": "Cain", "type": "PERSON", "aliases": [], "relevant": True},
          {"canonical_name": "Nehemia", "type": "PERSON", "aliases": [], "relevant": True},
      ]
      # Names appear in same window but always gap>=2 apart
      mentions = {
          "Cain": {"ch01": [
              "Nehemia watched the competition.",   # Nehemia @ 0
              "The crowd cheered loudly.",          # gap filler @ 1
              "Cain flexed his arms.",              # Cain @ 2 — gap=2 from Nehemia
          ]},
          "Nehemia": {"ch01": [
              "Nehemia watched the competition.",
              "The crowd cheered loudly.",
              "Cain flexed his arms.",
          ]},
      }
      rels, _ = build_cooccurrence_graph(
          entities, mentions, window_size=5, min_cooccurrence=1, min_chapters_together=1
      )
      names_in_output = {(r["entity_a"], r["entity_b"]) for r in rels}
      assert ("Cain", "Nehemia") not in names_in_output
      assert ("Nehemia", "Cain") not in names_in_output
  ```

- [ ] **Step 4: Run all 3 new tests, confirm they FAIL**

  ```bash
  pytest tests/test_relationship_extraction.py::test_tightest_span_returns_none_when_names_too_far_apart \
         tests/test_relationship_extraction.py::test_tightest_span_uses_closest_pair_when_multiple_occurrences \
         tests/test_relationship_extraction.py::test_build_cooccurrence_graph_excludes_pairs_without_proximity_context \
         -v
  ```

  Expected: **3 FAILED**

---

## Task 3 — Implement the changes

**File:** `scripts/relationship_extraction.py`

- [ ] **Step 1: Add `_MAX_DIRECT_INTERACTION_GAP` constant after `DEFAULT_MIN_CHAPTERS_TOGETHER`**

  ```python
  # At line ~87, after DEFAULT_MIN_CHAPTERS_TOGETHER:
  _MAX_DIRECT_INTERACTION_GAP = 1  # max sentence distance to qualify as direct interaction
  ```

- [ ] **Step 2: Replace `_tightest_span` implementation (lines 91–107)**

  ```python
  def _tightest_span(window: list[str], name_a: str, name_b: str) -> str | None:
      """Return the minimal sentence span around the closest co-occurrence of name_a
      and name_b, if they appear within _MAX_DIRECT_INTERACTION_GAP sentences of each other.

      Returns None if either name is absent from the window, or if the closest pair
      is farther apart than _MAX_DIRECT_INTERACTION_GAP — indicating co-presence without
      direct interaction.
      """
      pat_a = re.compile(r'\b' + re.escape(name_a.lower()) + r'\b')
      pat_b = re.compile(r'\b' + re.escape(name_b.lower()) + r'\b')

      indices_a = [i for i, s in enumerate(window) if pat_a.search(s.lower())]
      indices_b = [i for i, s in enumerate(window) if pat_b.search(s.lower())]

      if not indices_a or not indices_b:
          return None

      best_gap: int | None = None
      best_lo, best_hi = 0, 0
      for ia in indices_a:
          for ib in indices_b:
              gap = abs(ia - ib)
              if best_gap is None or gap < best_gap:
                  best_gap = gap
                  best_lo = min(ia, ib)
                  best_hi = max(ia, ib)

      if best_gap > _MAX_DIRECT_INTERACTION_GAP:
          return None

      return " ".join(window[best_lo : best_hi + 1])
  ```

- [ ] **Step 3: Update context storage in `build_cooccurrence_graph` (line ~200–201)**

  Old:
  ```python
  if len(cooc[key]["contexts"]) < 3:
      cooc[key]["contexts"].append(_tightest_span(window, a, b))
  ```

  New:
  ```python
  span = _tightest_span(window, a, b)
  if span is not None and len(cooc[key]["contexts"]) < 3:
      cooc[key]["contexts"].append(span)
  ```

- [ ] **Step 4: Update output filter in `build_cooccurrence_graph` (line ~205–206)**

  Old:
  ```python
  if data["count"] >= effective_min_cooc and len(data["chapters"]) >= min_chapters_together:
  ```

  New:
  ```python
  if (data["count"] >= effective_min_cooc
          and len(data["chapters"]) >= min_chapters_together
          and len(data["contexts"]) > 0):
  ```

- [ ] **Step 5: Run the 7 targeted tests, confirm they all pass**

  ```bash
  pytest tests/test_relationship_extraction.py::test_tightest_span_spans_two_sentences_when_names_separated \
         tests/test_relationship_extraction.py::test_tightest_span_excludes_sentences_with_neither_name \
         tests/test_relationship_extraction.py::test_tightest_span_returns_closest_pair_span \
         tests/test_relationship_extraction.py::test_tightest_span_returns_none_when_name_not_found \
         tests/test_relationship_extraction.py::test_tightest_span_returns_none_when_names_too_far_apart \
         tests/test_relationship_extraction.py::test_tightest_span_uses_closest_pair_when_multiple_occurrences \
         tests/test_relationship_extraction.py::test_build_cooccurrence_graph_excludes_pairs_without_proximity_context \
         -v
  ```

  Expected: **7 PASSED**

---

## Task 4 — Full suite + commit

- [ ] **Step 1: Run the full test suite**

  ```bash
  pytest -q
  ```

  Expected: baseline is `485 passed` (per CLAUDE.md). Count may vary slightly depending on tests added in this plan, but no pre-existing passing tests should break. One pre-existing failure (`test_wiki_resolution_pipeline_alias_resolution_runs_after_merge_and_relationship`) is known and unrelated.

- [ ] **Step 2: If any unexpected failures, investigate and fix**

  Check `test_build_cooccurrence_graph_sample_contexts_contain_both_names` (line 697) — it should still pass because Dorian@1 and Hollin@2 are gap=1 in the test fixture.

- [ ] **Step 3: Commit**

  ```bash
  git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
  git commit -m "fix(relationship-extraction): proximity filter — only keep contexts where names are within 1 sentence

  _tightest_span now returns None when the closest name pair is more than
  _MAX_DIRECT_INTERACTION_GAP (1) sentences apart, instead of returning a
  joined span of OR-filtered sentences. build_cooccurrence_graph skips None
  spans and excludes pairs that accumulate zero valid proximity contexts.

  This prevents the classifier from receiving co-presence-only evidence and
  hallucinating relationship types for pairs that never directly interact."
  ```

---

## Verification

After the commit, re-run the wiki-resolution pipeline:

```bash
make run-from-resolution
```

Then check `relationships_classified.json`:

```bash
python -c "
import json
data = json.load(open('library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/relationships_classified.json'))
rels = data['relationships']
print(f'Total pairs: {len(rels)}')
for r in rels:
    print(r['entity_a'], '↔', r['entity_b'], '->', r.get('relationship_type'), '|', r.get('cooccurrence_count'))
"
```

Expected outcomes:
- `Cain ↔ Nehemia` should be absent (names never within 1 sentence)
- `Celaena ↔ Verin` should be absent or have valid proximity contexts
- Total pairs likely reduced from 19 to a smaller set of genuinely interacting pairs
- No `null` relationship types from the classifier (pairs without evidence were removed before classification)
