# Validated Artifact I/O Implementation Plan (STU-447)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every main-pipeline artifact a validated write/read boundary backed by real dataclass schemas, so schema drift fails loudly instead of silently.

**Architecture:** Reconcile `wiki_creator/types.py` dataclasses to the real artifact shapes, add a strict recursive codec (`to_dict`/`from_dict`/`save_artifact`/`load_artifact`) to `wiki_creator/studio_io.py`, then wire each producer/consumer pair to it and delete the defensive `.get(..., default)` reads and multi-shape compat paths.

**Tech Stack:** Python 3, stdlib `dataclasses` + `typing` only. No new dependency. `pytest`, `mypy`.

## Global Constraints

- No new runtime dependency — stdlib `dataclasses`/`typing` only.
- `types.py` MUST NOT use `from __future__ import annotations` (the codec resolves field types via `typing.get_type_hints`, which works either way, but keeping annotations as real objects avoids surprises).
- Registry serialization (`registry.json`, `wiki_creator/registry.py`) is out of scope — already validated by its own `to_dict`/`from_dict`.
- Off-pipeline scripts (`lora_*`, `eval_coref`, `test_*`) are out of scope.
- Canonical importance labels are English: `principal | secondary | figurant | ignored`.
- `pytest -q` and `mypy wiki_creator/` must be green before ship.
- Commit trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

## File Structure

- `wiki_creator/types.py` — MODIFY. Artifact schema dataclasses (reconciled).
- `wiki_creator/studio_io.py` — MODIFY. Add codec: `ArtifactSchemaError`, `to_dict`, `from_dict`, `save_artifact`, `load_artifact`.
- `tests/test_studio_io_codec.py` — CREATE. Codec unit tests.
- `scripts/entity_extraction.py`, `scripts/split_clusters.py`, `scripts/entity_classification.py`, `scripts/save_relationships.py`, `scripts/classify_relationships.py`, `scripts/chapter_summary.py`, `scripts/generate_wiki_pages.py`, `scripts/build_event_layer.py` — MODIFY (producers).
- consumers per artifact (see each task) — MODIFY.
- `scripts/merge_entities.py`, `scripts/wiki_preparation.py` — MODIFY (phase 4 compat removal).

---

## Task 1: Reconcile `types.py` schemas

**Files:**
- Modify: `wiki_creator/types.py`
- Test: `tests/test_types.py` (existing — update to match new shapes)

**Interfaces:**
- Produces: dataclasses `EntityFull`, `MentionSpan`, `Splits`, `SplitSingle`, `SplitCluster`, `ClassifiedEntity`, `ClassifiedBundle`, `Relationship`, `RelationshipBundle`, `ChapterSummary`, `WikiPage`, `Event`, `EventBundle`. Importance `Literal` = `("principal","secondary","figurant","ignored")`.

- [ ] **Step 1: Replace `types.py` body**

Keep `EpubChapter`, `ParsedBook`. Delete the dead `ExtractedEntity`, `ResolvedEntity`, `WikiPageDraft`, `EntityRegistryEntry`, `EntityRegistry`, `ExtractedRelationship`. Add:

