# SP0 · Event Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic `events.json` layer by structuring the existing chapter summaries and relationship key-moments into per-chapter events with canonical participants, places, and a salience score — the foundation for the four Plot Spine projections (SP1–SP4).

**Architecture:** A pure module `wiki_creator/event_layer.py` (`build_events()`) does all the structuring and is unit-tested in isolation. A thin script-executor stage `scripts/build_event_layer.py` wires it to the pipeline: it reads `chapter_summaries.json` + `relationships_classified.json` + `registry.json`, calls `build_events()`, and writes `events.json`. Mirrors the existing `relationship_fold.py` (pure module) + `classify_relationships.py` (stage) pair verbatim.

**Tech Stack:** Python 3.14, pytest, spaCy-free (pure stdlib + `wiki_creator` helpers). No new dependencies.

## Global Constraints

- **No hardcoded word lists in scripts** (CLAUDE.md invariant). `action_cues` MUST come from `wiki_creator.lang.load_lang_config(<lang>)["action_cues"]`; if the key is absent, degrade to an empty list. Never define a fallback vocabulary constant.
- **Canonical identity via the registry only.** Resolve any surface name to its canonical form through `Registry.lookup(surface)`; never re-implement name matching.
- **Script-executor conventions.** Stages read the payload from stdin / `--book` CLI, read/write JSON artifacts under `book_paths.processing`, and are tolerant of missing files in unit-test mode.
- **Tolerant of missing `file_path`/registry in unit-test mode** (like `relationship_extraction.py`, `split_clusters.py`).
- Verify with `pytest -q` and `mypy wiki_creator/` before claiming done.
- Spoiler scope is inherited from the summaries (already book-1 bounded) — do not add cross-book data.

## File Structure

- **Create** `wiki_creator/event_layer.py` — pure module: beat extraction, canonical resolution, dedup/aggregation, salience. One responsibility: turn (summaries, relationships, registry) into a list of event dicts.
- **Create** `tests/test_event_layer.py` — unit tests for the pure module.
- **Create** `scripts/build_event_layer.py` — script-executor stage: read artifacts → `build_events()` → write `events.json`. Mirrors `scripts/classify_relationships.py`.
- **Create** `tests/test_build_event_layer.py` — stage-level test (tmp_path fixture, no LLM).
- **Modify** `run_wiki.py` — register `build_event_layer.py` as a PRE_STEP running after `classify_relationships.py`, before the `wiki-preparation` Studio pipeline.
- **Modify** `scripts/wiki_preparation.py` — `build_entity_bundle()` gains an `entity_events` field sourced from `events.json` (supersedes the empty `chapter_summary_context` channel).
- **Modify** `Makefile` — add `run-events` convenience target.

Event dict shape (the contract every later task and SP1–SP4 consume):
```python
{
    "event_id": str,          # e.g. "e_ch12_0"
    "chapter": int,           # 12
    "description": str,       # verbatim beat text
    "participants": list[str],# canonical PERSON names, sorted, deduped
    "places": list[str],      # canonical PLACE names, sorted, deduped
    "outcome": str | None,    # description if it contains an action_cue, else None
    "salience": float,        # 0.0–1.0
    "source_bullets": list[str],  # the raw beat string(s) this event came from
}
```

---

### Task 1: `_parse_chapter` — extract a chapter number from a beat/summary key

**Files:**
- Create: `wiki_creator/event_layer.py`
- Test: `tests/test_event_layer.py`

**Interfaces:**
- Produces: `_parse_chapter(text: str) -> int | None` — parses the leading chapter marker of a key-moment string (`"Ch04: ..."`, `"ch36: ..."`, `"C12: ..."`) or a summary key (`"Chapter 1"`); returns the int or `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_layer.py
from wiki_creator.event_layer import _parse_chapter


def test_parse_chapter_variants():
    assert _parse_chapter("Ch04: eye contact and mutual smiles") == 4
    assert _parse_chapter("ch36: harmed by Cain") == 36
    assert _parse_chapter("C12: final duel") == 12
    assert _parse_chapter("Chapter 1") == 1
    assert _parse_chapter("no chapter here") is None
    assert _parse_chapter("") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_layer.py::test_parse_chapter_variants -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki_creator.event_layer'`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki_creator/event_layer.py
