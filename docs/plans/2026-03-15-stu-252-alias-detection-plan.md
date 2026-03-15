# STU-252 Alias Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expose a clean `detect_named_aliases` public interface and replace the keyword-based co-occurrence heuristic with a proper 300-token window scan.

**Architecture:** All changes are local to `scripts/alias_resolution.py` and `tests/test_alias_resolution.py`. Add `AliasPair` TypedDict, add `detect_named_aliases` public function, extend pattern templates, replace `_detect_reveal_signal` with `_detect_cooccurrence_window`. The existing `resolve_aliases` pipeline function calls `detect_named_aliases` internally.

**Tech Stack:** Python 3.11, pytest, re, typing

---

### Task 1: Add AliasPair type and failing tests for detect_named_aliases

**Files:**
- Modify: `tests/test_alias_resolution.py`

**Step 1: Write the failing tests**

Append to `tests/test_alias_resolution.py`:

```python
from scripts.alias_resolution import detect_named_aliases


def test_detect_named_aliases_pattern_high_confidence():
    mentions = {
        "Celaena": ["Celaena smiled. You may call me Lillian, she said."],
        "Lillian": ["You may call me Lillian, she said."],
    }
    pairs = detect_named_aliases(mentions, text="")
    assert len(pairs) == 1
    assert pairs[0]["entity_a"] == "Celaena"
    assert pairs[0]["entity_b"] == "Lillian"
    assert pairs[0]["confidence"] == "high"
    assert pairs[0]["source"] == "pattern"


def test_detect_named_aliases_no_evidence_returns_empty():
    mentions = {
        "Celaena": ["Celaena entered the room."],
        "Dorian": ["Dorian watched the door."],
    }
    pairs = detect_named_aliases(mentions, text="Celaena entered the room. Dorian watched the door.")
    assert pairs == []


def test_detect_named_aliases_window_cooccurrence():
    # Build a text where Celaena and Aelin appear within 300 tokens, twice
    window = "Celaena " + "word " * 50 + "Aelin "
    text = (window * 3).strip()
    mentions = {
        "Celaena": [window],
        "Aelin": [window],
    }
    pairs = detect_named_aliases(mentions, text=text)
    assert len(pairs) == 1
    assert pairs[0]["source"] == "cooccurrence"
    assert pairs[0]["confidence"] == "medium"


def test_detect_named_aliases_window_below_threshold_returns_empty():
    # Only one shared window — below threshold of 2
    window = "Celaena " + "word " * 50 + "Aelin "
    mentions = {
        "Celaena": [window],
        "Aelin": [window],
    }
    pairs = detect_named_aliases(mentions, text=window)
    assert pairs == []


def test_detect_named_aliases_née_pattern():
    mentions = {
        "Jane Smith": ["Jane Smith, née Austen, entered."],
        "Austen": ["née Austen"],
    }
    pairs = detect_named_aliases(mentions, text="")
    assert len(pairs) == 1
    assert pairs[0]["confidence"] == "high"


def test_detect_named_aliases_known_as_pattern():
    mentions = {
        "David": ["David, known as El Príncipe, walked in."],
        "El Príncipe": ["known as El Príncipe"],
    }
    pairs = detect_named_aliases(mentions, text="")
    assert len(pairs) == 1
    assert pairs[0]["confidence"] == "high"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_alias_resolution.py::test_detect_named_aliases_pattern_high_confidence -v`
Expected: `ImportError` or `AttributeError` — `detect_named_aliases` not yet defined.

**Step 3: No implementation yet**

**Step 4: Confirm still failing**

Run: `pytest tests/test_alias_resolution.py -k "detect_named_aliases" -v`
Expected: all 6 new tests FAIL.

**Step 5: Commit**

```bash
git add tests/test_alias_resolution.py
git commit -m "test: add failing tests for detect_named_aliases public interface"
```

---

### Task 2: Add AliasPair type and detect_named_aliases (pattern strategy only)

**Files:**
- Modify: `scripts/alias_resolution.py`