```python
from dataclasses import dataclass, field
from typing import Literal

ENTITY_TYPE = Literal["PERSON", "PLACE", "ORG", "EVENT", "OTHER"]
IMPORTANCE = Literal["principal", "secondary", "figurant", "ignored"]
TEMPORAL = Literal["present", "flashback", "unknown"]


@dataclass
class MentionSpan:
    surface: str
    start: int
    end: int


@dataclass
class EntityFull:
    type: ENTITY_TYPE
    raw_mentions: list[str]
    first_seen: str
    mention_count: int
    mentions_by_chapter: dict = field(default_factory=dict)
    mention_spans_by_chapter: dict = field(default_factory=dict)


@dataclass
class SplitSingle:
    canonical_name: str
    type: ENTITY_TYPE
    aliases: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    relevant: bool = True


@dataclass
class SplitCluster:
    type: ENTITY_TYPE
    canonical_candidate: str
    entity_ids: list[str] = field(default_factory=list)
    all_mentions: list[str] = field(default_factory=list)
    entity_count: int = 0


@dataclass
class Splits:
    singles_resolved: list[SplitSingle] = field(default_factory=list)
    PERSON: list[SplitCluster] = field(default_factory=list)
    PLACE: list[SplitCluster] = field(default_factory=list)
    ORG: list[SplitCluster] = field(default_factory=list)
    EVENT: list[SplitCluster] = field(default_factory=list)
    OTHER: list[SplitCluster] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    pov_detection: dict | None = None


@dataclass
class ClassifiedEntity:
    canonical_name: str
    type: ENTITY_TYPE
    total_mentions: int
    chapters_present: int
    importance: IMPORTANCE
    source_ids: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    relevant: bool = True


@dataclass
class Relationship:
    entity_a: str
    entity_b: str
    cooccurrence_count: int
    chapters: list[str] = field(default_factory=list)
    sample_contexts: list[str] = field(default_factory=list)
    relationship_type: str | None = None
    direction: str | None = None
    evolution: str | None = None
    key_moments: list[str] = field(default_factory=list)


@dataclass
class ClassifiedBundle:
    entities: list[ClassifiedEntity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    narrator: str | None = None


@dataclass
class RelationshipBundle:
    entities: list[ClassifiedEntity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    narrator: str | None = None


@dataclass
class ChapterSummary:
    chapter_id: str
    chapter_title: str
    summary_bullets: list[str] = field(default_factory=list)
    summary_method: str = ""
    quality_flags: list = field(default_factory=list)
    temporal_context: TEMPORAL = "present"
    flashback_anchor: str | None = None
    pov_character: str | None = None
    pov_confidence: float | None = None
    pov_method: str | None = None


@dataclass
class WikiPage:
    title: str
    importance: str
    entity_type: str
    books: list[str] = field(default_factory=list)
    infobox_fields: dict = field(default_factory=dict)
    content: str = ""
    _failed: bool | None = None
    _insufficient_data: bool | None = None


@dataclass
class Event:
    chapter: int
    description: str
    event_id: str
    participants: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    outcome: str | None = None
    salience: float = 0.0
    source_bullets: list[str] = field(default_factory=list)


@dataclass
class EventBundle:
    events: list[Event] = field(default_factory=list)
```

Before writing, confirm the real `ChapterSummary` pov_* and `Splits`/`SplitCluster` field names against the producers:

Run: `rg -n "pov_" scripts/chapter_summary.py | head` and `rg -n "canonical_candidate|entity_count|all_mentions|source_ids|relevant" scripts/split_clusters.py`
Expected: the field names above appear; adjust any that differ before continuing.

- [ ] **Step 2: Update `tests/test_types.py`**

Replace references to deleted dataclasses with the new ones; assert a couple of constructions, e.g.:

```python
from wiki_creator.types import EntityFull, ClassifiedEntity

def test_entity_full_construction():
    e = EntityFull(type="PERSON", raw_mentions=["Celaena"], first_seen="ch1", mention_count=3)
    assert e.mentions_by_chapter == {}

def test_classified_entity_importance_literal():
    c = ClassifiedEntity(canonical_name="Celaena", type="PERSON", total_mentions=40, chapters_present=10, importance="principal")
    assert c.importance == "principal"
```

- [ ] **Step 3: Run**

Run: `pytest tests/test_types.py -q && mypy wiki_creator/types.py`
Expected: PASS, no type errors.

- [ ] **Step 4: Commit**