"""Event Layer (SP0): structure existing chapter summaries + relationship
key-moments into per-chapter events. Deterministic, zero LLM. Mirrors the
relationship_fold.py pure-module pattern.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wiki_creator.registry import Registry

_CHAPTER_RE = re.compile(r"^\s*(?:chapter\s+|c\.?h?\.?\s*)0*(\d+)", re.IGNORECASE)


def _parse_chapter(text: str) -> int | None:
    """Extract the leading chapter number from a beat string or summary key."""
    if not text:
        return None
    m = _CHAPTER_RE.match(text)
    return int(m.group(1)) if m else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_layer.py::test_parse_chapter_variants -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/event_layer.py tests/test_event_layer.py
git commit -m "feat(events): _parse_chapter for beat/summary chapter markers (STU-478)"
```

---

### Task 2: `_resolve` and `_names_in` — canonical entity resolution via the registry

**Files:**
- Modify: `wiki_creator/event_layer.py`
- Test: `tests/test_event_layer.py`

**Interfaces:**
- Consumes: `Registry.lookup(surface) -> EntityRecord | None` (has `.canonical_name`, `.entity_type`), `Registry.alias_table() -> dict[str, str]`.
- Produces:
  - `_resolve(name: str, registry: "Registry | None") -> str` — canonical name for a surface, or the input unchanged when no registry / no match.
  - `_names_in(text: str, registry: "Registry | None", entity_type: str) -> list[str]` — canonical names of the given `entity_type` ("PERSON"/"PLACE") whose surface appears as a whole word in `text`. Empty list when no registry.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_layer.py (append)
from wiki_creator.registry import EntityRecord, Registry
from wiki_creator.event_layer import _resolve, _names_in


def _registry(*records: EntityRecord) -> Registry:
    return Registry(entities=list(records))


CELAENA = EntityRecord(entity_id="celaena", canonical_name="Celaena Sardothien",
                       entity_type="PERSON", aliases=["Celaena Sardothien", "Celaena"])
CAIN = EntityRecord(entity_id="cain", canonical_name="Cain",
                    entity_type="PERSON", aliases=["Cain"])
RIFTHOLD = EntityRecord(entity_id="rifthold", canonical_name="Rifthold",
                        entity_type="PLACE", aliases=["Rifthold"])


def test_resolve_uses_registry_canonical():
    reg = _registry(CELAENA, CAIN, RIFTHOLD)
    assert _resolve("Celaena", reg) == "Celaena Sardothien"
    assert _resolve("Unknown", reg) == "Unknown"
    assert _resolve("Celaena", None) == "Celaena"


def test_names_in_matches_whole_words_by_type():
    reg = _registry(CELAENA, CAIN, RIFTHOLD)
    text = "Celaena defeats Cain in the arena at Rifthold"
    assert _names_in(text, reg, "PERSON") == ["Cain", "Celaena Sardothien"]
    assert _names_in(text, reg, "PLACE") == ["Rifthold"]
    assert _names_in("nothing here", reg, "PERSON") == []
    assert _names_in(text, None, "PERSON") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_layer.py -k "resolve or names_in" -v`
Expected: FAIL with `ImportError: cannot import name '_resolve'`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki_creator/event_layer.py (append)


def _resolve(name: str, registry: "Registry | None") -> str:
    if registry is None:
        return name
    record = registry.lookup(name)
    return record.canonical_name if record is not None else name


def _names_in(text: str, registry: "Registry | None", entity_type: str) -> list[str]:
    """Canonical names of `entity_type` whose surface appears as a whole word."""
    if registry is None or not text:
        return []
    low = text.casefold()
    found: set[str] = set()
    for record in registry.entities:
        if record.entity_type != entity_type:
            continue
        for alias in record.aliases:
            if re.search(rf"\b{re.escape(alias.casefold())}\b", low):
                found.add(record.canonical_name)
                break
    return sorted(found)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_layer.py -k "resolve or names_in" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/event_layer.py tests/test_event_layer.py
git commit -m "feat(events): canonical entity resolution helpers (STU-478)"
```

---

### Task 3: `_salience` — score a beat by action-cue + chapter position

**Files:**
- Modify: `wiki_creator/event_layer.py`
- Test: `tests/test_event_layer.py`

**Interfaces:**
- Produces: `_salience(description: str, chapter: int, total_chapters: int, action_cues: list[str]) -> float` — in `[0.0, 1.0]`. `0.5` for an action-cue hit, plus up to `0.5` scaled by how late in the book the chapter falls (climax bias). No cues + chapter 1 of many → near 0; a cue in the last chapter → ~1.0.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_layer.py (append)
from wiki_creator.event_layer import _salience


def test_salience_action_cue_and_position():
    cues = ["couronna", "vainquit", "tua"]
    # action cue + last chapter → high
    assert _salience("Celaena vainquit Cain", 12, 12, cues) == 1.0
    # action cue, early chapter → 0.5 + small position term
    assert _salience("Celaena vainquit Cain", 1, 12, cues) < 0.6
    # no cue, mid book → only the position term
    assert _salience("Celaena walks the corridor", 6, 12, cues) < 0.3
    # no cue, no chapters info → 0.0
    assert _salience("something", 0, 0, cues) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_layer.py::test_salience_action_cue_and_position -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki_creator/event_layer.py (append)


def _has_action_cue(description: str, action_cues: list[str]) -> bool:
    low = description.casefold()
    return any(re.search(rf"\b{re.escape(c.casefold())}\b", low) for c in action_cues)


def _salience(description: str, chapter: int, total_chapters: int,
              action_cues: list[str]) -> float:
    score = 0.5 if _has_action_cue(description, action_cues) else 0.0
    if total_chapters > 0 and chapter > 0:
        score += 0.5 * (chapter / total_chapters)
    return round(min(score, 1.0), 3)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_layer.py::test_salience_action_cue_and_position -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/event_layer.py tests/test_event_layer.py
git commit -m "feat(events): salience scoring (action_cues + climax bias) (STU-478)"
```

---

### Task 4: `build_events` — assemble, resolve, dedup, score

**Files:**
- Modify: `wiki_creator/event_layer.py`
- Test: `tests/test_event_layer.py`

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `build_events(chapter_summaries: dict, relationships: list[dict], registry: "Registry | None", action_cues: list[str]) -> list[dict]` — returns events in the shape from **File Structure**, sorted by `(chapter, event_id)`. Two beats in the same chapter with identical normalized descriptions collapse into one event (participants/places/source_bullets unioned).

Beat sources:
1. Each `key_moment` string in each relationship → a beat; participants seed = `[entity_a, entity_b]` (resolved canonical) plus any registry PERSON matched in the text; places = registry PLACE matched in the text.
2. Each `summary_bullet` in each chapter summary → a beat; participants = registry PERSON matched in the bullet; places = registry PLACE matched.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_layer.py (append)
from wiki_creator.event_layer import build_events


def test_build_events_from_summaries_and_key_moments():
    reg = _registry(CELAENA, CAIN, RIFTHOLD)
    summaries = {
        "Chapter 12": {
            "chapter_id": "C12.xhtml",
            "chapter_title": "Chapter 12",
            "summary_bullets": ["Celaena vainquit Cain at Rifthold"],
        },
    }
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Cain",
         "key_moments": ["Ch12: Celaena vainquit Cain at Rifthold"]},
    ]
    events = build_events(summaries, relationships, reg, action_cues=["vainquit"])

    # same chapter + identical description → one merged event
    assert len(events) == 1
    e = events[0]
    assert e["chapter"] == 12
    assert e["participants"] == ["Cain", "Celaena Sardothien"]
    assert e["places"] == ["Rifthold"]
    assert e["outcome"] == "Celaena vainquit Cain at Rifthold"  # has action cue
    assert e["salience"] == 1.0
    assert len(e["source_bullets"]) == 2  # both sources merged
    assert e["event_id"] == "e_ch12_0"


def test_build_events_skips_beats_without_chapter():
    reg = _registry(CELAENA)
    relationships = [{"entity_a": "Celaena", "entity_b": "Cain",
                      "key_moments": ["no chapter marker here"]}]
    assert build_events({}, relationships, reg, action_cues=[]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_event_layer.py -k build_events -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# wiki_creator/event_layer.py (append)


def _strip_marker(text: str) -> str:
    """Remove a leading 'Ch12:' / 'Chapter 12:' marker, return the description."""
    return _CHAPTER_RE.sub("", text).lstrip(" :—-").strip()


def build_events(
    chapter_summaries: dict,
    relationships: list[dict],
    registry: "Registry | None",
    action_cues: list[str],
) -> list[dict]:
    total_chapters = len(chapter_summaries) if chapter_summaries else 0

    # (chapter, normalized_description) -> aggregate
    agg: dict[tuple[int, str], dict] = {}

    def add_beat(chapter: int, raw: str, description: str, seed: list[str]) -> None:
        key = (chapter, description.casefold())
        entry = agg.get(key)
        if entry is None:
            entry = {
                "chapter": chapter,
                "description": description,
                "participants": set(),
                "places": set(),
                "source_bullets": [],
            }
            agg[key] = entry
        entry["source_bullets"].append(raw)
        for name in seed:
            entry["participants"].add(_resolve(name, registry))
        for name in _names_in(description, registry, "PERSON"):
            entry["participants"].add(name)
        for name in _names_in(description, registry, "PLACE"):
            entry["places"].add(name)

    # Source 1: relationship key_moments
    for rel in relationships:
        seed = [str(rel.get("entity_a", "")), str(rel.get("entity_b", ""))]
        seed = [s for s in seed if s]
        for km in rel.get("key_moments") or []:
            chapter = _parse_chapter(km)
            if chapter is None:
                continue
            add_beat(chapter, km, _strip_marker(km), seed)

    # Source 2: chapter summary bullets
    for key, summary in (chapter_summaries or {}).items():
        chapter = _parse_chapter(str(summary.get("chapter_title") or key)) \
            or _parse_chapter(str(summary.get("chapter_id") or ""))
        if chapter is None:
            continue
        for bullet in summary.get("summary_bullets") or []:
            add_beat(chapter, bullet, bullet.strip(), [])

    # Materialize, score, id, sort
    events: list[dict] = []
    for (chapter, _norm), entry in agg.items():
        description = entry["description"]
        events.append({
            "chapter": chapter,
            "description": description,
            "participants": sorted(entry["participants"]),
            "places": sorted(entry["places"]),
            "outcome": description if _has_action_cue(description, action_cues) else None,
            "salience": _salience(description, chapter, total_chapters, action_cues),
            "source_bullets": entry["source_bullets"],
        })

    events.sort(key=lambda e: (e["chapter"], e["description"].casefold()))
    by_chapter: dict[int, int] = {}
    for e in events:
        idx = by_chapter.get(e["chapter"], 0)
        e["event_id"] = f"e_ch{e['chapter']}_{idx}"
        by_chapter[e["chapter"]] = idx + 1
    return events
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_event_layer.py -v`
Expected: PASS (all event_layer tests)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/event_layer.py tests/test_event_layer.py
git commit -m "feat(events): build_events assembles/dedups/scores the event layer (STU-478)"
```

---

### Task 5: `scripts/build_event_layer.py` — the script-executor stage

**Files:**
- Create: `scripts/build_event_layer.py`
- Test: `tests/test_build_event_layer.py`

**Interfaces:**
- Consumes: `build_events(...)` (Task 4), `wiki_creator.paths.book_paths_from_yaml`, `wiki_creator.registry.Registry.load`, `wiki_creator.lang.load_lang_config` + `book_language`, `wiki_creator.studio_io`.
- Produces: `events.json` at `book_paths.processing / "events.json"` with shape `{"events": [...]}`; a `main()` that supports `--book <yaml>` (live/CLI) and the stdin payload path, mirroring `scripts/classify_relationships.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_build_event_layer.py
import json
import sys
import importlib.util
from pathlib import Path


def _load_stage():
    path = Path(__file__).resolve().parents[1] / "scripts" / "build_event_layer.py"
    spec = importlib.util.spec_from_file_location("build_event_layer", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_stage_writes_events_json(tmp_path):
    proc = tmp_path
    (proc / "chapter_summaries.json").write_text(json.dumps({
        "Chapter 12": {"chapter_id": "C12.xhtml", "chapter_title": "Chapter 12",
                       "summary_bullets": ["Celaena defeats Cain"]}
    }), encoding="utf-8")
    (proc / "relationships_classified.json").write_text(json.dumps([
        {"entity_a": "Celaena", "entity_b": "Cain",
         "key_moments": ["Ch12: Celaena defeats Cain"]}
    ]), encoding="utf-8")
    # No registry.json → registry is None, names pass through unresolved.

    stage = _load_stage()
    stage.run_for_processing(proc, language="en")

    out = json.loads((proc / "events.json").read_text(encoding="utf-8"))
    assert "events" in out
    assert len(out["events"]) == 1
    assert out["events"][0]["chapter"] == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_build_event_layer.py -v`
Expected: FAIL with `FileNotFoundError` / `AttributeError: module has no attribute 'run_for_processing'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/build_event_layer.py
"""build-event-layer (script executor, no LLM).