**Step 1: Write the failing test (already written in Task 1)**

**Step 2: Run to confirm failure**

Run: `pytest tests/test_alias_resolution.py::test_detect_named_aliases_pattern_high_confidence -v`
Expected: FAIL

**Step 3: Write minimal implementation**

At the top of `scripts/alias_resolution.py`, after imports, add:

```python
from typing import Literal
try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict


class AliasPair(TypedDict):
    entity_a: str
    entity_b: str
    confidence: Literal["high", "medium"]
    source: Literal["pattern", "cooccurrence"]
    snippet: str
```

Extend `_PATTERN_TEMPLATES` — replace the existing tuple with:

```python
_PATTERN_TEMPLATES = (
    r"\byou may call me {b}\b",
    r"\balso known as {b}\b",
    r"\bformerly known as {b}\b",
    r"\bformerly {b}\b",
    r"\bcalled (?:him|her|them) {b}\b",
    r"\bknown as {b}\b",
    r"\bnée {b}\b",
    r"\b{a}[^.]{{0,80}}\banother name[^.]{{0,80}}\b{b}\b",
    r"\b{a}[^.]{{0,80}}\bunder another name[^.]{{0,80}}\b{b}\b",
)
```

Add after `_REVEAL_WORDS`:

```python
def detect_named_aliases(mentions: dict[str, list[str]], text: str) -> list[AliasPair]:
    """
    Detect alias pairs using two deterministic heuristics (zero LLM).

    Args:
        mentions: mapping of entity canonical_name -> list of context snippets
        text: raw concatenated book text, used for token-window co-occurrence

    Returns:
        list of AliasPair, each with entity_a, entity_b, confidence, source, snippet
    """
    names = list(mentions.keys())
    pairs: list[AliasPair] = []
    seen: set[tuple[str, str]] = set()

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            name_a = names[i]
            name_b = names[j]
            key = (name_a, name_b)
            if key in seen:
                continue

            # Strategy 1: pattern matching
            all_snippets = mentions[name_a] + mentions[name_b]
            evidence = _detect_pattern_for_names(name_a, name_b, all_snippets)
            if evidence:
                seen.add(key)
                pairs.append(AliasPair(
                    entity_a=name_a,
                    entity_b=name_b,
                    confidence="high",
                    source="pattern",
                    snippet=evidence,
                ))
                continue

            # Strategy 2: token-window co-occurrence
            if text:
                window_evidence = _detect_cooccurrence_window(name_a, name_b, text)
                if window_evidence:
                    seen.add(key)
                    pairs.append(AliasPair(
                        entity_a=name_a,
                        entity_b=name_b,
                        confidence="medium",
                        source="cooccurrence",
                        snippet=window_evidence,
                    ))

    return pairs
```

Add the helper `_detect_pattern_for_names` (extracted from existing `_detect_pattern_match`):

```python
def _detect_pattern_for_names(name_a: str, name_b: str, snippets: list[str]) -> str | None:
    """Return the first snippet that matches an alias pattern for name_a/name_b, or None."""
    if name_a.lower() == name_b.lower():
        return None
    pattern_a_b = [
        t.format(a=re.escape(name_a.lower()), b=re.escape(name_b.lower()))
        for t in _PATTERN_TEMPLATES
    ]
    pattern_b_a = [
        t.format(a=re.escape(name_b.lower()), b=re.escape(name_a.lower()))
        for t in _PATTERN_TEMPLATES
    ]
    for snippet in snippets:
        lowered = snippet.lower()
        for pattern in pattern_a_b + pattern_b_a:
            if re.search(pattern, lowered):
                return snippet
    return None
```

Update `_detect_pattern_match` to delegate to `_detect_pattern_for_names`:

```python
def _detect_pattern_match(entity_a: dict, entity_b: dict, persons_full: dict) -> dict | None:
    contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for name_a in names_a:
        for name_b in names_b:
            snippet = _detect_pattern_for_names(name_a, name_b, contexts)
            if snippet:
                return {"method": "pattern", "confidence": "high", "snippet": snippet}
    return None
```

