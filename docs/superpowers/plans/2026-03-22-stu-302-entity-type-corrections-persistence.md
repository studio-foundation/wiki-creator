# STU-302 — Entity Type Corrections Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist LLM type corrections from `verify_entity_types.py` to disk so they survive `--restart wiki-resolution` without re-running the full `wiki-extraction` stage.

**Architecture:** `verify_entity_types.py` writes `entity_type_corrections.json` into `processing_output/<slug>/` after each enabled run. `entity_classification.py` reads this file (if present) and applies corrections after its deterministic heuristics but before user-defined overrides — ensuring LLM corrections are respected while manual `entity_overrides` stay highest priority.

**Tech Stack:** Python 3.12+, `pathlib.Path`, `json`, `pytest`

---

## File Map

| File | Change |
|------|--------|
| `scripts/verify_entity_types.py` | Add file write in `main()` within the `enabled=True` branch |
| `scripts/entity_classification.py` | Add `_load_type_corrections()` and `_apply_llm_type_corrections()`, call them in `run_studio_mode()` |
| `tests/test_verify_entity_types.py` | Add 4 tests for the write behavior |
| `tests/test_entity_classification.py` | Add 7 tests for load, apply, and integration |

---

## Task 1: Persist corrections in `verify_entity_types.py`

**Files:**
- Modify: `scripts/verify_entity_types.py` (in `main()`, after `apply_corrections`, before `json.dump`)
- Test: `tests/test_verify_entity_types.py`

### Background

`main()` currently ends like this (around line 228–248):

```python
paths = _paths_from_payload(payload)
type_files = None
if paths is not None:
    type_files = {...}

model = input_data.get("ollama_model", DEFAULT_MODEL)
corrections = verify_clusters(clusters, model=model, type_files=type_files)
corrected_clusters = apply_corrections(clusters, corrections)

json.dump(
    {"clusters": corrected_clusters, "stats": stats, "type_corrections": corrections},
    sys.stdout,
    ensure_ascii=False,
)
```

The write must be inserted **after** `apply_corrections` and **before** `json.dump`. Only within the `enabled=True` branch (the early-return path for `enabled=False` is unchanged). Write only if `paths is not None`.

---

- [ ] **Step 1.1: Write the 4 failing tests**

Add at the **module level** of `tests/test_verify_entity_types.py` (alongside the existing `import json`):

```python
import io
import yaml
```

Then add the following helpers and tests:

```python
# --- main() file persistence ---

import io
import yaml

def _make_payload(tmp_path, verify_enabled: bool, clusters: list) -> dict:
    """Build a Studio-style payload with file_path pointing into tmp_path."""
    # book_paths_from_epub expects: <anything>/books/<slug>.epub
    # It derives: series_dir = tmp_path, slug = "testbook"
    # → paths.processing = tmp_path / "processing_output" / "testbook"
    book_file = tmp_path / "books" / "testbook.epub"
    book_file.parent.mkdir(parents=True, exist_ok=True)
    book_file.touch()
    ctx = yaml.dump({"file_path": str(book_file), "verify_entity_types": verify_enabled})
    return {
        "additional_context": ctx,
        "previous_outputs": {
            "entity-clustering": {
                "clusters": clusters,
                "stats": {"input_entities": len(clusters), "total_items": len(clusters)},
            }
        },
    }


def _run_main(monkeypatch, payload: dict) -> dict:
    """Pipe payload through main() and return parsed stdout."""
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    # Patch _call_ollama to avoid real network calls
    import scripts.verify_entity_types as _vt
    monkeypatch.setattr(_vt, "_call_ollama", lambda name, ctx, model: "PERSON")
    from scripts.verify_entity_types import main
    main()
    return json.loads(captured.getvalue())


def test_main_writes_corrections_file(monkeypatch, tmp_path):
    """enabled=True + clusters → entity_type_corrections.json written."""
    clusters = [
        {
            "cluster_id": "cluster_042",
            "type": "PLACE",
            "canonical_candidate": "Arobynn",
            "all_mentions": ["Arobynn"],
            "entity_ids": ["entity_042"],
            "entity_count": 1,
            "total_mentions": 10,
        }
    ]
    # Provide places_full.json so load_context_for_cluster returns something
    processing_dir = tmp_path / "processing_output" / "testbook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "places_full.json").write_text(
        json.dumps({
            "places_full": {
                "entity_042": {
                    "type": "PLACE",
                    "raw_mentions": ["Arobynn"],
                    "mentions_by_chapter": {"ch01": ["Arobynn sourit depuis le trône."]},
                }
            }
        })
    )

    payload = _make_payload(tmp_path, verify_enabled=True, clusters=clusters)
    _run_main(monkeypatch, payload)

    corrections_file = processing_dir / "entity_type_corrections.json"
    assert corrections_file.exists(), "entity_type_corrections.json must be written"
    data = json.loads(corrections_file.read_text())
    assert len(data) == 1
    assert data[0]["name"] == "Arobynn"
    assert data[0]["to"] == "PERSON"
    assert data[0]["from"] == "PLACE"


def test_main_writes_empty_file_when_no_corrections(monkeypatch, tmp_path):
    """enabled=True but _call_ollama returns None for all → file written as []."""
    import scripts.verify_entity_types as _vt
    monkeypatch.setattr(_vt, "_call_ollama", lambda name, ctx, model: None)

    processing_dir = tmp_path / "processing_output" / "testbook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "places_full.json").write_text(
        json.dumps({
            "places_full": {
                "entity_042": {
                    "type": "PLACE",
                    "raw_mentions": ["SomePlace"],
                    "mentions_by_chapter": {"ch01": ["SomePlace was cold."]},
                }
            }
        })
    )
    clusters = [
        {
            "cluster_id": "cluster_042",
            "type": "PLACE",
            "canonical_candidate": "SomePlace",
            "all_mentions": ["SomePlace"],
            "entity_ids": ["entity_042"],
            "entity_count": 1,
            "total_mentions": 3,
        }
    ]
    payload = _make_payload(tmp_path, verify_enabled=True, clusters=clusters)

    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    from scripts.verify_entity_types import main
    main()

    corrections_file = processing_dir / "entity_type_corrections.json"
    assert corrections_file.exists()
    assert json.loads(corrections_file.read_text()) == []


def test_main_no_file_when_disabled(monkeypatch, tmp_path):
    """`verify_entity_types: false` → early return, no file written."""
    processing_dir = tmp_path / "processing_output" / "testbook"
    # Do NOT pre-create the directory — should not be created by the disabled path

    payload = _make_payload(tmp_path, verify_enabled=False, clusters=[])
    _run_main(monkeypatch, payload)

    assert not (processing_dir / "entity_type_corrections.json").exists()


def test_main_no_file_when_no_paths(monkeypatch, tmp_path):
    """Payload without file_path → no file written (test mode)."""
    payload = {
        "additional_context": "verify_entity_types: true",
        "previous_outputs": {
            "entity-clustering": {"clusters": [], "stats": {}}
        },
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    import scripts.verify_entity_types as _vt
    monkeypatch.setattr(_vt, "_call_ollama", lambda name, ctx, model: "PERSON")
    from scripts.verify_entity_types import main
    main()

    # No file should have been written anywhere near tmp_path
    # (nothing to check beyond no exception raised)
```

- [ ] **Step 1.2: Run tests to verify they all fail**

```bash
pytest tests/test_verify_entity_types.py::test_main_writes_corrections_file \
       tests/test_verify_entity_types.py::test_main_writes_empty_file_when_no_corrections \
       tests/test_verify_entity_types.py::test_main_no_file_when_disabled \
       tests/test_verify_entity_types.py::test_main_no_file_when_no_paths \
       -v
```

Expected: `test_main_writes_corrections_file` and `test_main_writes_empty_file_when_no_corrections` FAIL (file not written). Others may pass or fail depending on current behavior.

- [ ] **Step 1.3: Add the file write in `main()` of `verify_entity_types.py`**

Locate the section in `main()` that starts with `paths = _paths_from_payload(payload)` (around line 228). Add the write **after** `corrected_clusters = apply_corrections(clusters, corrections)` and **before** the final `json.dump`:

```python
    # Persist corrections for wiki-resolution restarts (STU-302)
    if paths is not None:
        paths.processing.mkdir(parents=True, exist_ok=True)
        corrections_path = paths.processing / "entity_type_corrections.json"
        with open(corrections_path, "w", encoding="utf-8") as _f:
            json.dump(corrections, _f, ensure_ascii=False)
```

- [ ] **Step 1.4: Run tests to verify they all pass**

```bash
pytest tests/test_verify_entity_types.py -v
```

Expected: all 13 tests PASS (9 pre-existing + 4 new).

- [ ] **Step 1.5: Commit**

```bash
git add scripts/verify_entity_types.py tests/test_verify_entity_types.py
git commit -m "feat(stu-302): persist entity_type_corrections.json in verify_entity_types"
```

---

## Task 2: Load and apply corrections in `entity_classification.py`

**Files:**
- Modify: `scripts/entity_classification.py`
  - Add `_load_type_corrections()` near `_load_entity_files()` (around line 566)
  - Add `_apply_llm_type_corrections()` near `_apply_entity_overrides()` (around line 523)
  - Call both in `run_studio_mode()` after `_normalize_entity_type` loop (after line 649)
- Test: `tests/test_entity_classification.py`

### Background

In `run_studio_mode()`, the current pipeline between lines 641–668:

```python
# Deterministic type normalization before scoring.
for entity in entities:
    entity["type"] = _normalize_entity_type(...)

# Role/title entities...
entities, relationships, _ = _canonicalize_role_entities(...)

# Optional per-book explicit overrides (highest priority).
entities, relationships, _ = _apply_entity_overrides(...)
```

The new call goes **between** `_normalize_entity_type` and `_canonicalize_role_entities`.

---

- [ ] **Step 2.1: Write the 7 failing tests**

Add to `tests/test_entity_classification.py` (after existing imports, before or after existing test sections):

