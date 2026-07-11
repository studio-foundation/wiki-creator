# STU-439 — Reconnect Custom NER Ontology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `scripts/entity_extraction.py` keep the custom NER model's PLACE/EVENT/FACTION labels, warn on any label it would silently drop, and make the POS-filter no-op explicit when the model has no tagger.

**Architecture:** All production changes live in `scripts/entity_extraction.py`: two module-level constants updated (`KEPT_LABELS`, `LABEL_TO_TYPE`), one constant added (`IGNORED_LABELS`), two small load-time audit functions added and wired into `main()`, and one guard added in `_is_valid_span`. Tests go in `tests/test_entity_extraction.py` following its existing patterns (module-scoped `nlp` fixture for `en_core_web_sm`, `spacy.blank("en")` pipelines for tagger-less cases, `capsys` for stderr assertions).

**Tech Stack:** Python 3, spaCy 3.8, pytest.

## Global Constraints

- Warnings go to **stderr** via `print("[WARN] …", file=sys.stderr)` — stdout is reserved for the stage's JSON payload; the script has no logger.
- Safety nets **warn, never raise** — extraction must not fail on ontology drift.
- No new dependencies.
- Spec: `docs/superpowers/specs/2026-07-11-stu-439-ner-kept-labels-design.md`.
- Baseline before Task 1: `pytest -q` → **878 passed** (verified in this worktree).
- Verified spaCy facts this plan relies on (do not re-litigate): `entity_ruler` on `spacy.blank("en")` emits custom labels via `doc.ents`; `span.root` works without a parser; blank-`en` tokenizes `"— Regarde toi."` as `['—', 'Regarde', 'toi', '.']`; in `en_core_web_sm`, token 1 of `"He said hello to Marion yesterday."` has `pos_ == "VERB"`; `en_core_web_sm` NER labels include `CARDINAL, DATE, EVENT, FAC, GPE, LANGUAGE, LAW, LOC, MONEY, NORP, ORDINAL, ORG, PERCENT, PERSON, PRODUCT, QUANTITY, TIME, WORK_OF_ART`.

---

### Task 1: Keep and type PLACE / EVENT / FACTION

**Files:**
- Modify: `scripts/entity_extraction.py:119-132` (`KEPT_LABELS`, `LABEL_TO_TYPE`)
- Test: `tests/test_entity_extraction.py`

**Interfaces:**
- Consumes: `extract_entities(chapters, nlp)` (existing).
- Produces: `KEPT_LABELS` containing `PLACE`, `EVENT`, `FACTION`; `LABEL_TO_TYPE` mapping `PLACE→PLACE`, `EVENT→EVENT`, `FACTION→ORG`. Task 2 subtracts `KEPT_LABELS` in its audit.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_entity_extraction.py` (top-level, near the other `extract_entities` tests). The fixture builds a pipeline that mimics `models/wiki-ner-en/model-best`: custom fiction ontology, no tagger, no parser.

```python
@pytest.fixture()
def custom_ontology_nlp():
    """Mimics models/wiki-ner-en: custom fiction labels, no tagger/parser."""
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    ruler = nlp.add_pipe("entity_ruler")
    ruler.add_patterns([
        {"label": "PERSON", "pattern": "Celaena"},
        {"label": "PLACE", "pattern": "Endovier"},
        {"label": "EVENT", "pattern": "Yulemas"},
        {"label": "FACTION", "pattern": [{"TEXT": "Silent"}, {"TEXT": "Assassins"}]},
    ])
    return nlp


def test_custom_ontology_labels_survive_extraction(custom_ontology_nlp):
    """PLACE/EVENT/FACTION from the fine-tuned model must not be dropped (STU-439)."""
    chapters = [{
        "id": "ch01",
        "title": "Chapter 1",
        "content": "Celaena walked to Endovier. Everyone celebrated Yulemas. The Silent Assassins waited.",
    }]
    result = extract_entities(chapters, custom_ontology_nlp)
    types_by_mention = {
        m: entry["type"]
        for entry in result["entities"].values()
        for m in entry["raw_mentions"]
    }
    assert types_by_mention.get("Celaena") == "PERSON"
    assert types_by_mention.get("Endovier") == "PLACE"
    assert types_by_mention.get("Yulemas") == "EVENT"
    assert types_by_mention.get("Silent Assassins") == "ORG"  # FACTION → ORG (spec decision)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_entity_extraction.py::test_custom_ontology_labels_survive_extraction -v`