**Step 4: Run pattern tests**

Run: `pytest tests/test_alias_resolution.py -k "detect_named_aliases" -v`
Expected: pattern tests pass, window tests still fail (no `_detect_cooccurrence_window` yet).

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat: add AliasPair type and detect_named_aliases (pattern strategy)"
```

---

### Task 3: Implement token-window co-occurrence strategy

**Files:**
- Modify: `scripts/alias_resolution.py`

**Step 1: Failing test**

Run: `pytest tests/test_alias_resolution.py::test_detect_named_aliases_window_cooccurrence -v`
Expected: FAIL — `_detect_cooccurrence_window` not defined.

**Step 2: Run to confirm failure**

(Same command as above.)

**Step 3: Implement `_detect_cooccurrence_window`**

Add after `_detect_pattern_for_names`:

```python
_WINDOW_SIZE = 300  # tokens


def _detect_cooccurrence_window(
    name_a: str,
    name_b: str,
    text: str,
    threshold: int = 2,
) -> str | None:
    """
    Return a snippet if name_a and name_b co-appear in 2+ distinct 300-token windows.

    Tokenizes by whitespace. A name "matches" a token span if the lowercased joined
    tokens in a small look-ahead contain the lowercased name.
    """
    tokens = text.split()
    if not tokens:
        return None

    na = name_a.lower()
    nb = name_b.lower()

    # Build position lists: token indices where each name starts
    def find_positions(name: str) -> list[int]:
        name_tokens = name.split()
        n = len(name_tokens)
        positions = []
        for idx in range(len(tokens) - n + 1):
            if " ".join(tokens[idx: idx + n]).lower() == name:
                positions.append(idx)
        return positions

    pos_a = find_positions(na)
    pos_b = find_positions(nb)

    if not pos_a or not pos_b:
        return None

    # Count distinct windows (non-overlapping by start of window)
    hit_windows: list[int] = []  # window start indices
    for pa in pos_a:
        window_start = max(0, pa - _WINDOW_SIZE // 2)
        window_end = window_start + _WINDOW_SIZE
        for pb in pos_b:
            if window_start <= pb < window_end:
                # Check this window isn't already covered
                if not any(abs(ws - window_start) < _WINDOW_SIZE for ws in hit_windows):
                    hit_windows.append(window_start)
                    break

    if len(hit_windows) < threshold:
        return None

    # Build snippet from first matching window
    ws = hit_windows[0]
    snippet_tokens = tokens[ws: ws + _WINDOW_SIZE]
    snippet = " ".join(snippet_tokens)
    return snippet[:200]
```

Also update `_detect_reveal_signal` to delegate to the new function so old behaviour is preserved for the pipeline (keeping the existing `resolve_aliases` tests green). Replace the body of `_detect_reveal_signal`:

```python
def _detect_reveal_signal(entity_a: dict, entity_b: dict, persons_full: dict) -> dict | None:
    """Co-occurrence signal using token-window scan over all context snippets."""
    all_contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    text = " ".join(all_contexts)
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for name_a in names_a:
        for name_b in names_b:
            snippet = _detect_cooccurrence_window(name_a, name_b, text)
            if snippet:
                return {"method": "cooccurrence", "confidence": "medium", "snippet": snippet}
    return None
```

**Step 4: Run all alias resolution tests**

Run: `pytest tests/test_alias_resolution.py -v`
Expected: all tests PASS.

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py
git commit -m "feat: implement token-window co-occurrence in detect_named_aliases"
```

---

### Task 4: Full regression check

**Files:**
- No changes

**Step 1: No new test**

**Step 2: N/A**

**Step 3: No implementation**

**Step 4: Run full suite**

Run: `pytest -q`
Expected: all tests pass (≥288).

**Step 5: Commit docs**

```bash
git add docs/plans/2026-03-15-stu-252-alias-detection-design.md docs/plans/2026-03-15-stu-252-alias-detection-plan.md
git commit -m "docs: design and plan for STU-252 alias detection"
```