```python
import json
import io
from pathlib import Path

# Add these imports at the top of the file alongside existing ones:
# from scripts.entity_classification import _load_type_corrections, _apply_llm_type_corrections


# --- _load_type_corrections ---

def test_load_type_corrections_returns_empty_when_no_file(tmp_path):
    from scripts.entity_classification import _load_type_corrections
    result = _load_type_corrections(tmp_path)
    assert result == {}


def test_load_type_corrections_reads_file(tmp_path):
    from scripts.entity_classification import _load_type_corrections
    data = [
        {"cluster_id": "c1", "name": "Arobynn", "from": "PLACE", "to": "PERSON"},
        {"cluster_id": "c2", "name": "Sam Hamel", "from": "ORG", "to": "PERSON"},
    ]
    (tmp_path / "entity_type_corrections.json").write_text(json.dumps(data))
    result = _load_type_corrections(tmp_path)
    assert result == {"arobynn": "PERSON", "sam hamel": "PERSON"}


# --- _apply_llm_type_corrections ---

def test_apply_llm_corrections_by_canonical_name():
    from scripts.entity_classification import _apply_llm_type_corrections
    entities = [{"canonical_name": "Arobynn", "type": "PLACE", "aliases": []}]
    corrections_map = {"arobynn": "PERSON"}
    _apply_llm_type_corrections(entities, corrections_map)
    assert entities[0]["type"] == "PERSON"


def test_apply_llm_corrections_by_alias():
    from scripts.entity_classification import _apply_llm_type_corrections
    # canonical_name does NOT match, but alias does
    entities = [{"canonical_name": "Arobynn Hamel", "type": "PLACE", "aliases": ["Arobynn"]}]
    corrections_map = {"arobynn": "PERSON"}
    _apply_llm_type_corrections(entities, corrections_map)
    assert entities[0]["type"] == "PERSON"


def test_apply_llm_corrections_no_match():
    from scripts.entity_classification import _apply_llm_type_corrections
    entities = [{"canonical_name": "Dorian", "type": "PERSON", "aliases": []}]
    corrections_map = {"arobynn": "PERSON"}
    _apply_llm_type_corrections(entities, corrections_map)
    assert entities[0]["type"] == "PERSON"  # unchanged


def test_corrections_lower_priority_than_entity_overrides(monkeypatch, tmp_path):
    """LLM correction says PERSON; manual override force_type=PLACE wins."""
    import yaml
    from scripts.entity_classification import run_studio_mode

    processing_dir = tmp_path / "processing_output" / "testbook"
    processing_dir.mkdir(parents=True)
    (processing_dir / "entity_type_corrections.json").write_text(
        json.dumps([{"name": "Arobynn", "from": "PLACE", "to": "PERSON"}])
    )
    for fname, key in [("persons_full.json", "persons_full"),
                       ("places_full.json", "places_full"),
                       ("orgs_full.json", "orgs_full"),
                       ("events_full.json", "events_full")]:
        (processing_dir / fname).write_text(json.dumps({key: {}}))

    book_file = tmp_path / "books" / "testbook.epub"
    book_file.parent.mkdir(parents=True)
    book_file.touch()

    book_yaml = yaml.dump({
        "file_path": str(book_file),
        "thresholds": "auto",
        "entity_overrides": {"Arobynn": {"force_type": "PLACE"}},
    })
    entities = [
        {"canonical_name": "Arobynn", "type": "PLACE", "aliases": [], "source_ids": [], "relevant": True}
    ]
    payload = {
        "additional_context": book_yaml,
        "previous_outputs": {
            "alias-resolution": {"entities": entities, "narrator": None},
            "relationship-extraction": {
                "entities": entities, "relationships": [], "stats": {}, "narrator": None,
            },
        },
        "all_stage_outputs": {},
    }
    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    run_studio_mode()

    result = json.loads(captured.getvalue())
    arobynn = next(e for e in result["entities"] if e["canonical_name"] == "Arobynn")
    assert arobynn["type"] == "PLACE", f"Expected PLACE (manual override wins), got {arobynn['type']}"


def test_run_studio_mode_applies_corrections_file(monkeypatch, tmp_path):
    """Integration: entity_type_corrections.json present → type corrected in output."""
    import sys
    import yaml
    import io
    from scripts.entity_classification import run_studio_mode

    # Setup paths: book_paths_from_epub("tmp_path/books/testbook.epub")
    # → paths.processing = tmp_path / "processing_output" / "testbook"
    processing_dir = tmp_path / "processing_output" / "testbook"
    processing_dir.mkdir(parents=True)

    # Write corrections file: Arobynn PLACE → PERSON
    (processing_dir / "entity_type_corrections.json").write_text(
        json.dumps([{"cluster_id": "c1", "name": "Arobynn", "from": "PLACE", "to": "PERSON"}])
    )
    # Empty entity files
    for fname, key in [("persons_full.json", "persons_full"),
                       ("places_full.json", "places_full"),
                       ("orgs_full.json", "orgs_full"),
                       ("events_full.json", "events_full")]:
        (processing_dir / fname).write_text(json.dumps({key: {}}))

    book_file = tmp_path / "books" / "testbook.epub"
    book_file.parent.mkdir(parents=True)
    book_file.touch()

    book_yaml = yaml.dump({"file_path": str(book_file), "thresholds": "auto"})
    entities = [
        {"canonical_name": "Arobynn", "type": "PLACE", "aliases": [], "source_ids": [], "relevant": True}
    ]
    payload = {
        "additional_context": book_yaml,
        "previous_outputs": {
            "alias-resolution": {"entities": entities, "narrator": None},
            "relationship-extraction": {
                "entities": entities,
                "relationships": [],
                "stats": {},
                "narrator": None,
            },
        },
        "all_stage_outputs": {},
    }

    monkeypatch.setattr(
        "sys.stdin",
        io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"),
    )
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)

    run_studio_mode()

    result = json.loads(captured.getvalue())
    arobynn = next(e for e in result["entities"] if e["canonical_name"] == "Arobynn")
    assert arobynn["type"] == "PERSON", f"Expected PERSON, got {arobynn['type']}"
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
pytest tests/test_entity_classification.py::test_load_type_corrections_returns_empty_when_no_file \
       tests/test_entity_classification.py::test_load_type_corrections_reads_file \
       tests/test_entity_classification.py::test_apply_llm_corrections_by_canonical_name \
       tests/test_entity_classification.py::test_apply_llm_corrections_by_alias \
       tests/test_entity_classification.py::test_apply_llm_corrections_no_match \
       tests/test_entity_classification.py::test_corrections_lower_priority_than_entity_overrides \
       tests/test_entity_classification.py::test_run_studio_mode_applies_corrections_file \
       -v
```