```bash
git add wiki_creator/types.py tests/test_types.py
git commit -m "refactor(types): reconcile artifact dataclasses to real shapes (STU-447)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Codec in `studio_io.py`

**Files:**
- Modify: `wiki_creator/studio_io.py`
- Test: `tests/test_studio_io_codec.py` (create)

**Interfaces:**
- Consumes: dataclasses from Task 1.
- Produces: `ArtifactSchemaError(ValueError)`; `to_dict(obj) -> Any`; `from_dict(schema, data, path="$") -> Any`; `save_artifact(path, obj, schema) -> None`; `load_artifact(path, schema) -> Any`. `schema` is a dataclass type, `list[T]`, or `dict[str, T]`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_studio_io_codec.py`:

```python
import pytest
from dataclasses import dataclass, field
from typing import Literal
from wiki_creator import studio_io
from wiki_creator.studio_io import ArtifactSchemaError, to_dict, from_dict


@dataclass
class Leaf:
    name: str
    score: float
    tag: Literal["a", "b"] = "a"
    note: str | None = None
    items: list[str] = field(default_factory=list)


@dataclass
class Nest:
    leaf: Leaf
    leaves: list[Leaf] = field(default_factory=list)


def test_roundtrip_dataclass():
    n = Nest(leaf=Leaf(name="x", score=1.0), leaves=[Leaf(name="y", score=2.0, tag="b")])
    assert from_dict(Nest, to_dict(n)) == n


def test_roundtrip_list_container():
    data = [Leaf(name="x", score=1.0), Leaf(name="y", score=2.0)]
    assert from_dict(list[Leaf], to_dict(data)) == data


def test_roundtrip_dict_container():
    data = {"a": Leaf(name="x", score=1.0)}
    assert from_dict(dict[str, Leaf], to_dict(data)) == data


def test_missing_required_raises():
    with pytest.raises(ArtifactSchemaError, match="score"):
        from_dict(Leaf, {"name": "x"})


def test_unknown_key_raises():
    with pytest.raises(ArtifactSchemaError, match="drifted"):
        from_dict(Leaf, {"name": "x", "score": 1.0, "drifted": 9})


def test_type_mismatch_raises():
    with pytest.raises(ArtifactSchemaError, match="score"):
        from_dict(Leaf, {"name": "x", "score": "not-a-number"})


def test_literal_violation_raises():
    with pytest.raises(ArtifactSchemaError, match="tag"):
        from_dict(Leaf, {"name": "x", "score": 1.0, "tag": "z"})


def test_optional_none_ok():
    assert from_dict(Leaf, {"name": "x", "score": 1.0, "note": None}).note is None


def test_int_accepted_for_float():
    assert from_dict(Leaf, {"name": "x", "score": 1}).score == 1.0


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "a.json"
    n = Nest(leaf=Leaf(name="x", score=1.0))
    studio_io.save_artifact(p, n, Nest)
    assert studio_io.load_artifact(p, Nest) == n


def test_save_rejects_offschema(tmp_path):
    # obj whose serialized form violates schema cannot be written
    bad = Leaf(name="x", score=1.0, tag="a")
    object.__setattr__(bad, "tag", "z")
    with pytest.raises(ArtifactSchemaError):
        studio_io.save_artifact(tmp_path / "b.json", bad, Leaf)
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest tests/test_studio_io_codec.py -q`
Expected: FAIL (`ImportError: cannot import name 'ArtifactSchemaError'`).

- [ ] **Step 3: Implement codec**

Append to `wiki_creator/studio_io.py` (add `import dataclasses`, `import typing`, and `from typing import Any, Literal, Union, get_args, get_origin` to the imports):

