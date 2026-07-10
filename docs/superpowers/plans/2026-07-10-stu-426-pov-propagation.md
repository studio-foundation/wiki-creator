# Narrative POV Propagation (STU-426) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Carry per-chapter narrative POV (type + focal character) from `parse_epub` through chapter summaries and batch files to the writer prompt, so subjective statements from a character's viewpoint are nuanced rather than stated as fact.

**Architecture:** Two layers. Layer 1 propagates the POV *type* — an already-computed-but-discarded signal — along the exact 4-hop path `temporal_context` (STU-271) already uses. Layer 2 adds a new deterministic POV-*character* attributor (`wiki_creator/pov_attribution.py`) gated by a `high/medium/low` certainty label: `high` → trust the deterministic name; otherwise fall back to the existing `chapter-summary-item` LLM agent, or abstain (`null`) in deterministic-only runs.

**Tech Stack:** Python 3, pytest, existing Studio script-executor scripts, `wiki_creator/cue_words/<lang>.json` vocabulary, `wiki_creator/lang.py` config loader.

## Global Constraints

- **No hardcoded word lists in scripts.** All vocabulary (thought markers, name-exclusion words) is read from `cue_words/<lang>.json`. If a key is absent, degrade to an empty collection — never define a fallback constant. (CLAUDE.md invariant.)
- **Confidence is a label, not a float:** `"high" | "medium" | "low"`, matching `detect_pov`'s existing `confidence` vocabulary.
- **Defensive `.get(field, "unknown")` reads at every propagation hop**, matching the `temporal_context` pattern — old runs and partial data must never break.
- **New emitted fields are optional** in `.studio/contracts/chapter-summary-item.contract.yaml` (never `required_fields`), so deterministic mode and older outputs validate unchanged.
- **POV-character attribution runs only when `pov ∈ {first_person, third_limited}`.** `omniscient`/`unknown` → `pov_character: null`.
- Baseline test state to preserve: `pytest -q` → `735 passed, 31 skipped`.

**Canonical per-chapter POV field set** (produced by Task 3, consumed by Tasks 4–5):

```json
{
  "pov": "third_limited",              // "first_person" | "third_limited" | "omniscient" | "unknown"
  "pov_confidence": "high",            // "high" | "medium" | "low" | "unknown"
  "pov_character": "Chaol Westfall",   // str | null
  "pov_character_confidence": "high",  // "high" | "medium" | "low"
  "pov_character_source": "deterministic"  // "deterministic" | "llm" | "none"
}
```

---

### Task 1: Persist per-chapter POV in `parse_epub.py`

Currently `parse_epub` computes per-chapter POV then discards it, keeping only the book-level modal. Refactor the inline block into a testable `annotate_pov` helper that **persists** `pov`/`pov_confidence` onto each chapter dict and **returns** the unchanged modal `pov_detection`.

**Files:**
- Modify: `scripts/parse_epub.py:271-297` (the inline modal block) and `scripts/parse_epub.py:297` (the `return`)
- Test: `tests/test_parse_epub.py`

