# Chapter Summary Grounding Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the chapter-summary validator flag summary bullets containing proper nouns that never appear in the chapter's source text, so hallucinated names trigger regeneration.

**Architecture:** Add a deterministic `check_grounding` function to `scripts/chapter_summary_validator.py` and wire it into `validate_summary`. The chapter text is already available to the script via `meta["chapter_content"]` (the `additional_context`/`input` payload), so no pipeline or agent YAML changes are needed. On any ungrounded proper noun, the validator returns `valid: false` with feedback, and the existing RALPH group loop (`max_iterations: 3`) regenerates.

**Tech Stack:** Python 3.14, `pytest`, `re` (Unicode-aware, stdlib only — no new deps).

## Global Constraints

- **No hardcoded word lists** in scripts. Vocabulary belongs in `wiki_creator/cue_words/<lang>.json` or book YAML. This heuristic uses the chapter text itself as the allowlist — it must not introduce any stopword/name constant.
- **Degrade gracefully on missing context.** If `chapter_content` is absent/empty, grounding returns no errors (scripts in this repo tolerate missing `additional_context` fields in unit-test mode).
- Match the existing file's style: French error strings prefixed with `❌`, functions returning `list[str]` of error lines, no type-signature change to `validate_summary(summary, meta) -> dict`.
- Verify with `pytest -q` before claiming done (baseline: `735 passed, 31 skipped` as of 2026-07-10).

---

### Task 1: Proper-noun grounding heuristic

**Files:**
- Modify: `scripts/chapter_summary_validator.py`
- Test: `tests/test_chapter_summary_validator.py`

**Interfaces:**
- Consumes: `summary["summary_bullets"]: list[str]`, `meta["chapter_content"]: str` (already parsed from `additional_context` by `parse_payload`).
- Produces: `check_grounding(summary: dict, meta: dict) -> list[str]` (error lines, empty if grounded/uncheckable); `validate_summary` now includes grounding errors in its `errors`/`valid`/`feedback` result.

**Heuristic (reference implementation):**

Tokenizer yields Unicode letter-runs only (splits on digits, punctuation, apostrophes, and hyphens — so `Celaena's`→`Celaena`,`s`; `d'Adarlan`→`d`,`Adarlan`). A bullet token is a *proper-noun candidate* when its first character is uppercase and its length ≥ 2. A candidate is *ungrounded* when its casefolded form is absent from the casefolded set of chapter tokens.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_chapter_summary_validator.py`:

```python
from scripts.chapter_summary_validator import (
    check_temporal_context,
    check_bullets_not_empty,
    check_grounding,
    validate_summary,
)

CHAPTER_TEXT = (
    "Celaena Sardothien est escortée hors des mines d'Endovier par le "
    "capitaine Chaol Westfall. Le prince Dorian l'observe. Duke Perrington "
    "les accompagne jusqu'à Rifthold. Nehemia n'est pas encore arrivée."
)


def _meta():
    return {"chapter_content": CHAPTER_TEXT}


def test_grounding_flags_invented_name():
    summary = {"summary_bullets": ["Le Duke of Niflaren trahit le roi Eadmund."]}
    errors = check_grounding(summary, _meta())
    assert errors != []
    assert "Niflaren" in errors[0]
    assert "Eadmund" in errors[0]


def test_grounding_passes_real_names():
    summary = {"summary_bullets": ["Celaena quitte Endovier avec Chaol et Dorian."]}
    assert check_grounding(summary, _meta()) == []


def test_grounding_ignores_sentence_initial_common_word():
    # "Elle"/"Le" are capitalized at sentence start but appear lowercased in text.
    summary = {"summary_bullets": ["Elle quitte les mines. Le capitaine la suit."]}
    assert check_grounding(summary, _meta()) == []


def test_grounding_handles_possessive():
    summary = {"summary_bullets": ["Celaena's escape from Endovier begins."]}
    # "Celaena" and "Endovier" are in the text; "s" is lowercase and skipped.
    assert check_grounding(summary, _meta()) == []


def test_grounding_handles_accented_name():
    summary = {"summary_bullets": ["Nehemia arrivera bientôt à Rifthold."]}
    assert check_grounding(summary, _meta()) == []


def test_grounding_graceful_without_chapter_text():
    summary = {"summary_bullets": ["Le Duke of Niflaren trahit le roi Eadmund."]}
    assert check_grounding(summary, {}) == []


def test_validate_summary_rejects_hallucinated_names():
    summary = {
        "temporal_context": "present",
        "summary_bullets": ["Le Duke of Niflaren rejoint King Davoth."],
    }
    result = validate_summary(summary, _meta())
    assert result["valid"] is False
    assert any("Niflaren" in e for e in result["errors"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_chapter_summary_validator.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_grounding'` (and the new tests error/fail).

- [ ] **Step 3: Implement `check_grounding` and wire it in**

In `scripts/chapter_summary_validator.py`, add `import re` near the top imports, then add this function (place it above `validate_summary`):

```python
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _letter_tokens(text: str) -> list[str]:
    """Unicode letter-runs only (digits, punctuation, apostrophes, hyphens split)."""
    return _WORD_RE.findall(text or "")


def check_grounding(summary: dict, meta: dict) -> list[str]:
    chapter_text = str((meta or {}).get("chapter_content", "") or "").strip()
    if not chapter_text:
        return []
    text_tokens = {t.casefold() for t in _letter_tokens(chapter_text)}
    ungrounded: list[str] = []
    seen: set[str] = set()
    for bullet in summary.get("summary_bullets", []) or []:
        for tok in _letter_tokens(str(bullet)):
            if len(tok) < 2 or not tok[0].isupper():
                continue
            key = tok.casefold()
            if key in text_tokens or key in seen:
                continue
            seen.add(key)
            ungrounded.append(tok)
    if not ungrounded:
        return []
    reported = ", ".join(ungrounded[:5])
    return [f"❌ Noms/termes absents du texte du chapitre: {reported}"]
```

Then wire it into `validate_summary`:

```python
def validate_summary(summary: dict, meta: dict) -> dict:
    errors: list[str] = []
    errors += check_temporal_context(summary)
    errors += check_bullets_not_empty(summary)
    errors += check_grounding(summary, meta)
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "feedback": build_feedback(errors) if errors else "",
    }
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest tests/test_chapter_summary_validator.py -q`
Expected: PASS (all grounding tests + the 6 pre-existing tests).

- [ ] **Step 5: Run the full suite for regressions**

Run: `pytest -q`
Expected: `741 passed, 31 skipped` (735 prior + 6 new tests; existing `test_validate_summary_valid` still passes because empty `meta` skips grounding).

- [ ] **Step 6: Commit**

```bash
git add scripts/chapter_summary_validator.py tests/test_chapter_summary_validator.py
git commit -m "fix(chapter-summary): flag ungrounded proper nouns in validator (STU-464)"
```

---

## Self-Review

- **Spec coverage:** `check_grounding` design (steps 1–5 of the spec), word-list-free rationale, hard-fail wiring, graceful missing-text degradation, and all seven spec test cases are covered by Task 1. Blind spot (fabricated scenes from real names) is explicitly out of scope — no task, by design.
- **Placeholder scan:** none — all code and commands are concrete.
- **Type consistency:** `check_grounding(summary, meta) -> list[str]` matches the sibling checks; `validate_summary(summary, meta) -> dict` signature unchanged; `_letter_tokens`/`_WORD_RE` used consistently.