```python
class ArtifactSchemaError(ValueError):
    """Raised when an artifact does not match its declared schema."""


def to_dict(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, list):
        return [to_dict(v) for v in obj]
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    return obj


def from_dict(schema: Any, data: Any, path: str = "$") -> Any:
    origin = get_origin(schema)

    if origin in (list, typing.List):
        (elem,) = get_args(schema)
        if not isinstance(data, list):
            raise ArtifactSchemaError(f"{path}: expected array, got {type(data).__name__}")
        return [from_dict(elem, v, f"{path}[{i}]") for i, v in enumerate(data)]

    if origin in (dict, typing.Dict):
        _k, val = get_args(schema)
        if not isinstance(data, dict):
            raise ArtifactSchemaError(f"{path}: expected object, got {type(data).__name__}")
        return {k: from_dict(val, v, f"{path}.{k}") for k, v in data.items()}

    if origin is Union:
        members = get_args(schema)
        if data is None and type(None) in members:
            return None
        non_none = [m for m in members if m is not type(None)]
        return from_dict(non_none[0], data, path)

    if origin is Literal:
        allowed = get_args(schema)
        if data not in allowed:
            raise ArtifactSchemaError(f"{path}: {data!r} not one of {allowed}")
        return data

    if dataclasses.is_dataclass(schema):
        if not isinstance(data, dict):
            raise ArtifactSchemaError(f"{path}: expected object for {schema.__name__}, got {type(data).__name__}")
        hints = typing.get_type_hints(schema)
        fields = {f.name: f for f in dataclasses.fields(schema)}
        unknown = sorted(set(data) - set(fields))
        if unknown:
            raise ArtifactSchemaError(f"{path}: unknown keys {unknown} for {schema.__name__}")
        kwargs = {}
        for name, f in fields.items():
            if name in data:
                kwargs[name] = from_dict(hints[name], data[name], f"{path}.{name}")
            elif f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                raise ArtifactSchemaError(f"{path}: missing required field {name!r}")
        return schema(**kwargs)

    if schema in (int, float, str, bool):
        if schema is float and isinstance(data, int) and not isinstance(data, bool):
            return float(data)
        if isinstance(data, bool) != (schema is bool):
            raise ArtifactSchemaError(f"{path}: expected {schema.__name__}, got {type(data).__name__}")
        if not isinstance(data, schema):
            raise ArtifactSchemaError(f"{path}: expected {schema.__name__}, got {type(data).__name__}")
        return data

    # Any / untyped dict|list: pass through unvalidated (free-form fields like stats/infobox_fields)
    return data


def save_artifact(path, obj: Any, schema: Any) -> None:
    payload = to_dict(obj)
    from_dict(schema, payload)  # roundtrip self-check: never write off-schema
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)


def load_artifact(path, schema: Any) -> Any:
    with open(path, encoding="utf-8") as f:
        return from_dict(schema, json.load(f))
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/test_studio_io_codec.py -q && mypy wiki_creator/studio_io.py`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/studio_io.py tests/test_studio_io_codec.py
git commit -m "feat(studio_io): strict dataclass codec for artifact validation (STU-447)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

> **Phase 3 (Tasks 3-9) pattern.** Each task wires ONE artifact: producer writes via `save_artifact`, every consumer reads via `load_artifact`, and that artifact's defensive `.get(..., default)` reads are deleted. These tasks are additive — no output shape changes, so existing stage tests stay green. For the wrapper-keyed `*_full` files and dict-keyed files, the caller keeps unwrapping/wrapping the outer key; the codec validates the inner `dict[str, T]`.

## Task 3: Wire `*_full.json` (extraction)

**Files:**
- Modify: `scripts/entity_extraction.py:768-770` (writer)
- Modify consumers: `scripts/entity_classification.py:686-689`, `scripts/alias_resolution.py:98`, `scripts/wiki_preparation.py:510-513`, `scripts/write_registry.py:83-86`, `scripts/relationship_extraction.py:1183`
- Test: `tests/test_entity_extraction.py` (add drift test)

**Interfaces:**
- Consumes: `save_artifact`/`load_artifact`, `EntityFull`.

- [ ] **Step 1: Writer → `save_artifact`**

The files are wrapped by `json_key`, so the codec validates the inner `dict[str, EntityFull]` while the caller keeps the wrapper. In `scripts/entity_extraction.py`, replace the per-type write loop body:

```python
from wiki_creator.types import EntityFull

for type_key, (filename, json_key) in type_files.items():
    records = {eid: EntityFull(**rec) for eid, rec in by_type[type_key].items()}
    studio_io.from_dict(dict[str, EntityFull], studio_io.to_dict(records))  # self-check
    with open(paths.processing / filename, "w", encoding="utf-8") as f:
        json.dump({json_key: studio_io.to_dict(records)}, f, ensure_ascii=False)
```

- [ ] **Step 2: Consumers → validated load**

At each consumer, after unwrapping the `json_key`, validate. Add a shared helper in `studio_io.py`:

```python
def load_full_file(path, json_key: str):
    from wiki_creator.types import EntityFull
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return from_dict(dict[str, EntityFull], raw.get(json_key, raw))
```

Replace each consumer's raw `json.load` + `.get(json_key)` with `studio_io.load_full_file(path, json_key)`, returning `EntityFull` objects (attribute access replaces `.get("mention_count", 0)` etc. — update those call sites to `.mention_count`).

Run: `rg -n '\["mention_count"\]|\.get\("mention_count"|\["raw_mentions"\]|\.get\("raw_mentions"' scripts/` to find the defensive reads to convert.

- [ ] **Step 3: Drift test**

Add to `tests/test_entity_extraction.py`:

```python
def test_full_file_drift_raises(tmp_path):
    import json
    from wiki_creator import studio_io
    from wiki_creator.studio_io import ArtifactSchemaError
    p = tmp_path / "persons_full.json"
    p.write_text(json.dumps({"persons_full": {"e1": {"type": "PERSON", "raw_mentions": [], "first_seen": "c1", "mention_count": 1, "surprise": 9}}}))
    with pytest.raises(ArtifactSchemaError, match="surprise"):
        studio_io.load_full_file(p, "persons_full")
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_entity_extraction.py tests/test_entity_classification.py tests/test_alias_resolution.py -q && mypy wiki_creator/`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat(extraction): validated *_full.json write/read (STU-447)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire `splits.json`

**Files:**
- Modify: `scripts/split_clusters.py:89` (writer)
- Modify consumers: `scripts/write_registry.py:77`, `scripts/load_splits.py:18`
- Test: `tests/test_split_clusters.py`

- [ ] **Step 1: Writer → `save_artifact(path, Splits(...), Splits)`.** Build a `Splits` from the assembled dict (`Splits(**splits_dict)` after constructing `SplitSingle`/`SplitCluster` lists), then `studio_io.save_artifact(paths.processing / "splits.json", splits_obj, Splits)`.
- [ ] **Step 2: Consumers → `studio_io.load_artifact(path, Splits)`;** replace `data["PERSON"]` etc. and `.get("singles_resolved", [])` with attribute access.
- [ ] **Step 3: Drift test** — write a `splits.json` with an unknown top-level key, assert `ArtifactSchemaError`.
- [ ] **Step 4: Run** `pytest tests/test_split_clusters.py tests/test_write_registry.py -q && mypy wiki_creator/`
- [ ] **Step 5: Commit** `feat(splits): validated splits.json write/read (STU-447)`

---

## Task 5: Wire `entities_classified.json`

**Files:**
- Modify: `scripts/entity_classification.py:815-819` (writer)
- Modify consumers: `scripts/build_event_layer.py:57`, `scripts/chapter_summary.py:796,853`, `scripts/wiki_preparation.py:465-467`, `scripts/write_registry.py:73-75`
- Test: `tests/test_entity_classification.py`

> NOTE: importance is still `secondaire` at this point — Task 1's `ClassifiedEntity.importance` Literal is English-only, so this task would FAIL validation on `secondaire`. Do NOT wire this artifact until Task 10 flips the producer to English. **Task 5 is scheduled after Task 10** (see Execution Order). Alternatively, fold Task 5 into Task 10.