**Interfaces:**
- Produces: `annotate_pov(chapters: list[dict], language: str = "fr") -> dict`. Mutates each `chapters[i]` in place, adding `chapters[i]["pov"]` (str) and `chapters[i]["pov_confidence"]` (str). Returns the book-level `pov_detection` dict (unchanged shape: keys `pov`, `first_person_count`, `total_tokens`, `confidence`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_parse_epub.py`:

```python
from scripts.parse_epub import annotate_pov


def test_annotate_pov_persists_per_chapter_fields():
    """Each chapter gets its own pov + pov_confidence, not just the book modal."""
    chapters = [
        {"id": "c1", "content": "Je marche. Je pense donc je suis. Je regarde le ciel."},
        {"id": "c2", "content": "Le roi regarda la salle. Les gardes attendaient en silence."},
    ]
    modal = annotate_pov(chapters, language="fr")
    assert chapters[0]["pov"] == "first_person"
    assert chapters[0]["pov_confidence"] in {"high", "medium", "low"}
    assert "pov" in chapters[1] and "pov_confidence" in chapters[1]
    # Book-level modal is still returned with its historical shape.
    assert set(modal) == {"pov", "first_person_count", "total_tokens", "confidence"}


def test_annotate_pov_empty_chapters():
    """No chapters → omniscient modal, no crash."""
    assert annotate_pov([], language="fr")["pov"] == "omniscient"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parse_epub.py::test_annotate_pov_persists_per_chapter_fields -v`
Expected: FAIL with `ImportError: cannot import name 'annotate_pov'`

- [ ] **Step 3: Extract the helper and persist per-chapter POV**

In `scripts/parse_epub.py`, add this function immediately after `detect_pov` (after line 171):

```python
def annotate_pov(chapters: list[dict], language: str = "fr") -> dict:
    """Persist per-chapter POV onto each chapter and return the book-level modal.

    Recovers the per-chapter detail that parse_epub previously discarded: writes
    `pov` and `pov_confidence` onto every chapter dict, then returns the modal
    `pov_detection` (unchanged shape) for backward compatibility.
    """
    if not chapters:
        return {"pov": "omniscient", "first_person_count": 0, "total_tokens": 0, "confidence": "low"}

    chapter_results = [detect_pov(ch["content"], language=language) for ch in chapters]
    for ch, r in zip(chapters, chapter_results):
        ch["pov"] = r["pov"]
        ch["pov_confidence"] = r["confidence"]

    pov_counts: dict[str, int] = {}
    for r in chapter_results:
        pov_counts[r["pov"]] = pov_counts.get(r["pov"], 0) + 1
    modal_pov = max(pov_counts, key=lambda p: pov_counts[p])
    total_fp = sum(r["first_person_count"] for r in chapter_results)
    total_tokens = sum(r["total_tokens"] for r in chapter_results)
    agg_ratio = total_fp / total_tokens if total_tokens > 0 else 0
    if modal_pov == "first_person":
        confidence = "high" if agg_ratio > 0.05 else "medium" if agg_ratio > 0.01 else "low"
    else:
        confidence = "high"
    return {
        "pov": modal_pov,
        "first_person_count": total_fp,
        "total_tokens": total_tokens,
        "confidence": confidence,
    }
```

Then replace the inline block at `scripts/parse_epub.py:271-297` (from the `# Compute POV per chapter` comment through the `else:` branch that builds `pov_detection`) with a single call:

```python
    # Compute per-chapter POV (persisted onto each chapter) + book-level modal.
    pov_detection = annotate_pov(chapters, language=language)

    return {"title": title, "author": author, "chapters": chapters, "pov_detection": pov_detection}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parse_epub.py -v`
Expected: PASS (all existing `detect_pov`/`clean_chapter_text` tests plus the two new ones)

- [ ] **Step 5: Commit**

```bash
git add scripts/parse_epub.py tests/test_parse_epub.py
git commit -m "feat(stu-426): persist per-chapter POV in parse_epub"
```

---

### Task 2: Deterministic POV-character attributor (`wiki_creator/pov_attribution.py`)

A pure, dependency-free module: given chapter text + POV type + cue-word vocab, name the most likely focal character and grade the certainty. This is the only genuinely new logic in the feature.

**Files:**
- Create: `wiki_creator/pov_attribution.py`
- Test: `tests/test_pov_attribution.py`

**Interfaces:**
- Produces: `attribute_pov_character(content: str, pov: str, thought_markers: tuple[str, ...] = (), exclusion_words: tuple[str, ...] = ()) -> dict` returning `{"pov_character": str | None, "pov_character_confidence": "high" | "medium" | "low"}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_pov_attribution.py`:

```python
"""Tests for wiki_creator/pov_attribution.py."""
from wiki_creator.pov_attribution import attribute_pov_character

MARKERS = ("thought", "wondered", "realized", "felt")
EXCLUDE = ("the", "and", "she", "he", "lord", "king")


def test_omniscient_returns_none():
    """Omniscient POV has no single focal character."""
    out = attribute_pov_character("Chaol Chaol Chaol wondered.", "omniscient", MARKERS, EXCLUDE)
    assert out == {"pov_character": None, "pov_character_confidence": "low"}


def test_empty_content_returns_none():
    out = attribute_pov_character("", "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character"] is None


def test_dominant_character_high_confidence():
    """One clearly dominant name near thought markers → high + that name."""
    text = (
        "Chaol wondered about the plan. Chaol felt uneasy. Chaol realized the truth. "
        "Chaol watched the door and thought of home."
    )
    out = attribute_pov_character(text, "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character"] == "Chaol"
    assert out["pov_character_confidence"] == "high"


def test_two_equal_names_not_high():
    """No dominant candidate → not high (medium or low), never a false 'high'."""
    text = "Chaol spoke. Dorian answered. Chaol left. Dorian stayed."
    out = attribute_pov_character(text, "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character_confidence"] != "high"


def test_excluded_words_not_chosen():
    """Title-cased stopwords/roles from cue-words are never the focal character."""
    text = "The The The Lord Lord King King. Celaena felt cold. Celaena felt tired. Celaena moved."
    out = attribute_pov_character(text, "third_limited", MARKERS, EXCLUDE)
    assert out["pov_character"] == "Celaena"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_pov_attribution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki_creator.pov_attribution'`

- [ ] **Step 3: Implement the module**

Create `wiki_creator/pov_attribution.py`:

```python
"""Deterministic POV-character attribution for a single chapter.

Given raw chapter text and its POV *type* (from parse_epub's detect_pov), name
the most likely focal character by capitalized-name frequency, weighted by
proximity to third-person thought markers. Returns a high/medium/low certainty
label so callers can gate on it (high → trust; otherwise fall back to an LLM or
abstain).

All vocabulary — thought markers and name-exclusion words — is passed in from
cue_words/<lang>.json. Nothing is hardcoded here (CLAUDE.md invariant); an empty
vocab simply weakens the signal, it never crashes.

Known limitation: sentence-initial capitalization inflates common words. The
certainty gate is the safeguard — ambiguous chapters resolve to medium/low and
are handled by the LLM fallback or abstention, not a confident wrong guess.
"""
from __future__ import annotations

import re

# POV types that have a single focal character worth attributing.
_SUBJECTIVE_POV = {"first_person", "third_limited"}

# Certainty-gate thresholds (design STU-426). Kept together so the policy is
# tunable in one place.
_MIN_ABS_HIGH = 3      # top candidate must occur >= this many times for "high"
_SHARE_HIGH = 0.5      # ... and hold >= this share of total weighted mass
_MARGIN_HIGH = 0.2     # ... and lead the runner-up by this share of the mass
_SHARE_MEDIUM = 0.35   # medium floor
_PROXIMITY_WINDOW = 8  # tokens; an occurrence within this of a marker gets a bonus
_PROXIMITY_BONUS = 1.0 # extra weight per marker-adjacent occurrence

_STRIP = ".,;:!?\"'()[]«»…—–"
_CAP_RE = re.compile(r"^[A-ZÀ-Ý][\wÀ-ÿ'’\-]+$")


def _clean(token: str) -> str:
    return token.strip(_STRIP)


def attribute_pov_character(
    content: str,
    pov: str,
    thought_markers: tuple[str, ...] = (),
    exclusion_words: tuple[str, ...] = (),
) -> dict:
    none_result = {"pov_character": None, "pov_character_confidence": "low"}
    if pov not in _SUBJECTIVE_POV or not content:
        return none_result

    exclusion = {w.lower() for w in exclusion_words}
    markers = {m.lower() for m in thought_markers}

    tokens = content.split()
    marker_idx = [i for i, t in enumerate(tokens) if _clean(t).lower() in markers]

    counts: dict[str, int] = {}
    weights: dict[str, float] = {}
    i, n = 0, len(tokens)
    while i < n:
        cleaned = _clean(tokens[i])
        if not _CAP_RE.match(cleaned):
            i += 1
            continue
        start = i
        span_tokens: list[str] = []
        while i < n:
            c = _clean(tokens[i])
            if not _CAP_RE.match(c):
                break
            span_tokens.append(c)
            i += 1
        # Drop a span that is a single excluded (title-cased stopword/role) token.
        if len(span_tokens) == 1 and span_tokens[0].lower() in exclusion:
            continue
        span = " ".join(span_tokens)
        counts[span] = counts.get(span, 0) + 1
        weight = 1.0
        if any(abs(start - mi) <= _PROXIMITY_WINDOW for mi in marker_idx):
            weight += _PROXIMITY_BONUS
        weights[span] = weights.get(span, 0.0) + weight

    if not weights:
        return none_result

    ranked = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    top_span, top_w = ranked[0]
    second_w = ranked[1][1] if len(ranked) > 1 else 0.0
    total_w = sum(weights.values())
    top_share = top_w / total_w if total_w else 0.0
    margin = (top_w - second_w) / total_w if total_w else 0.0

    if counts[top_span] >= _MIN_ABS_HIGH and top_share >= _SHARE_HIGH and margin >= _MARGIN_HIGH:
        confidence = "high"
    elif top_share >= _SHARE_MEDIUM:
        confidence = "medium"
    else:
        confidence = "low"
    return {"pov_character": top_span, "pov_character_confidence": confidence}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_pov_attribution.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/pov_attribution.py tests/test_pov_attribution.py
git commit -m "feat(stu-426): deterministic POV-character attributor"
```

---

### Task 3: Emit POV fields from `chapter_summary.py` (type propagation + confidence gate)

Load POV vocab from cue-words, thread it through the summarize functions (mirroring `action_cues`/`flashback_cues`), and add the canonical POV field set to every summary dict via a single `_resolve_pov_fields` gate helper used by both the extractive and LLM-item paths.

**Files:**
- Modify: `scripts/chapter_summary.py` (import; new `_resolve_pov_fields`; signatures of `_summarize_chapter_extractive`, `summarize_chapter`, `summarize_chapter_from_item_result`, `summarize_chapters`, `summarize_chapters_incrementally`; the two entrypoints `_main_from_book` and `_main_from_payload`)
- Modify: `.studio/contracts/chapter-summary-item.contract.yaml`
- Test: `tests/test_chapter_summary.py`

**Interfaces:**
- Consumes: `attribute_pov_character` (Task 2); per-chapter `pov`/`pov_confidence` (Task 1).
- Produces: `_resolve_pov_fields(chapter: dict, thought_markers: tuple[str, ...] = (), exclusion_words: tuple[str, ...] = (), llm_item_result: dict | None = None) -> dict` returning the canonical 5-field POV set. Every summary dict returned by `_summarize_chapter_extractive` and `summarize_chapter_from_item_result` now includes those 5 keys.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_chapter_summary.py`:

```python
from scripts.chapter_summary import _resolve_pov_fields, _summarize_chapter_extractive, ChapterSummaryConfig

_MARKERS = ("wondered", "felt", "realized", "thought")
_EXCLUDE = ("the", "and", "she", "he", "lord")


def test_resolve_pov_fields_deterministic_high():
    chapter = {
        "id": "c1",
        "content": "Chaol wondered. Chaol felt cold. Chaol realized the plan. Chaol thought hard.",
        "pov": "third_limited",
        "pov_confidence": "high",
    }
    out = _resolve_pov_fields(chapter, _MARKERS, _EXCLUDE)
    assert out["pov"] == "third_limited"
    assert out["pov_character"] == "Chaol"
    assert out["pov_character_source"] == "deterministic"


def test_resolve_pov_fields_omniscient_abstains():
    chapter = {"id": "c2", "content": "The court gathered.", "pov": "omniscient", "pov_confidence": "high"}
    out = _resolve_pov_fields(chapter, _MARKERS, _EXCLUDE)
    assert out["pov_character"] is None
    assert out["pov_character_source"] == "none"


def test_resolve_pov_fields_llm_fallback_when_uncertain():
    """Deterministic uncertain + LLM provided a name → source 'llm'."""
    chapter = {"id": "c3", "content": "A spoke. B answered.", "pov": "third_limited", "pov_confidence": "low"}
    llm = {"pov_character": "Celaena", "pov_character_confidence": "high"}
    out = _resolve_pov_fields(chapter, _MARKERS, _EXCLUDE, llm_item_result=llm)
    assert out["pov_character"] == "Celaena"
    assert out["pov_character_source"] == "llm"


def test_extractive_summary_carries_pov_fields():
    chapter = {"id": "c4", "content": "Chaol felt cold. Chaol felt tired. Chaol moved on.", "pov": "third_limited", "pov_confidence": "high"}
    out = _summarize_chapter_extractive(chapter, ChapterSummaryConfig(), thought_markers=_MARKERS, exclusion_words=_EXCLUDE)
    assert "pov" in out and "pov_character" in out and "pov_character_source" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_summary.py::test_resolve_pov_fields_deterministic_high -v`
Expected: FAIL with `ImportError: cannot import name '_resolve_pov_fields'`

- [ ] **Step 3: Add the import and the gate helper**

In `scripts/chapter_summary.py`, after the existing `from wiki_creator.lang import ...` line (line 45), add:

```python
from wiki_creator.pov_attribution import attribute_pov_character
```

Add the gate helper next to `_detect_temporal_context` (after line 187):

```python
def _resolve_pov_fields(
    chapter: dict,
    thought_markers: tuple[str, ...] = (),
    exclusion_words: tuple[str, ...] = (),
    llm_item_result: dict | None = None,
) -> dict:
    """Resolve the canonical per-chapter POV field set.

    Gate: deterministic attribution wins when it is `high`; otherwise use the
    LLM item's `pov_character` when present; otherwise abstain (`null`).
    """
    pov = str(chapter.get("pov", "unknown") or "unknown")
    fields = {
        "pov": pov,
        "pov_confidence": str(chapter.get("pov_confidence", "unknown") or "unknown"),
        "pov_character": None,
        "pov_character_confidence": "low",
        "pov_character_source": "none",
    }
    if pov not in ("first_person", "third_limited"):
        return fields

    det = attribute_pov_character(chapter.get("content", ""), pov, thought_markers, exclusion_words)
    if det["pov_character"] and det["pov_character_confidence"] == "high":
        fields["pov_character"] = det["pov_character"]
        fields["pov_character_confidence"] = "high"
        fields["pov_character_source"] = "deterministic"
        return fields

    if isinstance(llm_item_result, dict) and llm_item_result.get("pov_character"):
        fields["pov_character"] = str(llm_item_result["pov_character"]).strip() or None
        fields["pov_character_confidence"] = str(
            llm_item_result.get("pov_character_confidence", "medium") or "medium"
        )
        fields["pov_character_source"] = "llm" if fields["pov_character"] else "none"
        return fields

    return fields
```

- [ ] **Step 4: Thread the vocab params and emit the fields**

Add `thought_markers`/`exclusion_words` params to each function below, defaulting to `()`, and forward them. Update the return dicts to merge the POV fields.

In `_summarize_chapter_extractive` (line 296) change the signature to:

```python
def _summarize_chapter_extractive(chapter: dict, cfg: ChapterSummaryConfig, method: str = "extractive", seed_flags: list[str] | None = None, action_cues: tuple[str, ...] = (), flashback_cues: tuple[str, ...] = (), thought_markers: tuple[str, ...] = (), exclusion_words: tuple[str, ...] = ()) -> dict:
```

and change its return (line 321-329) to:

```python
    return {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "summary_bullets": bullets,
        "summary_method": method,
        "quality_flags": quality_flags,
        "temporal_context": _detect_temporal_context(chapter.get("content", ""), flashback_cues),
        "flashback_anchor": None,
        **_resolve_pov_fields(chapter, thought_markers, exclusion_words),
    }
```

In `summarize_chapter` (line 332) add the two params and forward to both branches:

```python
def summarize_chapter(chapter: dict, config: ChapterSummaryConfig | None = None, action_cues: tuple[str, ...] = (), flashback_cues: tuple[str, ...] = (), thought_markers: tuple[str, ...] = (), exclusion_words: tuple[str, ...] = ()) -> dict:
    cfg = config or ChapterSummaryConfig()
    if cfg.mode == "llm":
        llm_result = _call_llm_summary(
            chapter=chapter,
            model=cfg.llm_model,
            timeout_seconds=cfg.llm_timeout_seconds,
            max_bullets=cfg.max_bullets,
        )
        return summarize_chapter_from_item_result(chapter, llm_result, config=cfg, action_cues=action_cues, flashback_cues=flashback_cues, thought_markers=thought_markers, exclusion_words=exclusion_words)
    return _summarize_chapter_extractive(chapter, cfg, action_cues=action_cues, flashback_cues=flashback_cues, thought_markers=thought_markers, exclusion_words=exclusion_words)
```

In `summarize_chapter_from_item_result` (line 632) add the two params; pass the LLM result to the gate; forward to the extractive fallback. Signature:

```python
def summarize_chapter_from_item_result(
    chapter: dict,
    item_result: dict | list[str],
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
    flashback_cues: tuple[str, ...] = (),
    thought_markers: tuple[str, ...] = (),
    exclusion_words: tuple[str, ...] = (),
) -> dict:
```

Compute the POV fields once after the `if isinstance(item_result, list)` block (after line 649):

```python
    _pov = _resolve_pov_fields(
        chapter,
        thought_markers,
        exclusion_words,
        llm_item_result=item_result if isinstance(item_result, dict) else None,
    )
```

Merge `**_pov` into the success return (line 652-660) and the final fallback return (line 670-678), and forward the vocab to the `_summarize_chapter_extractive` fallback call (line 661-669):

```python
    if llm_bullets:
        return {
            "chapter_id": str(chapter.get("id", "")).strip(),
            "chapter_title": str(chapter.get("title", "")).strip(),
            "summary_bullets": llm_bullets,
            "summary_method": "llm",
            "quality_flags": [],
            "temporal_context": temporal_context,
            "flashback_anchor": flashback_anchor,
            **_pov,
        }
    if cfg.llm_fallback_to_extractive:
        return _summarize_chapter_extractive(
            chapter,
            cfg,
            method="extractive_fallback",
            seed_flags=([llm_error] if llm_error else []) + ["fallback_used"],
            action_cues=action_cues,
            flashback_cues=flashback_cues,
            thought_markers=thought_markers,
            exclusion_words=exclusion_words,
        )
    return {
        "chapter_id": str(chapter.get("id", "")).strip(),
        "chapter_title": str(chapter.get("title", "")).strip(),
        "summary_bullets": [_FALLBACK_BULLET],
        "summary_method": "llm",
        "quality_flags": [llm_error] if llm_error else [],
        "temporal_context": "unknown",
        "flashback_anchor": None,
        **_pov,
    }
```

In `summarize_chapters` (line 547) and `summarize_chapters_incrementally` (line 584) add the two params and forward them to every `summarize_chapter` / `summarize_chapter_from_item_result` call inside (lines 555, 618, 620).

- [ ] **Step 5: Load the vocab in both entrypoints**

In `_main_from_book` (near line 719) and `_main_from_payload`/`main` (near line 769), after the existing `action_cues`/`flashback_cues` lines, add:

```python
    thought_markers = tuple(lang_config.get("third_person_thought_markers", ()))
    exclusion_words = tuple(
        set(lang_config.get("noise_words", []))
        | set(lang_config.get("false_positive_words", []))
        | set(lang_config.get("determiners", []))
        | set(lang_config.get("role_words", []))
        | set(lang_config.get("pronouns", []))
    )
```

and pass `thought_markers=thought_markers, exclusion_words=exclusion_words` into the `summarize_chapters_incrementally(...)` call in each (lines 739-746 and 775-782).

- [ ] **Step 6: Extend the item contract**

In `.studio/contracts/chapter-summary-item.contract.yaml`, after the `# flashback_anchor:` comment line, add (comments only — these stay OPTIONAL, not in `required_fields`):

```yaml
# pov: "first_person" | "third_limited" | "omniscient" | "unknown"  (optional)
# pov_character: str | null  (optional — the chapter's focal character)
# pov_character_confidence: "high" | "medium" | "low"  (optional, default "medium")
```

- [ ] **Step 7: Extend the LLM agent prompt (enables the fallback to actually produce a name)**

In `.studio/agents/chapter-summary.agent.yaml`, add `pov_character` to the required output object and a short rule block. Change the `Return exactly:` object to include:

```
    "temporal_context": "present" | "flashback" | "mixed" | "unknown",
    "flashback_anchor": "..." | null,
    "pov_character": "..." | null
  }
```

and add after the `flashback_anchor:` rule paragraph:

```
  pov_character: the single character whose viewpoint this chapter is narrated from
  (whose thoughts/feelings the narration follows). Use the character's name as it
  appears in the text. Set to null for an omniscient/multi-viewpoint chapter or when
  in doubt.
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_chapter_summary.py -v`
Expected: PASS (existing tests + 4 new)

- [ ] **Step 9: Commit**

```bash
git add scripts/chapter_summary.py tests/test_chapter_summary.py .studio/contracts/chapter-summary-item.contract.yaml .studio/agents/chapter-summary.agent.yaml
git commit -m "feat(stu-426): emit per-chapter POV fields from chapter summaries"
```

---

### Task 4: Propagate POV fields through `wiki_preparation.py` batch entries

**Files:**
- Modify: `scripts/wiki_preparation.py:317-321` (the per-chapter batch entry in `build_chapter_summary_context`)
- Test: `tests/test_wiki_preparation.py`

**Interfaces:**
- Consumes: summary dicts carrying the canonical POV fields (Task 3).
- Produces: each batch chapter entry gains `pov`, `pov_character`, `pov_character_confidence`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_wiki_preparation.py`:

```python
from scripts.wiki_preparation import build_chapter_summary_context


def test_batch_chapter_entry_carries_pov():
    entity = {"canonical_name": "Chaol", "mentions_by_chapter": {"c1": ["ctx"]}}
    summaries = {
        "c1": {
            "summary_bullets": ["Chaol did a thing."],
            "temporal_context": "present",
            "pov": "third_limited",
            "pov_character": "Chaol",
            "pov_character_confidence": "high",
        }
    }
    out = build_chapter_summary_context(entity, chapter_summaries=summaries, chapter_id_to_title={})
    assert out and out[0]["pov"] == "third_limited"
    assert out[0]["pov_character"] == "Chaol"
    assert out[0]["pov_character_confidence"] == "high"
```

> If `build_chapter_summary_context`'s exact signature differs, read `scripts/wiki_preparation.py:280-322` and adapt the call — the assertion on the emitted keys is what matters.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wiki_preparation.py::test_batch_chapter_entry_carries_pov -v`
Expected: FAIL — `KeyError: 'pov'`

- [ ] **Step 3: Add the fields to the batch entry**

In `scripts/wiki_preparation.py`, change the `result.append({...})` block (lines 317-321) to:

```python
        result.append({
            "chapter_key": chapter_key,
            "summary_bullets": bullets,
            "temporal_context": summary.get("temporal_context", "unknown"),
            "pov": summary.get("pov", "unknown"),
            "pov_character": summary.get("pov_character"),
            "pov_character_confidence": summary.get("pov_character_confidence", "low"),
        })
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wiki_preparation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/wiki_preparation.py tests/test_wiki_preparation.py
git commit -m "feat(stu-426): carry POV fields into batch chapter entries"
```

---

### Task 5: Surface POV to the writer prompt in `generate_wiki_pages.py`

**Files:**
- Modify: `scripts/generate_wiki_pages.py:252-278` (per-chapter summary block loop) and the WRITING RULES block (~line 360)
- Test: `tests/test_generate_wiki_pages.py`

**Interfaces:**
- Consumes: batch chapter entries with `pov`/`pov_character` (Task 4).
- Produces: a per-chapter POV note inside the chapter-summary block, plus a global neutrality rule.

- [ ] **Step 1: Write the failing test**

The prompt is built by `build_prompt(entity, book_title, sections, forbidden_names=None)` (line 182), which reads the chapter list from `entity["chapter_summary_context"]`. Add to `tests/test_generate_wiki_pages.py`:

```python
from scripts.generate_wiki_pages import build_prompt


def _entity_with_chapter(pov, pov_character):
    return {
        "canonical_name": "Chaol",
        "entity_type": "PERSON",
        "importance": "principal",
        "aliases": [],
        "chapter_summary_context": [
            {"chapter_key": "c1", "summary_bullets": ["Something happened."],
             "temporal_context": "present", "pov": pov, "pov_character": pov_character},
        ],
    }


def test_prompt_includes_pov_note_for_limited_pov():
    prompt = build_prompt(_entity_with_chapter("third_limited", "Chaol"), "Book", ["main"])
    assert "Chaol's perspective" in prompt


def test_prompt_no_pov_note_for_omniscient():
    prompt = build_prompt(_entity_with_chapter("omniscient", None), "Book", ["main"])
    assert "perspective —" not in prompt  # no per-chapter POV note emitted
```

> If `build_prompt` raises on this minimal entity (it reads other keys), read `scripts/generate_wiki_pages.py:182-253` and add whatever keys it dereferences before the chapter loop — the assertions on the POV-note text are what matter.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages.py::test_prompt_includes_pov_note_for_limited_pov -v`
Expected: FAIL — the note text is absent.

- [ ] **Step 3: Emit the per-chapter POV note**

In `scripts/generate_wiki_pages.py`, inside the `for chapter in chapter_summary_context[:8]:` loop (lines 254-265), after the `for bullet in ...: entry_lines.append(...)` block and before the `if temporal == "flashback":` branch, add:

```python
        pov = chapter.get("pov", "unknown")
        pov_char = chapter.get("pov_character")
        if pov_char:
            entry_lines.append(
                f"    - POV: narrated from {pov_char}'s perspective — statements about other "
                f"characters may reflect a subjective view, not objective fact."
            )
        elif pov in ("first_person", "third_limited"):
            entry_lines.append(
                "    - POV: subjective narration — some statements may reflect a character's "
                "perception rather than objective fact."
            )
```

- [ ] **Step 4: Add the global neutrality rule**

In the WRITING RULES section, under `Tone and register:` (after line 361, the `- Describe what the entity IS ...` line), add:

```python
- When a chapter summary is tagged with a subjective POV, attribute contested claims to that viewpoint ("selon X", "du point de vue de X") rather than stating them as fact.
```

(Insert this as an extra line inside the existing rules f-string, matching its French register and indentation.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(stu-426): surface subjective POV to the writer prompt"
```

---

### Task 6: Full-suite + smoke verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `pytest -q`
Expected: `>= 739 passed` (baseline 735 + the new tests), `31 skipped`, 0 failed.

- [ ] **Step 2: Type-check the touched modules**

Run: `mypy wiki_creator/pov_attribution.py`
Expected: no errors.

- [ ] **Step 3: End-to-end smoke on the committed fixture novella**

Run: `make smoke`
Expected: completes without error; spot-check that a generated batch file under `wiki_inputs/<slug>/batch_*.json` contains `pov` on its chapter entries.

- [ ] **Step 4: Final commit (if smoke required any fixture/lockfile touch; otherwise skip)**

```bash
git add -A
git commit -m "test(stu-426): verify POV propagation end-to-end"
```

---

## Self-Review

**Spec coverage:**
- Spec Layer 1 (type propagation, 4 hops) → Task 1 (persist), Task 3 (summary), Task 4 (batch), Task 5 (prompt). ✓
- Spec Layer 2 (deterministic attribution + certainty label) → Task 2. ✓
- Spec Layer 2 gate (high → trust; else LLM; else abstain) → Task 3 `_resolve_pov_fields`. ✓
- Spec contract change (optional fields) → Task 3 Step 6. ✓
- Spec writer prompt notes → Task 5. ✓
- Spec "no hardcoded vocab" → Task 3 Step 5 loads exclusion vocab from cue-words; Task 2 takes it as a param. ✓
- Spec "confidence = high/medium/low" → enforced in Task 2 and the field set. ✓
- Spec non-goal "no canonicalization / no new stage / no book-modal change" → respected (Task 1 keeps modal shape; no new pipeline stage). ✓

**Type consistency:** field names `pov`, `pov_confidence`, `pov_character`, `pov_character_confidence`, `pov_character_source` are identical across Tasks 1–5. `attribute_pov_character` returns exactly `{pov_character, pov_character_confidence}`; `_resolve_pov_fields` returns exactly the 5-field set; both match their consumers. ✓

**Placeholder scan:** Task 5 Step 1 intentionally defers to the real prompt-builder name (unknown until the file is read at execution) — the engineer is told exactly how to find it (`rg` command given) and what to assert. All code steps otherwise contain complete code. ✓