Expected: FAIL — `types_by_mention.get("Endovier")` is `None` (label dropped at the `KEPT_LABELS` filter). Verified pre-plan: current extraction keeps only `{'Celaena': 'PERSON'}` on this input.

- [ ] **Step 3: Update the constants**

In `scripts/entity_extraction.py`, replace lines 119-132:

```python
# Entity labels to keep. Covers French/English spaCy models and the
# fine-tuned fiction models (models/wiki-ner-*), which emit
# PERSON / PLACE / ORG / FACTION / EVENT (see ner_dataset_generation.py).
# French (fr_core_news_*): PER, LOC, ORG
# English (en_core_web_*): PERSON, GPE, LOC, ORG, FAC, NORP
KEPT_LABELS = {
    "PER", "LOC", "ORG", "PERSON", "GPE", "FAC", "NORP",
    "PLACE", "EVENT", "FACTION",
}

LABEL_TO_TYPE = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "LOC": "PLACE",
    "GPE": "PLACE",
    "FAC": "PLACE",
    "PLACE": "PLACE",
    "ORG": "ORG",
    "NORP": "ORG",
    # FACTION → ORG: downstream type vocabulary is frozen to
    # PERSON/PLACE/ORG/EVENT/OTHER (wiki_creator/types.py).
    "FACTION": "ORG",
    "EVENT": "EVENT",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_entity_extraction.py::test_custom_ontology_labels_survive_extraction -v`
Expected: PASS

- [ ] **Step 5: Run the full extraction test file**

Run: `pytest tests/test_entity_extraction.py -q`
Expected: all pass (stock models never emit PLACE/EVENT/FACTION, so no existing test changes behaviour).

- [ ] **Step 6: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "fix(extraction): keep PLACE/EVENT/FACTION from custom NER ontology (STU-439)"
```

---

### Task 2: Silent-drop safety net (`IGNORED_LABELS` + load-time audit)

**Files:**
- Modify: `scripts/entity_extraction.py` (constant after `LABEL_TO_TYPE`; function near `_load_spacy_model_with_fallback`; one call in `main()` after `_ensure_sentencizer(nlp)`)
- Test: `tests/test_entity_extraction.py`

**Interfaces:**
- Consumes: `KEPT_LABELS` (Task 1).
- Produces: `IGNORED_LABELS: set[str]` and `_audit_ner_labels(nlp) -> None`, imported by tests. Task 3 wires its own call next to this one in `main()`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_entity_extraction.py`. Extend the existing `from scripts.entity_extraction import (…)` block with `_audit_ner_labels`.

```python
def test_audit_warns_on_unknown_ner_label(capsys):
    """A model emitting labels outside KEPT_LABELS ∪ IGNORED_LABELS must warn (STU-439)."""
    nlp = spacy.blank("en")
    ner = nlp.add_pipe("ner")
    ner.add_label("ARTIFACT")
    _audit_ner_labels(nlp)
    err = capsys.readouterr().err
    assert "[WARN]" in err
    assert "ARTIFACT" in err


def test_audit_silent_for_kept_and_ignored_labels(capsys):
    """Custom ontology + deliberately-ignored stock labels: no warning."""
    nlp = spacy.blank("en")
    ner = nlp.add_pipe("ner")
    for label in ("PERSON", "PLACE", "ORG", "FACTION", "EVENT", "DATE", "CARDINAL", "MISC"):
        ner.add_label(label)
    _audit_ner_labels(nlp)
    assert capsys.readouterr().err == ""


def test_audit_without_ner_pipe_is_silent(capsys):
    nlp = spacy.blank("en")
    _audit_ner_labels(nlp)
    assert capsys.readouterr().err == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_entity_extraction.py -q -k audit`
Expected: FAIL at import — `ImportError: cannot import name '_audit_ner_labels'`.