- [ ] **Step 1: Writer → `save_artifact`.** Build `ClassifiedBundle` and write via `studio_io.save_artifact(paths.processing / "entities_classified.json", bundle, ClassifiedBundle)`. Keep the stdout `json.dump(studio_io.to_dict(bundle), sys.stdout)`.
- [ ] **Step 2: Consumers → `load_artifact(path, ClassifiedBundle)`;** attribute access replaces `e["importance"]`, `e.get("total_mentions", 0)`.
- [ ] **Step 3: Drift test** — unknown key raises.
- [ ] **Step 4: Run** relevant tests + `mypy wiki_creator/`
- [ ] **Step 5: Commit** `feat(classification): validated entities_classified.json write/read (STU-447)`

---

## Task 6: Wire `relationships.json` / `relationships_classified.json`

**Files:**
- Modify: `scripts/save_relationships.py:39`, `scripts/classify_relationships.py:54` (writers)
- Modify consumers: `scripts/build_event_layer.py:51`, `scripts/wiki_preparation.py:478-490`
- Test: `tests/test_save_relationships.py`, `tests/test_classify_relationships.py`

- [ ] **Step 1: Writers → `save_artifact(path, RelationshipBundle(...), RelationshipBundle)`.**
- [ ] **Step 2: Consumers → `load_artifact(path, RelationshipBundle)`;** the classified-vs-unclassified fallback stays (try `_classified` file, else base) but each branch now returns validated `RelationshipBundle`. Attribute access replaces `.get("relationship_type")` etc.
- [ ] **Step 3: Drift test** — unknown key raises.
- [ ] **Step 4: Run** relevant tests + `mypy wiki_creator/`
- [ ] **Step 5: Commit** `feat(relationships): validated relationships[_classified].json write/read (STU-447)`

---

## Task 7: Wire `chapter_summaries.json`

**Files:**
- Modify: `scripts/chapter_summary.py:799,856` (writer)
- Modify consumers: `scripts/build_event_layer.py:50`, `scripts/wiki_preparation.py:548`
- Test: `tests/test_chapter_summary.py`

- [ ] **Step 1: Verify field names.** Run `rg -n "pov_|quality_flags|flashback_anchor|summary_method|summary_bullets" scripts/chapter_summary.py` and reconcile `ChapterSummary` (Task 1) with the actual keys before wiring. Add any missing Optional field.
- [ ] **Step 2: Writer → validated `dict[str, ChapterSummary]`.** The file is chapter-keyed; construct `{cid: ChapterSummary(**s) for ...}`, self-check `from_dict(dict[str, ChapterSummary], to_dict(...))`, write. Preserve the outer wrapper key if one exists (`chapter_summaries`).
- [ ] **Step 3: Consumers → validated load;** attribute access replaces `.get("temporal_context", "present")`.
- [ ] **Step 4: Drift test** — unknown key raises.
- [ ] **Step 5: Run** relevant tests + `mypy wiki_creator/`; **Commit** `feat(summaries): validated chapter_summaries.json write/read (STU-447)`

---

## Task 8: Wire `wiki_pages.json`

**Files:**
- Modify: `scripts/generate_wiki_pages.py:1340` (writer)
- Modify consumers: `scripts/load_wiki_pages.py:56`
- Test: `tests/test_generate_wiki_pages.py`

- [ ] **Step 1: Writer → `save_artifact(path, [WikiPage(**p) for p in pages], list[WikiPage])`.** `_failed`/`_insufficient_data` are Optional in the schema, so partial/failed pages validate.
- [ ] **Step 2: Consumer → `load_artifact(path, list[WikiPage])`.**
- [ ] **Step 3: Drift test** — unknown key raises.
- [ ] **Step 4: Run** relevant tests + `mypy wiki_creator/`; **Commit** `feat(pages): validated wiki_pages.json write/read (STU-447)`

---

## Task 9: Wire `events.json`

**Files:**
- Modify: `scripts/build_event_layer.py:62` (writer)
- Modify consumers: `scripts/generate_book_synopsis.py`
- Test: `tests/test_build_event_layer.py`, `tests/test_generate_book_synopsis.py`