Structures chapter_summaries.json + relationships_classified.json into
events.json (SP0 of the Plot Spine feature, STU-478). Runs after
classify_relationships.py, before wiki_preparation.py.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wiki_creator.event_layer import build_events
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry


def run_for_processing(processing_dir: Path | str, language: str) -> list[dict]:
    """Build events.json from artifacts in ``processing_dir``. Returns events."""
    processing_dir = Path(processing_dir)
    summaries_path = processing_dir / "chapter_summaries.json"
    rels_path = processing_dir / "relationships_classified.json"

    summaries = _read_summaries(summaries_path)
    relationships = _read_relationships(rels_path)

    registry_path = processing_dir / "registry.json"
    registry = Registry.load(registry_path) if registry_path.exists() else None

    action_cues = load_lang_config(language).get("action_cues", [])
    events = build_events(summaries, relationships, registry, action_cues)

    (processing_dir / "events.json").write_text(
        json.dumps({"events": events}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[events] wrote {len(events)} events to {processing_dir / 'events.json'}",
          file=sys.stderr)
    return events


def _read_summaries(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("chapter_summaries", data) if isinstance(data, dict) else {}


def _read_relationships(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data.get("relationships", [])
    return data if isinstance(data, list) else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the event layer (events.json)")
    parser.add_argument("--book", required=True, help="Path to book YAML config")
    args = parser.parse_args()

    with open(args.book, encoding="utf-8") as f:
        import yaml
        ctx = yaml.safe_load(f) or {}

    book_paths = book_paths_from_yaml(args.book)
    run_for_processing(book_paths.processing, book_language(ctx))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_build_event_layer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/build_event_layer.py tests/test_build_event_layer.py
git commit -m "feat(events): build_event_layer stage writes events.json (STU-478)"
```

---

### Task 6: Wire the stage into the pipeline orchestration

**Files:**
- Modify: `run_wiki.py` (PRE_STEPS mapping for `wiki-preparation`)
- Modify: `Makefile`

**Interfaces:**
- Consumes: `scripts/build_event_layer.py --book <yaml>` (Task 5).
- Produces: `events.json` is generated automatically during a full `make run` / `run_wiki.py`, ordered after `classify_relationships.py` and before `scripts/wiki_preparation.py`.

- [ ] **Step 1: Locate the PRE_STEPS list for the `wiki-preparation` pipeline in `run_wiki.py`**

Run: `grep -n "classify_relationships\|PRE_STEPS\|wiki-preparation" run_wiki.py`
Expected: shows the list where `["python", "scripts/classify_relationships.py", "--book"]` is registered.

- [ ] **Step 2: Add the event-layer pre-step immediately after `classify_relationships.py`**

In the `wiki-preparation` PRE_STEPS list, add this entry right after the `classify_relationships.py` entry (same list, same `--book` convention):

```python
        ["python", "scripts/build_event_layer.py", "--book"],
```

- [ ] **Step 3: Add a `run-events` Makefile target**

Add after the `classify-relationships` target block in `Makefile`:

```makefile
run-events:
	python scripts/build_event_layer.py --book $(BOOK)
```

And add `run-events` to the `.PHONY` line.

- [ ] **Step 4: Verify the target runs on the committed fixture**

Run: `make run-events BOOK=library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`
Expected: stderr prints `[events] wrote N events to .../events.json` and `events.json` exists with a non-empty `events` array.

Run: `python -c "import json; d=json.load(open('library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/events.json')); print(len(d['events']), 'events'); print(any('Cain' in e['participants'] and e['chapter']>=10 for e in d['events']))"`
Expected: prints a count > 0 and `True` (the final duel beat is present with Cain as a participant).

- [ ] **Step 5: Commit**

```bash
git add run_wiki.py Makefile
git commit -m "feat(events): run build_event_layer after classify_relationships (STU-478)"
```

---

### Task 7: Expose per-entity events in the batch bundle

**Files:**
- Modify: `scripts/wiki_preparation.py` (`build_entity_bundle`)
- Test: `tests/test_wiki_preparation.py` (append; create if absent)

**Interfaces:**
- Consumes: `events.json` (`{"events": [...]}`) from Task 5, read once in `wiki_preparation.py`'s `main()` and passed into `build_entity_bundle`.
- Produces: each batch entity bundle gains `"entity_events": list[dict]` — the events (chapter-sorted) where the entity's canonical name is in `participants` or `places`. This is the channel SP1–SP4 consume (supersedes the empty `chapter_summary_context`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_wiki_preparation.py (append)
import importlib.util
from pathlib import Path


def _prep_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "wiki_preparation.py"
    spec = importlib.util.spec_from_file_location("wiki_preparation", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_entity_events_filtered_by_canonical_name():
    prep = _prep_module()
    events = [
        {"event_id": "e_ch12_0", "chapter": 12, "description": "duel",
         "participants": ["Celaena Sardothien", "Cain"], "places": ["Rifthold"]},
        {"event_id": "e_ch01_0", "chapter": 1, "description": "freed",
         "participants": ["Dorian Havilliard"], "places": ["Endovier"]},
    ]
    got = prep.events_for_entity("Celaena Sardothien", events)
    assert [e["event_id"] for e in got] == ["e_ch12_0"]
    got_place = prep.events_for_entity("Rifthold", events)
    assert [e["event_id"] for e in got_place] == ["e_ch12_0"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wiki_preparation.py::test_entity_events_filtered_by_canonical_name -v`
Expected: FAIL with `AttributeError: module 'wiki_preparation' has no attribute 'events_for_entity'`

- [ ] **Step 3: Write minimal implementation**

Add this helper near the other bundle builders in `scripts/wiki_preparation.py`:

```python
def events_for_entity(canonical_name: str, events: list[dict]) -> list[dict]:
    """Events where the entity participates or that occur at the entity (PLACE),
    sorted by chapter. The channel Plot Spine projections (SP1-SP4) consume."""
    hits = [
        e for e in events
        if canonical_name in e.get("participants", [])
        or canonical_name in e.get("places", [])
    ]
    return sorted(hits, key=lambda e: e.get("chapter", 0))
```

Then, in `build_entity_bundle(...)`, add `events` as a parameter (default `()`), and add the field to the returned bundle dict alongside `chapter_summary_context`:

```python
        "entity_events": events_for_entity(entity["canonical_name"], list(events)),
```

Finally, in `main()`, load events once and pass them in where `build_entity_bundle` is called:

```python
    import json as _json
    _events_path = paths.processing / "events.json"
    all_events = (
        _json.loads(_events_path.read_text(encoding="utf-8")).get("events", [])
        if _events_path.exists() else []
    )
    # ... build_entity_bundle(..., events=all_events)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_wiki_preparation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/wiki_preparation.py tests/test_wiki_preparation.py
git commit -m "feat(events): expose entity_events in batch bundles (STU-478)"
```

---

### Task 8: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full suite**

Run: `pytest -q`
Expected: all pass (no regressions).

- [ ] **Step 2: Type-check**

Run: `mypy wiki_creator/`
Expected: `Success: no issues found`.

- [ ] **Step 3: End-to-end on the fixture**

Run: `make run-events && make run-preparation BOOK=library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`
Expected: `events.json` present; the regenerated `wiki_inputs/batch_*.json` entities carry a non-empty `entity_events` for principals (Celaena, Chaol, Dorian).

Run (assertion):
```bash
python -c "
import json, glob
n=0
for f in glob.glob('library/sarah_j_maas/throne-of-glass/wiki_inputs/01-throne-of-glass/batch_*.json'):
    for e in json.load(open(f)).get('entities', []):
        if e['canonical_name'].startswith('Celaena') and e.get('entity_events'):
            n=len(e['entity_events'])
print('Celaena entity_events:', n)
assert n > 0
"
```
Expected: `Celaena entity_events: <N>` with N > 0 — the protagonist now carries her plot events into the bundle (the run-18 gap is closed).

- [ ] **Step 4: Commit any fixups**

```bash
git add -A && git commit -m "test(events): SP0 end-to-end verified on TOG fixture (STU-478)"
```

---

## Self-Review

**Spec coverage:**
- Event Layer stage (structure summaries + key_moments) → Tasks 1–5. ✓
- Canonical participant/place resolution via registry → Task 2. ✓
- Salience (action_cues + chapter position) → Task 3. ✓
- `source_bullets` grounding → Task 4. ✓
- `outcome` from action_cues → Task 4. ✓
- Pipeline placement (after classify-relationships, before wiki-preparation) → Task 6. ✓
- Fix `chapter_summary_context` wiring (empty for Celaena) → Task 7 supersedes it with `entity_events`. ✓
- Test criterion (events.json contains known_facts_book1 beats, canonical participants) → Tasks 5 & 8. ✓

**Placeholder scan:** none — every code step contains complete code.

**Type consistency:** `build_events` / `_resolve` / `_names_in` / `_salience` / `_has_action_cue` / `_parse_chapter` signatures are consistent across Tasks 1–4; `run_for_processing` and `events_for_entity` names match between Tasks 5–8.

**Deferred (not SP0, documented):** deeper event aggregation (semantic dedup beyond exact-description match) and participant-importance weighting in salience are intentionally out of scope for v1 — the exact-match dedup + action-cue/position salience are sufficient to unblock SP1. Revisit if SP1 shows noisy events.