- [ ] **Step 3: Implement constant + audit function + wiring**

In `scripts/entity_extraction.py`, directly after the `LABEL_TO_TYPE` dict:

```python
# Stock-model labels we deliberately do NOT extract. Kept explicit so the
# load-time audit (_audit_ner_labels) can tell "intentionally dropped"
# from "silently disconnected" (STU-439).
# en_core_web_*: numerics/dates/works.  fr_core_news_*: MISC.
IGNORED_LABELS = {
    "CARDINAL", "DATE", "TIME", "MONEY", "PERCENT", "QUANTITY", "ORDINAL",
    "LANGUAGE", "LAW", "PRODUCT", "WORK_OF_ART", "MISC",
}
```

Directly after `_load_spacy_model_with_fallback`:

```python
def _audit_ner_labels(nlp) -> None:
    """
    Warn (never raise) if the loaded model can emit NER labels that the
    extraction filter would silently drop — i.e. labels in neither
    KEPT_LABELS nor IGNORED_LABELS. Guards against a custom ontology
    being half-disconnected again (STU-439).
    """
    if "ner" not in nlp.pipe_names:
        return
    unknown = sorted(set(nlp.get_pipe("ner").labels) - KEPT_LABELS - IGNORED_LABELS)
    if unknown:
        print(
            "[WARN] NER model emits labels outside KEPT_LABELS/IGNORED_LABELS; "
            f"these entities will be dropped: {', '.join(unknown)}",
            file=sys.stderr,
        )
```

In `main()`, after the `_ensure_sentencizer(nlp)` line:

```python
    _ensure_sentencizer(nlp)
    _audit_ner_labels(nlp)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_entity_extraction.py -q -k audit`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat(extraction): warn when NER model labels would be silently dropped (STU-439)"
```

---

### Task 3: Explicit POS no-op when the model has no tagger

**Files:**
- Modify: `scripts/entity_extraction.py` (`_is_valid_span`, lines 310-337; new `_warn_if_no_pos_tagger` next to `_audit_ner_labels`; one call in `main()`)
- Test: `tests/test_entity_extraction.py`

**Interfaces:**
- Consumes: `_BAD_POS` (existing), `_audit_ner_labels` wiring point in `main()` (Task 2).
- Produces: `_warn_if_no_pos_tagger(nlp) -> None` and POS-aware `_is_valid_span(span) -> bool`, imported by tests.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_entity_extraction.py`. Extend the import block with `_is_valid_span, _warn_if_no_pos_tagger` and add `from spacy.tokens import Span` below the existing `import spacy`.

```python
@requires_en_sm
def test_is_valid_span_rejects_verb_when_pos_available(nlp):
    doc = nlp("He said hello to Marion yesterday.")
    span = Span(doc, 1, 2, label="PERSON")  # "said", pos_ == VERB
    assert _is_valid_span(span) is False


def test_is_valid_span_skips_pos_check_without_tagger():
    """Tagger-less model (e.g. wiki-ner-en): POS filter is an explicit no-op (STU-439)."""
    blank = spacy.blank("en")
    doc = blank("He said hello to Marion yesterday.")
    span = Span(doc, 1, 2, label="PERSON")  # same span, but pos_ is empty
    assert _is_valid_span(span) is True


def test_is_valid_span_dash_rejection_survives_missing_pos():
    """The dialogue-dash check does not depend on POS and must stay active."""
    blank = spacy.blank("en")
    doc = blank("— Regarde toi.")  # tokens: ['—', 'Regarde', 'toi', '.']
    span = Span(doc, 1, 2, label="PERSON")  # "Regarde", preceded by dash
    assert _is_valid_span(span) is False


def test_warns_when_model_has_no_tagger(capsys):
    blank = spacy.blank("en")
    _warn_if_no_pos_tagger(blank)
    err = capsys.readouterr().err
    assert "[WARN]" in err
    assert "POS filters disabled" in err


@requires_en_sm
def test_no_warning_when_tagger_present(nlp, capsys):
    _warn_if_no_pos_tagger(nlp)
    assert capsys.readouterr().err == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_entity_extraction.py -q -k "valid_span or tagger"`