- [ ] **Step 1: Writer → `save_artifact(path, EventBundle(events=[Event(**e) ...]), EventBundle)`.**
- [ ] **Step 2: Consumer → `load_artifact(path, EventBundle)`;** the "events.json absent → warn and skip" path in `generate_book_synopsis.py` stays (guard on file existence before load).
- [ ] **Step 3: Drift test** — unknown key raises.
- [ ] **Step 4: Run** relevant tests + `mypy wiki_creator/`; **Commit** `feat(events): validated events.json write/read (STU-447)`

---

## Task 10: Remove compat + canonicalize importance (phase 4)

**Files:**
- Modify: `scripts/entity_classification.py:214,806-808` (importance → English)
- Modify: `scripts/wiki_preparation.py:50,467` (delete `_IMPORTANCE_NORMALIZE`)
- Modify: `scripts/merge_entities.py:41-55` (drop gen-2/gen-3 compat)
- Modify: tests exercising old shapes; goldens
- Test: `tests/test_merge_entities.py`, `tests/test_entity_classification.py`, `tests/test_e2e_golden.py`

**Interfaces:**
- After this task, `entities_classified.json` importance is English; Task 5 can be wired (or is wired here).

- [ ] **Step 1: Canonicalize importance in producer.** In `scripts/entity_classification.py`, `assign_importance` line 214: change the middle tier return from `"secondaire"` to `"secondary"`. In the stats dict (lines 806-808) rename the `"secondaire"` key + counter lookup to `"secondary"`.

Run: `rg -n "secondaire" scripts/ wiki_creator/`
Expected: only comments/docstrings remain; convert or delete them.

- [ ] **Step 2: Delete `_IMPORTANCE_NORMALIZE`.** In `scripts/wiki_preparation.py` remove the constant (line ~50) and its call site (line ~467): `e["importance"]` is already English.

- [ ] **Step 3: Drop merge compat.** In `scripts/merge_entities.py` remove the gen-2 (`resolve-clusters`) and gen-3 (`split-clusters` + `entity-resolution-*`) branches (lines ~41-55). Keep only the current alias-resolution input shape. Delete the tests that construct the legacy shapes; keep/adjust the current-shape test.

- [ ] **Step 4: Wire `entities_classified.json`** (Task 5 steps 1-3) now that importance is English.

- [ ] **Step 5: Run unit tests**

Run: `pytest -q -k "classification or merge or preparation or event_layer"`
Expected: PASS (update assertions expecting `secondaire` → `secondary`).

- [ ] **Step 6: Regenerate goldens**

Run: `make golden-update`
Then: `git diff tests/fixtures/e2e/golden/` — confirm the diff is exactly (a) importance `secondaire`→`secondary` at classification output and downstream, (b) merged-entity output losing legacy-shape artifacts. No unexpected changes.

- [ ] **Step 7: Full suite**

Run: `pytest -q && mypy wiki_creator/`
Expected: `pytest` green (≈1113 passed baseline ± the tests you added/removed), no type errors.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(schema): canonicalize importance to English, drop multi-shape compat (STU-447)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Execution Order

1 → 2 → 3 → 4 → 6 → 7 → 8 → 9 → **10** → 5.

Task 5 (`entities_classified.json` wiring) runs **after** Task 10 because its `ClassifiedEntity.importance` Literal is English-only and would reject the pre-canonicalization `secondaire`. Task 10 Step 4 folds Task 5 in; the standalone Task 5 entry documents the wiring for reviewers.

## Testing Summary

- Codec unit tests (Task 2): roundtrip, three raise conditions, three container forms.
- Per-artifact drift test (Tasks 3-9): a stray key raises `ArtifactSchemaError`.
- Additive-plumbing tasks (3,4,6-9) keep existing stage tests green with no golden churn.
- Task 10: `make golden-update` + reviewed golden diff; full `pytest -q` + `mypy wiki_creator/` green.