Expected: ImportError or NameError on `_load_type_corrections` / `_apply_llm_type_corrections` for most tests. Integration tests may also fail on logic.

- [ ] **Step 2.3: Add `_load_type_corrections` to `entity_classification.py`**

Add near the existing `_load_entity_files` function (around line 566):

```python
def _load_type_corrections(processing_dir: Path) -> dict[str, str]:
    """Load persisted LLM type corrections from entity_type_corrections.json.

    Returns a dict of { lowercase_name: target_type } for matching against
    entity canonical_name and aliases. Returns {} if file is absent.
    """
    p = processing_dir / "entity_type_corrections.json"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        corrections = json.load(f)
    return {c["name"].lower(): c["to"] for c in corrections if "name" in c and "to" in c}
```

- [ ] **Step 2.4: Add `_apply_llm_type_corrections` to `entity_classification.py`**

Add near the existing `_apply_entity_overrides` function (around line 523):

```python
def _apply_llm_type_corrections(
    entities: list[dict],
    corrections_map: dict[str, str],
) -> None:
    """Apply persisted LLM type corrections to entities (in-place).

    Matches by canonical_name first, then aliases (all lowercase).
    Corrections have lower priority than _apply_entity_overrides —
    call this BEFORE entity_overrides in run_studio_mode().
    """
    for entity in entities:
        name = (entity.get("canonical_name") or "").lower()
        match = corrections_map.get(name)
        if match is None:
            for alias in entity.get("aliases", []):
                match = corrections_map.get((alias or "").lower())
                if match is not None:
                    break
        if match is not None and entity.get("type") != match:
            print(
                f"[CORRECTIONS] {entity['canonical_name']}: {entity['type']} → {match}"
                " (from entity_type_corrections.json)",
                file=sys.stderr,
            )
            entity["type"] = match
```

- [ ] **Step 2.5: Call both functions in `run_studio_mode()`**

In `run_studio_mode()`, after the `_normalize_entity_type` loop (after line 649) and before `_canonicalize_role_entities`:

```python
    # Apply persisted LLM type corrections (STU-302).
    # Priority: after heuristic normalization, before role canonicalization and manual overrides.
    llm_corrections = _load_type_corrections(paths.processing)
    if llm_corrections:
        _apply_llm_type_corrections(entities, llm_corrections)
```

- [ ] **Step 2.6: Run the new tests**

```bash
pytest tests/test_entity_classification.py::test_load_type_corrections_returns_empty_when_no_file \
       tests/test_entity_classification.py::test_load_type_corrections_reads_file \
       tests/test_entity_classification.py::test_apply_llm_corrections_by_canonical_name \
       tests/test_entity_classification.py::test_apply_llm_corrections_by_alias \
       tests/test_entity_classification.py::test_apply_llm_corrections_no_match \
       tests/test_entity_classification.py::test_corrections_lower_priority_than_entity_overrides \
       tests/test_entity_classification.py::test_run_studio_mode_applies_corrections_file \
       -v
```

Expected: all 7 PASS.

- [ ] **Step 2.7: Run full test suite**

```bash
pytest -q
```

Expected: all tests pass (485+ previously passing tests still pass).

- [ ] **Step 2.8: Commit**

```bash
git add scripts/entity_classification.py tests/test_entity_classification.py
git commit -m "feat(stu-302): load and apply entity_type_corrections in entity_classification"
```

---

## Final verification

- [ ] **Step 3.1: Confirm all tests green**

```bash
pytest -q
```

Expected output: `X passed` with no failures.