Expected: FAIL at import — `ImportError: cannot import name '_warn_if_no_pos_tagger'`. (Note: `test_is_valid_span_skips_pos_check_without_tagger` would pass even pre-change — `pos_` is empty so never in `_BAD_POS`; it pins the no-op as *intended* behaviour rather than an accident.)

- [ ] **Step 3: Implement warning function + explicit guard**

In `scripts/entity_extraction.py`, after `_audit_ner_labels`:

```python
def _warn_if_no_pos_tagger(nlp) -> None:
    """
    The _BAD_POS filters in _is_valid_span need POS annotation. Fine-tuned
    ['tok2vec','ner'] models have no tagger, so those filters cannot apply.
    Make that explicit instead of silent (STU-439).
    """
    if not any(p in nlp.pipe_names for p in ("tagger", "morphologizer")):
        print(
            "[WARN] POS filters disabled: model has no tagger/morphologizer, "
            "_BAD_POS span filtering will not apply",
            file=sys.stderr,
        )
```

In `_is_valid_span`, make the no-op explicit. Replace the function body (keep the docstring, appending the note below):

```python
    tokens = list(span)
    # Tagger-less pipelines (e.g. fine-tuned ['tok2vec','ner'] models) carry no
    # POS annotation; the _BAD_POS checks are then deliberately skipped
    # (warned once at load time by _warn_if_no_pos_tagger). The dialogue-dash
    # rejection below does not depend on POS and always applies.
    has_pos = span.doc.has_annotation("POS")
    if len(tokens) == 1:
        tok = tokens[0]
        if has_pos and tok.pos_ in _BAD_POS:
            return False
        # Reject if immediately preceded by a dialogue dash (French dialogue marker)
        if tok.i > 0 and span.doc[tok.i - 1].text in {"—", "–", "-"}:
            return False
    else:
        head = span.root
        if has_pos and head.pos_ in _BAD_POS:
            return False
        # Reject multi-token spans that start immediately after a dialogue dash
        if span.start > 0 and span.doc[span.start - 1].text in {"—", "–", "-"}:
            return False
    return True
```

In `main()`, after the `_audit_ner_labels(nlp)` line added in Task 2:

```python
    _audit_ner_labels(nlp)
    _warn_if_no_pos_tagger(nlp)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_entity_extraction.py -q -k "valid_span or tagger"`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat(extraction): explicit POS-filter no-op + warning for tagger-less models (STU-439)"
```

---

### Task 4: Full-suite verification and real-model smoke check

**Files:**
- No new files; verification only.

**Interfaces:**
- Consumes: everything above.
- Produces: green suite; evidence the real custom model triggers the no-tagger warning and no label warning.

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: **≥ 887 passed** (878 baseline + 9 new), 0 failures.

- [ ] **Step 2: Smoke-check against the real fine-tuned model (if present)**

```bash
python - <<'EOF'
import sys, os
sys.path.insert(0, "scripts")
import spacy
from entity_extraction import _audit_ner_labels, _warn_if_no_pos_tagger, KEPT_LABELS
path = "models/wiki-ner-en/model-best"
if not os.path.isdir(path):
    print("model not present locally — skip", file=sys.stderr); sys.exit(0)
nlp = spacy.load(path)
print("labels:", sorted(nlp.get_pipe("ner").labels), file=sys.stderr)
_audit_ner_labels(nlp)          # expected: silent (all 5 labels now kept)
_warn_if_no_pos_tagger(nlp)     # expected: [WARN] POS filters disabled…
EOF
```

Expected stderr: the 5 labels, **no** `KEPT_LABELS` warning, **one** `POS filters disabled` warning.

- [ ] **Step 3: Run mypy on the touched module (project command)**

Run: `mypy wiki_creator/`
Expected: unchanged from baseline (the script lives in `scripts/`, but run the project check to be safe).

- [ ] **Step 4: Commit any stragglers and stop**

```bash
git status --short   # should be clean; commit only if something was missed
```

Do not merge or push — integration is a separate decision (superpowers:finishing-a-development-branch).
