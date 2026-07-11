# STU-441 — EntityRegistry pas 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the pure module `wiki_creator/registry.py` (read-only EntityRegistry rebuilt from existing artifacts), serialize it as `processing_output/<slug>/registry.json` with 4 invariants enforced, and wire a final `write-registry` stage into `wiki-resolution` — with zero pipeline behavior change (pure addition).

**Architecture:** `registry.py` follows the proven `page_templates.py` pattern: frozen dataclasses + pure functions + `ValueError` on invariant violation, no pipeline side effects. Reconstruction (`Registry.from_artifacts`) joins three existing artifacts: the alias-resolution stage output (merged entities + recorded merge evidence), `splits.json` (which aliases arrived via Jaro-Winkler clusters), and the `*_full.json` mention registries (surfaces, chapter ids, context sentences). A new final pipeline stage `write-registry` (modeled exactly on `save-relationships`) writes `registry.json`. Nothing consumes it yet — the first consumer is STU-435 (pas 3).

**Tech Stack:** Python (stdlib only: `dataclasses`, `json`, `re`, `hashlib`, `unicodedata`), pytest, Studio pipeline YAML (script executor).

**Linear:** [STU-441](https://linear.app/studioag/issue/STU-441/entityregistry-pas-1-module-registrypy-en-lecture-seule-registryjson) — branch `arianedguay/stu-441-entityregistry-pas-1-module-registrypy-en-lecture-seule` (work in a dedicated git worktree off `main`, per CLAUDE.md).

**Spec:** `docs/superpowers/specs/2026-07-11-refondation-wiki-creator-design.md` §3.2 (data model), §3.3 (artifact), §3.4 (API), §3.5 pas 1, §3.7 (tests).

## Global Constraints

- **Zero behavior change** to existing stages: `write-registry` is appended at the end of `wiki-resolution`; no existing script or contract is modified.
- Pure module rule: `wiki_creator/registry.py` performs no I/O except in `save()`/`load()`; no imports from `scripts/`.
- No hardcoded vocabulary lists (CLAUDE.md rule) — this module needs none.
- Existing suite stays green: baseline is `pytest -q` → `735 passed, 31 skipped`.
- `mypy wiki_creator/` must pass (registry.py is inside the checked package).
- Deviations from spec §3.2 decided with Ariane on 2026-07-11:
  - `Mention.start/end/raw_label` are `int | None` / `str | None` (artifacts don't preserve offsets or raw NER labels); extra field `context: str | None` carries the preserved sentence.
  - Synthesized `MergeDecision.strategy` values: `"cluster_jw"` (alias found in a `splits.json` multi-cluster), `"extraction_grouping"` (NER surface-variant grouping), and the **verbatim** recorded method names from `alias_resolution` blocks (`pattern`, `title_alias`, `pure_title`, `role_symmetric`, `llm`, `cooccurrence`). Spec-enum vocabulary arrives natively at pas 2 (STU-442).
- `merge()` from the spec API sketch (§3.4) is **out of scope** — pas 1 is read-only; `merge()` is the deliverable of STU-442.
- Commit style: `feat(registry): … (STU-441)` matching repo history; commit after every green task.

## Artifact shapes consumed (reference — verified 2026-07-11 on main)

- **alias_output** = alias-resolution stage output (`scripts/alias_resolution.py:839,913`): `{"entities": [...], "narrator": null, "stats": {...}}`. Entity dict: `{canonical_name, type, aliases: list[str] (sorted, canonical included), source_ids: ["entity_001", ...], relevant}`, plus for merged PERSONs an `alias_resolution` block: `{merged_from: [names], evidence: [{method, confidence, snippet}], confidence, method}`. `entities_classified.json` on disk contains the same entity dicts (superset) and works as fallback input.
- **splits** = `processing_output/<slug>/splits.json` (`scripts/split_clusters.py:102`): `{singles_resolved: [...], PERSON: [<cluster>], PLACE: [...], ORG: [...], EVENT: [...], OTHER: [...], stats, pov_detection?}`. Cluster keys: `canonical_candidate`, `type`, `all_mentions`, `entity_ids`, `entity_count`.
- **full registries** = `persons_full.json` / `places_full.json` / `orgs_full.json` / `events_full.json` (`scripts/entity_extraction.py:655-670,833-840`): `{"entity_001": {type, raw_mentions: [surfaces], first_seen: "ch01", mention_count, mentions_by_chapter: {"ch01": ["<sentence>", ...max 3]}}}`. **No character offsets, no raw NER labels exist** — hence the Optional fields.

---

### Task 1: Data model + deterministic ID helpers

**Files:**
- Create: `wiki_creator/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces: dataclasses `Mention`, `MergeDecision`, `EntityRecord`; functions `entity_slug(name: str) -> str`, `_decision_id(strategy: str, inputs: tuple[str, str], evidence: str) -> str`; constants `REGISTRY_VERSION = 1`, `ENTITY_TYPES`. Later tasks add the `Registry` class to this same file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_registry.py`:

```python
"""Tests for wiki_creator/registry.py — EntityRegistry pas 1 (STU-441)."""
import pytest

from wiki_creator.registry import (
    EntityRecord,
    MergeDecision,
    Mention,
    entity_slug,
)


def test_entity_slug_is_deterministic_lowercase_ascii():
    assert entity_slug("Chaol Westfall") == "chaol_westfall"
    assert entity_slug("Chaol Westfall") == entity_slug("Chaol Westfall")
    # accents fold to ascii, punctuation collapses to single underscore
    assert entity_slug("Céfiro—Dorn!") == "cefiro_dorn"
    # leading/trailing separators stripped
    assert entity_slug("  The Guard  ") == "the_guard"
    # degenerate input still yields a usable id
    assert entity_slug("") == "unnamed"
    assert entity_slug("!!!") == "unnamed"


def test_mention_defaults_reflect_reconstruction_gaps():
    m = Mention(surface="Perrington", chapter_id="ch02")
    assert m.source == "ner"
    assert m.start is None and m.end is None
    assert m.raw_label is None and m.context is None


def test_merge_decision_is_frozen():
    d = MergeDecision(
        decision_id="d_abc",
        strategy="pure_title",
        inputs=("perrington", "duke_perrington"),
        evidence="snippet",
        confidence="high",
    )
    assert d.reversible is True
    with pytest.raises(AttributeError):
        d.strategy = "manual"  # type: ignore[misc]


def test_entity_record_defaults():
    r = EntityRecord(entity_id="perrington", canonical_name="Perrington", entity_type="PERSON")
    assert r.aliases == [] and r.mentions == [] and r.decisions == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_creator.registry'`

- [ ] **Step 3: Write the implementation**

Create `wiki_creator/registry.py`:

```python
"""Entity identity registry — single source of truth for « qui est qui ».

Pure module, no pipeline side effects (same pattern as page_templates.py).

Pas 1 (STU-441): read-only reconstruction from existing pipeline artifacts
(splits.json + alias-resolution output + *_full.json mention registries).
Nothing consumes registry.json yet — the first consumer is STU-435 (pas 3).

Spec: docs/superpowers/specs/2026-07-11-refondation-wiki-creator-design.md §3
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

REGISTRY_VERSION = 1
ENTITY_TYPES = ("PERSON", "PLACE", "ORG", "EVENT", "OTHER")


@dataclass(frozen=True)
class Mention:
    surface: str
    chapter_id: str
    source: str = "ner"  # "ner" | "coref" | "pattern"
    # None when rebuilt from artifacts: extraction does not preserve character
    # offsets nor the raw model label — real values arrive when extraction
    # feeds the registry directly (pas 2+).
    start: int | None = None
    end: int | None = None
    raw_label: str | None = None
    context: str | None = None  # context sentence from *_full.json


@dataclass(frozen=True)
class MergeDecision:
    decision_id: str
    strategy: str  # "cluster_jw" | "extraction_grouping" | recorded method | "manual"
    inputs: tuple[str, str]  # (surviving entity_id, absorbed entity_id / alias slug)
    evidence: str
    confidence: str  # "high" | "medium" | "low" | "certain" (manual)
    reversible: bool = True


@dataclass
class EntityRecord:
    entity_id: str  # stable slug derived from the canonical name
    canonical_name: str
    entity_type: str  # PERSON | PLACE | ORG | EVENT | OTHER
    aliases: list[str] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)  # decision_ids


def entity_slug(name: str) -> str:
    """Deterministic ascii slug for entity ids (invariant 4: no randomness)."""
    ascii_name = (
        unicodedata.normalize("NFKD", str(name or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_name.lower()).strip("_")
    return slug or "unnamed"


def _decision_id(strategy: str, inputs: tuple[str, str], evidence: str) -> str:
    """Content-derived id: identical decision content ⇒ identical id across runs."""
    payload = json.dumps([strategy, list(inputs), evidence], ensure_ascii=False)
    return "d_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/registry.py tests/test_registry.py
git commit -m "feat(registry): data model + deterministic slug/decision-id helpers (STU-441)"
```

---

### Task 2: Registry core — lookup, alias_table, audit_log, invariants

**Files:**
- Modify: `wiki_creator/registry.py` (append `Registry` class)
- Test: `tests/test_registry.py` (append)

**Interfaces:**
- Consumes: Task 1 dataclasses and `entity_slug`.
- Produces: `class Registry` with `__init__(entities: list[EntityRecord] | None, decisions: dict[str, MergeDecision] | None, warnings: list[str] | None)`, attributes `entities: list[EntityRecord]`, `decisions: dict[str, MergeDecision]`, `warnings: list[str]`, and methods `lookup(surface: str) -> EntityRecord | None`, `alias_table() -> dict[str, str]`, `audit_log() -> list[MergeDecision]`, `validate() -> None` (raises `ValueError`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py`:

```python
from wiki_creator.registry import Registry, _decision_id


def _record_with_decision(
    entity_id: str,
    canonical: str,
    aliases: list[str],
    strategy: str = "extraction_grouping",
) -> tuple[EntityRecord, dict[str, MergeDecision]]:
    """Build a valid EntityRecord + the decisions justifying its non-canonical aliases."""
    decisions: dict[str, MergeDecision] = {}
    decision_ids: list[str] = []
    for alias in aliases:
        if alias == canonical:
            continue
        d_id = _decision_id(strategy, (entity_id, entity_slug(alias)), f"test:{alias}")
        decisions[d_id] = MergeDecision(
            decision_id=d_id,
            strategy=strategy,
            inputs=(entity_id, entity_slug(alias)),
            evidence=f"test:{alias}",
            confidence="medium",
        )
        decision_ids.append(d_id)
    record = EntityRecord(
        entity_id=entity_id,
        canonical_name=canonical,
        entity_type="PERSON",
        aliases=list(aliases),
        decisions=decision_ids,
    )
    return record, decisions


def _valid_registry() -> Registry:
    r1, d1 = _record_with_decision("chaol_westfall", "Chaol Westfall", ["Captain Westfall", "Chaol Westfall"])
    r2, d2 = _record_with_decision("perrington", "Perrington", ["Duke Perrington", "Perrington"])
    return Registry(entities=[r1, r2], decisions={**d1, **d2})


def test_lookup_matches_aliases_case_insensitively():
    registry = _valid_registry()
    assert registry.lookup("captain westfall").entity_id == "chaol_westfall"
    assert registry.lookup("PERRINGTON").entity_id == "perrington"
    assert registry.lookup("Nehemia") is None


def test_alias_table_maps_every_alias_to_its_entity_id():
    table = _valid_registry().alias_table()
    assert table["Captain Westfall"] == "chaol_westfall"
    assert table["Duke Perrington"] == "perrington"
    assert table["Perrington"] == "perrington"


def test_audit_log_is_sorted_and_complete():
    registry = _valid_registry()
    log = registry.audit_log()
    assert [d.decision_id for d in log] == sorted(d.decision_id for d in log)
    assert len(log) == 2


def test_validate_accepts_valid_registry():
    _valid_registry().validate()  # must not raise


def test_validate_rejects_alias_owned_by_two_entities():
    registry = _valid_registry()
    r_extra, d_extra = _record_with_decision("westfall_2", "Westfall Two", ["Captain Westfall", "Westfall Two"])
    registry.entities.append(r_extra)
    registry.decisions.update(d_extra)
    with pytest.raises(ValueError, match="invariant 1"):
        registry.validate()


def test_validate_rejects_alias_without_merge_decision():
    registry = _valid_registry()
    registry.entities[0].aliases.append("Mystery Name")
    with pytest.raises(ValueError, match="invariant 2"):
        registry.validate()


def test_validate_rejects_canonical_missing_from_aliases():
    registry = _valid_registry()
    registry.entities[1].aliases.remove("Perrington")
    with pytest.raises(ValueError, match="invariant 3"):
        registry.validate()


def test_validate_rejects_unknown_decision_id():
    registry = _valid_registry()
    registry.entities[0].decisions.append("d_does_not_exist")
    with pytest.raises(ValueError, match="unknown decision_id"):
        registry.validate()


def test_validate_rejects_duplicate_entity_ids():
    registry = _valid_registry()
    dup, d_dup = _record_with_decision("perrington", "Perrington Bis", ["Perrington Bis"])
    registry.entities.append(dup)
    registry.decisions.update(d_dup)
    with pytest.raises(ValueError, match="duplicate entity_id"):
        registry.validate()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_registry.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'Registry'`

- [ ] **Step 3: Write the implementation**

Append to `wiki_creator/registry.py`:

```python
class Registry:
    """In-memory registry. Invariants (spec §3.2) are enforced by validate():

    1. an alias belongs to exactly one entity (casefold comparison);
    2. every alias ≠ canonical_name is justified by ≥1 MergeDecision
       (its slug appears in the inputs of a decision attached to the record);
    3. canonical_name ∈ aliases;
    4. entity_id determinism — structural (ids derive only from content,
       see entity_slug/_decision_id) and covered by tests, not checkable
       within a single instance.
    """

    def __init__(
        self,
        entities: list[EntityRecord] | None = None,
        decisions: dict[str, MergeDecision] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.entities: list[EntityRecord] = list(entities or [])
        self.decisions: dict[str, MergeDecision] = dict(decisions or {})
        self.warnings: list[str] = list(warnings or [])

    def lookup(self, surface: str) -> EntityRecord | None:
        key = str(surface).casefold()
        for record in self.entities:
            if any(alias.casefold() == key for alias in record.aliases):
                return record
        return None

    def alias_table(self) -> dict[str, str]:
        """surface → entity_id (the STU-435 consumer API)."""
        table: dict[str, str] = {}
        for record in self.entities:
            for alias in record.aliases:
                table[alias] = record.entity_id
        return table

    def audit_log(self) -> list[MergeDecision]:
        return sorted(self.decisions.values(), key=lambda d: d.decision_id)

    def validate(self) -> None:
        seen_ids: set[str] = set()
        owners: dict[str, str] = {}
        for record in self.entities:
            if record.entity_id in seen_ids:
                raise ValueError(f"duplicate entity_id '{record.entity_id}'")
            seen_ids.add(record.entity_id)

            if record.canonical_name not in record.aliases:
                raise ValueError(
                    "invariant 3 violated: canonical_name "
                    f"'{record.canonical_name}' not in aliases of '{record.entity_id}'"
                )
            for alias in record.aliases:
                key = alias.casefold()
                owner = owners.get(key)
                if owner is not None and owner != record.entity_id:
                    raise ValueError(
                        f"invariant 1 violated: alias '{alias}' belongs to "
                        f"both '{owner}' and '{record.entity_id}'"
                    )
                owners[key] = record.entity_id

            justified: set[str] = set()
            for d_id in record.decisions:
                decision = self.decisions.get(d_id)
                if decision is None:
                    raise ValueError(
                        f"unknown decision_id '{d_id}' on entity '{record.entity_id}'"
                    )
                justified.update(decision.inputs)
            for alias in record.aliases:
                if alias == record.canonical_name:
                    continue
                if entity_slug(alias) not in justified:
                    raise ValueError(
                        f"invariant 2 violated: alias '{alias}' of "
                        f"'{record.entity_id}' has no MergeDecision"
                    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/registry.py tests/test_registry.py
git commit -m "feat(registry): Registry core with lookup/alias_table/audit_log + invariants 1-3 (STU-441)"
```

---

### Task 3: Serialization — to_dict/from_dict/save/load round-trip

**Files:**
- Modify: `wiki_creator/registry.py` (append methods to `Registry`)
- Test: `tests/test_registry.py` (append)

**Interfaces:**
- Consumes: Task 2 `Registry` (`validate`, `audit_log`).
- Produces: `Registry.to_dict() -> dict`, `Registry.from_dict(raw: dict) -> "Registry"` (classmethod), `Registry.save(path: Path | str) -> None` (validates, then writes JSON), `Registry.load(path: Path | str) -> "Registry"` (classmethod, reads then validates). JSON shape: `{"version": 1, "entities": [...], "decisions": [...], "warnings": [...]}` — decisions stored once top-level, records reference them by id.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py`:

```python
def test_round_trip_save_load_preserves_everything(tmp_path):
    registry = _valid_registry()
    registry.entities[0].mentions.append(
        Mention(surface="Chaol", chapter_id="ch01", context="Chaol stood guard.")
    )
    registry.warnings.append("test warning")
    path = tmp_path / "registry.json"

    registry.save(path)
    loaded = Registry.load(path)

    assert loaded.to_dict() == registry.to_dict()
    assert loaded.entities[0].mentions[0] == registry.entities[0].mentions[0]
    assert loaded.decisions == registry.decisions
    assert loaded.warnings == ["test warning"]


def test_saved_json_shape(tmp_path):
    import json as jsonlib

    path = tmp_path / "registry.json"
    _valid_registry().save(path)
    raw = jsonlib.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert {e["entity_id"] for e in raw["entities"]} == {"chaol_westfall", "perrington"}
    # decisions are stored once, top-level, referenced by id from records
    top_ids = {d["decision_id"] for d in raw["decisions"]}
    for entity in raw["entities"]:
        assert set(entity["decisions"]) <= top_ids


def test_save_enforces_invariants(tmp_path):
    registry = _valid_registry()
    registry.entities[0].aliases.append("Unjustified Alias")
    with pytest.raises(ValueError, match="invariant 2"):
        registry.save(tmp_path / "registry.json")
    assert not (tmp_path / "registry.json").exists()


def test_load_rejects_corrupted_registry(tmp_path):
    import json as jsonlib

    registry = _valid_registry()
    path = tmp_path / "registry.json"
    registry.save(path)
    raw = jsonlib.loads(path.read_text(encoding="utf-8"))
    raw["entities"][0]["aliases"].append("Injected Alias")
    path.write_text(jsonlib.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="invariant 2"):
        Registry.load(path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_registry.py -v`
Expected: new tests FAIL with `AttributeError: 'Registry' object has no attribute 'save'` (or `to_dict`)

- [ ] **Step 3: Write the implementation**

Append these methods to the `Registry` class in `wiki_creator/registry.py`:

```python
    def to_dict(self) -> dict:
        return {
            "version": REGISTRY_VERSION,
            "entities": [
                {
                    "entity_id": r.entity_id,
                    "canonical_name": r.canonical_name,
                    "entity_type": r.entity_type,
                    "aliases": list(r.aliases),
                    "mentions": [asdict(m) for m in r.mentions],
                    "decisions": list(r.decisions),
                }
                for r in self.entities
            ],
            "decisions": [
                {
                    "decision_id": d.decision_id,
                    "strategy": d.strategy,
                    "inputs": list(d.inputs),
                    "evidence": d.evidence,
                    "confidence": d.confidence,
                    "reversible": d.reversible,
                }
                for d in self.audit_log()
            ],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Registry":
        decisions: dict[str, MergeDecision] = {}
        for d in raw.get("decisions") or []:
            inputs = list(d.get("inputs") or ["", ""])
            decisions[str(d["decision_id"])] = MergeDecision(
                decision_id=str(d["decision_id"]),
                strategy=str(d.get("strategy") or ""),
                inputs=(str(inputs[0]), str(inputs[1])),
                evidence=str(d.get("evidence") or ""),
                confidence=str(d.get("confidence") or ""),
                reversible=bool(d.get("reversible", True)),
            )
        entities: list[EntityRecord] = []
        for e in raw.get("entities") or []:
            entities.append(
                EntityRecord(
                    entity_id=str(e["entity_id"]),
                    canonical_name=str(e.get("canonical_name") or ""),
                    entity_type=str(e.get("entity_type") or "OTHER"),
                    aliases=[str(a) for a in e.get("aliases") or []],
                    mentions=[Mention(**m) for m in e.get("mentions") or []],
                    decisions=[str(d) for d in e.get("decisions") or []],
                )
            )
        return cls(
            entities=entities,
            decisions=decisions,
            warnings=[str(w) for w in raw.get("warnings") or []],
        )

    def save(self, path: Path | str) -> None:
        """Serialize to JSON. Invariants are verified on every save (spec §3.2)."""
        self.validate()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")

    @classmethod
    def load(cls, path: Path | str) -> "Registry":
        with open(path, encoding="utf-8") as f:
            registry = cls.from_dict(json.load(f))
        registry.validate()
        return registry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/registry.py tests/test_registry.py
git commit -m "feat(registry): registry.json serialization with invariant-checked save/load (STU-441)"
```

---

### Task 4: `Registry.from_artifacts` — read-only reconstruction

**Files:**
- Modify: `wiki_creator/registry.py` (append classmethod + private helpers)
- Test: `tests/test_registry.py` (append)

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: `Registry.from_artifacts(splits: dict | None, alias_output: dict | None, full_registries: dict | None = None) -> "Registry"` (classmethod). `full_registries` is the merged content of the `*_full.json` files (`{"entity_001": {...}}`). Module-level helpers `_mentions_from_full`, `_merge_duplicate_canonicals`, `_resolve_alias_collisions`.

**Reconstruction rules (the heart of pas 1 — implement exactly):**
1. `entity_id` = `entity_slug(canonical_name)`; on collision between *different* canonicals, deterministic suffix `_2`, `_3`, … in artifact order (invariant 4).
2. Alias provenance, per alias ≠ canonical (first match wins):
   - alias ∈ `alias_resolution.merged_from` (casefold) → strategy = recorded `method`, confidence = recorded `confidence`, evidence = joined recorded snippets;
   - alias appears (casefold) in any `splits[TYPE][*].all_mentions` (multi-entity JW cluster) → strategy `"cluster_jw"`, confidence `"medium"`;
   - else → strategy `"extraction_grouping"`, confidence `"medium"`.
   Synthesized evidence strings mention `(pas 1)` so reconstructed decisions are distinguishable in the audit log.
3. Mentions: for each `source_id`, for each chapter (sorted) and context sentence in `mentions_by_chapter`, emit one `Mention` whose `surface` is the **longest** `raw_mentions` entry found as a substring of the sentence (fallback: first raw mention, then canonical), `source="ner"`, `context=` the sentence.
4. Artifacts may violate invariant 1; resolve deterministically **before** returning so `save()` never crashes on real runs:
   - two entities with the same casefold canonical → merge the later into the first (aliases/mentions/decisions union; the absorbed exact canonical form gets an `extraction_grouping` decision if it differs);
   - alias claimed by several entities → the entity whose *canonical* it is wins; otherwise highest summed `mention_count` (from full registries) wins; ties → first in artifact order. Losers drop the alias + its now-orphaned decision ids; every resolution appends to `registry.warnings`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py`:

```python
import copy


def _run16_artifacts() -> tuple[dict, dict, dict]:
    """The Run 16 / STU-430 snippet as pipeline artifacts (Crown Prince and
    Perrington are distinct; 'Duke Perrington' is an extraction surface variant).
    Mirrors tests/test_alias_resolution.py:1248."""
    splits = {
        "singles_resolved": [],
        "PERSON": [],
        "PLACE": [],
        "ORG": [],
        "EVENT": [],
        "OTHER": [],
        "stats": {},
    }
    alias_output = {
        "entities": [
            {
                "canonical_name": "Crown Prince",
                "type": "PERSON",
                "aliases": ["Crown Prince"],
                "source_ids": ["e_crown_prince"],
                "relevant": True,
            },
            {
                "canonical_name": "Perrington",
                "type": "PERSON",
                "aliases": ["Duke Perrington", "Perrington"],
                "source_ids": ["e_perrington"],
                "relevant": True,
            },
        ],
        "narrator": None,
        "stats": {"merges_applied": 0},
    }
    persons_full = {
        "e_crown_prince": {
            "type": "PERSON",
            "raw_mentions": ["Crown Prince"],
            "first_seen": "ch02",
            "mention_count": 1,
            "mentions_by_chapter": {
                "ch02": [
                    "The Crown Prince, of course, sat with Perrington "
                    "on their own two logs, far from her.",
                ]
            },
        },
        "e_perrington": {
            "type": "PERSON",
            "raw_mentions": ["Perrington", "Duke Perrington"],
            "first_seen": "ch02",
            "mention_count": 2,
            "mentions_by_chapter": {"ch02": ["Perrington scowled at the competitors."]},
        },
    }
    return splits, alias_output, persons_full


def test_from_artifacts_run16_reconstruction():
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full)

    assert sorted(r.entity_id for r in registry.entities) == ["crown_prince", "perrington"]
    perrington = registry.lookup("Perrington")
    assert perrington.canonical_name == "Perrington"
    assert perrington.entity_type == "PERSON"
    assert "Duke Perrington" in perrington.aliases
    # invariant 3 holds by construction
    assert perrington.canonical_name in perrington.aliases
    # the whole thing is save()-able (all invariants hold)
    registry.validate()


def test_from_artifacts_entity_ids_deterministic_between_runs():
    """Invariant 4: same artifacts ⇒ byte-identical registry."""
    splits, alias_output, persons_full = _run16_artifacts()
    first = Registry.from_artifacts(
        copy.deepcopy(splits), copy.deepcopy(alias_output), copy.deepcopy(persons_full)
    )
    second = Registry.from_artifacts(
        copy.deepcopy(splits), copy.deepcopy(alias_output), copy.deepcopy(persons_full)
    )
    assert first.to_dict() == second.to_dict()


def test_from_artifacts_unclustered_alias_gets_extraction_grouping():
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    perrington = registry.lookup("Perrington")
    strategies = {registry.decisions[d].strategy for d in perrington.decisions}
    assert strategies == {"extraction_grouping"}


def test_from_artifacts_clustered_alias_gets_cluster_jw():
    splits, alias_output, persons_full = _run16_artifacts()
    splits["PERSON"].append(
        {
            "canonical_candidate": "Perrington",
            "type": "PERSON",
            "all_mentions": ["Perrington", "Duke Perrington"],
            "entity_ids": ["e_perrington", "e_duke"],
            "entity_count": 2,
        }
    )
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    perrington = registry.lookup("Perrington")
    strategies = {registry.decisions[d].strategy for d in perrington.decisions}
    assert strategies == {"cluster_jw"}


def test_from_artifacts_recorded_merge_keeps_method_and_evidence():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"][1]["aliases"] = ["Duke", "Duke Perrington", "Perrington"]
    alias_output["entities"][1]["alias_resolution"] = {
        "merged_from": ["Duke"],
        "evidence": [
            {"method": "pure_title", "confidence": "high", "snippet": "Duke Perrington scowled."}
        ],
        "confidence": "high",
        "method": "pure_title",
    }
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    perrington = registry.lookup("Perrington")
    by_alias_slug = {
        registry.decisions[d].inputs[1]: registry.decisions[d] for d in perrington.decisions
    }
    duke = by_alias_slug["duke"]
    assert duke.strategy == "pure_title"
    assert duke.confidence == "high"
    assert "Duke Perrington scowled." in duke.evidence
    # the plain surface variant still gets a synthesized decision
    assert by_alias_slug["duke_perrington"].strategy == "extraction_grouping"


def test_from_artifacts_rebuilds_mentions_with_longest_surface_match():
    splits, alias_output, persons_full = _run16_artifacts()
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    crown = registry.lookup("Crown Prince")
    assert len(crown.mentions) == 1
    mention = crown.mentions[0]
    assert mention.surface == "Crown Prince"
    assert mention.chapter_id == "ch02"
    assert mention.source == "ner"
    assert mention.start is None and mention.raw_label is None
    assert "sat with Perrington" in mention.context


def test_from_artifacts_canonical_added_to_aliases_when_missing():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"][0]["aliases"] = []  # artifact anomaly
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    crown = registry.lookup("Crown Prince")
    assert crown.aliases == ["Crown Prince"]


def test_from_artifacts_slug_collision_gets_deterministic_suffix():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"].append(
        {
            "canonical_name": "Crown-Prince",  # different name, same slug
            "type": "PERSON",
            "aliases": ["Crown-Prince"],
            "source_ids": [],
            "relevant": True,
        }
    )
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    ids = sorted(r.entity_id for r in registry.entities)
    assert ids == ["crown_prince", "crown_prince_2", "perrington"]


def test_from_artifacts_merges_duplicate_canonicals():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"].append(
        {
            "canonical_name": "Perrington",
            "type": "PERSON",
            "aliases": ["Perrington", "the duke"],
            "source_ids": [],
            "relevant": True,
        }
    )
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    assert sorted(r.entity_id for r in registry.entities) == ["crown_prince", "perrington"]
    perrington = registry.lookup("Perrington")
    assert "the duke" in perrington.aliases
    assert registry.warnings  # the resolution is traced
    registry.validate()


def test_from_artifacts_alias_collision_canonical_wins():
    splits, alias_output, persons_full = _run16_artifacts()
    # 'Crown Prince' also (wrongly) listed as alias of Perrington in the artifacts
    alias_output["entities"][1]["aliases"] = ["Crown Prince", "Duke Perrington", "Perrington"]
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    crown = registry.lookup("Crown Prince")
    perrington = [r for r in registry.entities if r.entity_id == "perrington"][0]
    assert crown.entity_id == "crown_prince"  # canonical owner keeps it
    assert "Crown Prince" not in perrington.aliases
    assert any("Crown Prince" in w for w in registry.warnings)
    registry.validate()


def test_from_artifacts_tolerates_missing_optional_inputs():
    _, alias_output, _ = _run16_artifacts()
    registry = Registry.from_artifacts(None, alias_output, None)
    assert len(registry.entities) == 2
    assert all(r.mentions == [] for r in registry.entities)
    registry.validate()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_registry.py -v`
Expected: new tests FAIL with `AttributeError: type object 'Registry' has no attribute 'from_artifacts'`

- [ ] **Step 3: Write the implementation**

Append the classmethod to `Registry` and the module-level helpers in `wiki_creator/registry.py`:

```python
    @classmethod
    def from_artifacts(
        cls,
        splits: dict | None,
        alias_output: dict | None,
        full_registries: dict | None = None,
    ) -> "Registry":
        """Rebuild the registry from existing artifacts (pas 1 — read only).

        splits: parsed splits.json (multi-entity JW clusters per type).
        alias_output: alias-resolution stage output ({"entities": [...]});
            entities_classified.json carries the same entity dicts and works too.
        full_registries: merged *_full.json registries ({"entity_001": {...}}),
            used to rebuild mentions and to break alias-collision ties.
        """
        splits = splits or {}
        full = full_registries or {}
        entities_raw = [
            e for e in (alias_output or {}).get("entities") or [] if isinstance(e, dict)
        ]

        jw_names = {
            str(name).casefold()
            for etype in ENTITY_TYPES
            for cluster in (splits.get(etype) or [])
            for name in (cluster.get("all_mentions") or [])
        }

        records: list[EntityRecord] = []
        decisions: dict[str, MergeDecision] = {}
        warnings: list[str] = []
        mention_counts: dict[str, int] = {}
        used_slugs: dict[str, int] = {}

        for raw in entities_raw:
            canonical = str(raw.get("canonical_name") or "").strip()
            if not canonical:
                warnings.append("skipped entity without canonical_name")
                continue

            slug = entity_slug(canonical)
            used_slugs[slug] = used_slugs.get(slug, 0) + 1
            entity_id = slug if used_slugs[slug] == 1 else f"{slug}_{used_slugs[slug]}"

            aliases = sorted(
                {str(a) for a in (raw.get("aliases") or []) if str(a).strip()}
                | {canonical},
                key=str.casefold,
            )
            source_ids = [str(s) for s in (raw.get("source_ids") or [])]

            recorded = raw.get("alias_resolution") or {}
            merged_from = {str(m).casefold() for m in (recorded.get("merged_from") or [])}
            method = str(recorded.get("method") or "unknown")
            method_confidence = str(recorded.get("confidence") or "medium")
            snippets = "; ".join(
                s
                for s in (
                    str(e.get("snippet") or "")
                    for e in (recorded.get("evidence") or [])
                    if isinstance(e, dict)
                )
                if s
            )

            decision_ids: list[str] = []
            for alias in aliases:
                if alias == canonical:
                    continue
                alias_slug = entity_slug(alias)
                if alias.casefold() in merged_from:
                    strategy, conf = method, method_confidence
                    evidence = snippets or (
                        f"alias-resolution merge of '{alias}' into '{canonical}'"
                    )
                elif alias.casefold() in jw_names:
                    strategy, conf = "cluster_jw", "medium"
                    evidence = (
                        f"reconstructed (pas 1) from splits cluster: "
                        f"'{alias}' co-clustered with '{canonical}'"
                    )
                else:
                    strategy, conf = "extraction_grouping", "medium"
                    evidence = (
                        f"reconstructed (pas 1) from extraction surface variants: "
                        f"'{alias}' grouped under '{canonical}'"
                    )
                d_id = _decision_id(strategy, (entity_id, alias_slug), evidence)
                decisions[d_id] = MergeDecision(
                    decision_id=d_id,
                    strategy=strategy,
                    inputs=(entity_id, alias_slug),
                    evidence=evidence,
                    confidence=conf,
                )
                if d_id not in decision_ids:
                    decision_ids.append(d_id)

            mention_counts[entity_id] = sum(
                int((full.get(sid) or {}).get("mention_count") or 0) for sid in source_ids
            )
            records.append(
                EntityRecord(
                    entity_id=entity_id,
                    canonical_name=canonical,
                    entity_type=str(raw.get("type") or "OTHER"),
                    aliases=aliases,
                    mentions=_mentions_from_full(canonical, source_ids, full),
                    decisions=decision_ids,
                )
            )

        records = _merge_duplicate_canonicals(records, decisions, mention_counts, warnings)
        _resolve_alias_collisions(records, decisions, mention_counts, warnings)
        return cls(entities=records, decisions=decisions, warnings=warnings)
```

Module-level helpers (place after the `Registry` class):

```python
def _mentions_from_full(
    canonical: str, source_ids: list[str], full: dict
) -> list[Mention]:
    """One Mention per preserved context sentence; surface = longest raw
    mention found in the sentence (offsets/raw labels were never persisted)."""
    mentions: list[Mention] = []
    for sid in source_ids:
        record = full.get(sid) or {}
        surfaces = [str(m) for m in (record.get("raw_mentions") or []) if str(m).strip()]
        by_length = sorted(surfaces, key=len, reverse=True)
        by_chapter = record.get("mentions_by_chapter") or {}
        for chapter_id in sorted(by_chapter):
            for sentence in by_chapter[chapter_id] or []:
                text = str(sentence)
                surface = next(
                    (s for s in by_length if s in text),
                    surfaces[0] if surfaces else canonical,
                )
                mentions.append(
                    Mention(
                        surface=surface,
                        chapter_id=str(chapter_id),
                        source="ner",
                        context=text,
                    )
                )
    return mentions


def _merge_duplicate_canonicals(
    records: list[EntityRecord],
    decisions: dict[str, MergeDecision],
    mention_counts: dict[str, int],
    warnings: list[str],
) -> list[EntityRecord]:
    """Artifacts occasionally carry two entities with the same canonical name;
    fold the later into the first so invariant 1 can hold (deterministic)."""
    by_canonical: dict[str, EntityRecord] = {}
    kept: list[EntityRecord] = []
    for record in records:
        key = record.canonical_name.casefold()
        first = by_canonical.get(key)
        if first is None:
            by_canonical[key] = record
            kept.append(record)
            continue
        warnings.append(
            f"duplicate canonical_name '{record.canonical_name}': "
            f"merged '{record.entity_id}' into '{first.entity_id}'"
        )
        for alias in record.aliases:
            if alias not in first.aliases:
                first.aliases.append(alias)
        first.aliases.sort(key=str.casefold)
        first.mentions.extend(record.mentions)
        for d_id in record.decisions:
            if d_id not in first.decisions:
                first.decisions.append(d_id)
        mention_counts[first.entity_id] = mention_counts.get(
            first.entity_id, 0
        ) + mention_counts.get(record.entity_id, 0)
        if record.canonical_name != first.canonical_name:
            alias_slug = entity_slug(record.canonical_name)
            evidence = (
                f"reconstructed (pas 1): duplicate canonical "
                f"'{record.canonical_name}' folded into '{first.canonical_name}'"
            )
            d_id = _decision_id(
                "extraction_grouping", (first.entity_id, alias_slug), evidence
            )
            decisions[d_id] = MergeDecision(
                decision_id=d_id,
                strategy="extraction_grouping",
                inputs=(first.entity_id, alias_slug),
                evidence=evidence,
                confidence="medium",
            )
            first.decisions.append(d_id)
    return kept


def _resolve_alias_collisions(
    records: list[EntityRecord],
    decisions: dict[str, MergeDecision],
    mention_counts: dict[str, int],
    warnings: list[str],
) -> None:
    """Invariant 1 pre-pass: an alias claimed by several entities stays with
    its canonical owner, else the highest mention_count, else artifact order."""
    claims: dict[str, list[EntityRecord]] = {}
    for record in records:
        for alias in record.aliases:
            bucket = claims.setdefault(alias.casefold(), [])
            if not bucket or bucket[-1] is not record:
                bucket.append(record)

    for key, claimants in claims.items():
        if len(claimants) < 2:
            continue
        canonical_owners = [
            r for r in claimants if r.canonical_name.casefold() == key
        ]
        if canonical_owners:
            winner = canonical_owners[0]  # unique after duplicate-canonical merge
        else:
            winner = max(claimants, key=lambda r: mention_counts.get(r.entity_id, 0))
        for loser in claimants:
            if loser is winner:
                continue
            dropped = [a for a in loser.aliases if a.casefold() == key]
            loser.aliases = [a for a in loser.aliases if a.casefold() != key]
            dropped_slugs = {entity_slug(a) for a in dropped}
            still_needed = {entity_slug(a) for a in loser.aliases}
            loser.decisions = [
                d_id
                for d_id in loser.decisions
                if decisions[d_id].inputs[1] not in dropped_slugs
                or decisions[d_id].inputs[1] in still_needed
            ]
            warnings.append(
                f"alias '{dropped[0]}' claimed by multiple entities: kept on "
                f"'{winner.entity_id}', dropped from '{loser.entity_id}'"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry.py -v`
Expected: all PASS

- [ ] **Step 5: Run mypy on the finished module**

Run: `mypy wiki_creator/`
Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add wiki_creator/registry.py tests/test_registry.py
git commit -m "feat(registry): from_artifacts read-only reconstruction with provenance + collision resolution (STU-441)"
```

---

### Task 5: `write-registry` pipeline stage + gating

**Files:**
- Create: `scripts/write_registry.py`
- Create: `.studio/contracts/write-registry.contract.yaml`
- Modify: `.studio/pipelines/wiki-resolution.pipeline.yaml` (append one stage)
- Modify: `run_wiki.py:33-36` (required_files) and `run_wiki.py:63-65` (clean_files)
- Test: `tests/test_write_registry.py`

**Interfaces:**
- Consumes: `Registry.from_artifacts`, `Registry.save` (Task 4), `wiki_creator.paths.book_paths_from_epub`.
- Produces: `processing_output/<slug>/registry.json`; stage stdout `{"registry": {"path": str, "entities": int, "decisions": int, "warnings": list[str]}}` (contract requires the `registry` field). Pure addition — no existing stage or consumer changes.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_write_registry.py`:

```python
"""Subprocess tests for scripts/write_registry.py (STU-441, write-registry stage)."""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "write_registry.py"


def _book_tree(tmp_path: Path) -> tuple[Path, Path]:
    """Minimal library layout: returns (epub_path, processing_dir)."""
    books = tmp_path / "library" / "author" / "series" / "books"
    books.mkdir(parents=True)
    epub = books / "01-book.epub"
    epub.write_bytes(b"")
    processing = tmp_path / "library" / "author" / "series" / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    return epub, processing


def _artifacts() -> tuple[dict, dict, dict]:
    splits = {
        "singles_resolved": [],
        "PERSON": [],
        "PLACE": [],
        "ORG": [],
        "EVENT": [],
        "OTHER": [],
        "stats": {},
    }
    alias_output = {
        "entities": [
            {
                "canonical_name": "Crown Prince",
                "type": "PERSON",
                "aliases": ["Crown Prince"],
                "source_ids": ["e_crown_prince"],
                "relevant": True,
            },
            {
                "canonical_name": "Perrington",
                "type": "PERSON",
                "aliases": ["Duke Perrington", "Perrington"],
                "source_ids": ["e_perrington"],
                "relevant": True,
            },
        ],
        "narrator": None,
        "stats": {"merges_applied": 0},
    }
    persons_full = {
        "e_crown_prince": {
            "type": "PERSON",
            "raw_mentions": ["Crown Prince"],
            "first_seen": "ch02",
            "mention_count": 1,
            "mentions_by_chapter": {"ch02": ["The Crown Prince sat with Perrington."]},
        },
        "e_perrington": {
            "type": "PERSON",
            "raw_mentions": ["Perrington", "Duke Perrington"],
            "first_seen": "ch02",
            "mention_count": 2,
            "mentions_by_chapter": {"ch02": ["Perrington scowled at the competitors."]},
        },
    }
    return splits, alias_output, persons_full


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def test_write_registry_writes_registry_json(tmp_path):
    epub, processing = _book_tree(tmp_path)
    splits, alias_output, persons_full = _artifacts()
    (processing / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    (processing / "persons_full.json").write_text(json.dumps(persons_full), encoding="utf-8")

    result = _run(
        {
            "additional_context": f"file_path: {epub}\n",
            "previous_outputs": {"alias-resolution": alias_output},
        }
    )
    assert result.returncode == 0, result.stderr

    out = json.loads(result.stdout)
    assert out["registry"]["entities"] == 2
    assert out["registry"]["decisions"] >= 1

    saved = json.loads((processing / "registry.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert {e["entity_id"] for e in saved["entities"]} == {"crown_prince", "perrington"}
    # mentions were rebuilt from persons_full.json
    perrington = [e for e in saved["entities"] if e["entity_id"] == "perrington"][0]
    assert perrington["mentions"][0]["chapter_id"] == "ch02"


def test_write_registry_falls_back_to_entities_classified(tmp_path):
    epub, processing = _book_tree(tmp_path)
    splits, alias_output, _ = _artifacts()
    (processing / "splits.json").write_text(json.dumps(splits), encoding="utf-8")
    (processing / "entities_classified.json").write_text(
        json.dumps(alias_output), encoding="utf-8"
    )

    result = _run({"additional_context": f"file_path: {epub}\n", "previous_outputs": {}})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["registry"]["entities"] == 2
    assert (processing / "registry.json").exists()


def test_write_registry_fails_without_file_path():
    result = _run({"additional_context": "", "previous_outputs": {}})
    assert result.returncode == 1
    assert "file_path" in json.loads(result.stdout)["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_write_registry.py -v`
Expected: FAIL — the script does not exist (`FileNotFoundError` / non-zero returncode with empty stdout)

- [ ] **Step 3: Write the stage script**

Create `scripts/write_registry.py` (modeled on `scripts/save_relationships.py`):

```python
#!/usr/bin/env python3
"""Stage: write-registry (STU-441, EntityRegistry pas 1)

Reconstruit le registre d'identité depuis les artefacts existants et écrit
processing_output/<slug>/registry.json. Lecture seule : aucun changement de
comportement du pipeline — rien ne consomme le registre avant STU-435 (pas 3).

Input (Studio stdin):
  all_stage_outputs["alias-resolution"]: output du stage alias-resolution
  (fallback : entities_classified.json sur disque, pour les runs repris)

Output (stdout): {"registry": {"path", "entities", "decisions", "warnings"}}
Disk: processing_output/<slug>/registry.json
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from wiki_creator.paths import book_paths_from_epub
from wiki_creator.registry import Registry

FULL_REGISTRY_FILES = (
    "persons_full.json",
    "places_full.json",
    "orgs_full.json",
    "events_full.json",
)


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def main() -> None:
    payload = json.load(sys.stdin)
    previous_outputs = payload.get("previous_outputs", payload.get("all_stage_outputs", {}))

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path", "")
    if not file_path:
        json.dump({"error": "missing file_path in additional_context"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    paths = book_paths_from_epub(file_path)

    alias_output = previous_outputs.get("alias-resolution") or {}
    if not alias_output.get("entities"):
        alias_output = _load_json(paths.processing / "entities_classified.json")

    splits = _load_json(paths.processing / "splits.json")
    full_registries: dict = {}
    for name in FULL_REGISTRY_FILES:
        full_registries.update(_load_json(paths.processing / name))

    registry = Registry.from_artifacts(splits, alias_output, full_registries)
    output_path = paths.processing / "registry.json"
    registry.save(output_path)

    print(
        f"[write-registry] Written {len(registry.entities)} entities, "
        f"{len(registry.decisions)} decisions to {output_path}",
        file=sys.stderr,
    )
    for warning in registry.warnings:
        print(f"[write-registry] warning: {warning}", file=sys.stderr)

    json.dump(
        {
            "registry": {
                "path": str(output_path),
                "entities": len(registry.entities),
                "decisions": len(registry.decisions),
                "warnings": registry.warnings,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_write_registry.py -v`
Expected: 3 PASS

- [ ] **Step 5: Wire the stage into the pipeline**

Create `.studio/contracts/write-registry.contract.yaml`:

```yaml
name: write-registry
version: 1
schema:
  required_fields:
    - registry
```

Append to `.studio/pipelines/wiki-resolution.pipeline.yaml` (after the `save-relationships` stage, same indentation):

```yaml
  - name: write-registry
    kind: extraction
    executor: script
    runtime: python
    script: scripts/write_registry.py
    contract: write-registry
    context:
      include:
        - input
        - all_stage_outputs
```

- [ ] **Step 6: Gate and clean the new artifact in run_wiki.py**

In `run_wiki.py`, `required_files()` — add `registry.json` to the `wiki-resolution` list:

```python
        "wiki-resolution": [
            str(p.processing / "entities_classified.json"),
            str(p.processing / "chapter_summaries.json"),
            str(p.processing / "registry.json"),
        ],
```

In `run_wiki.py`, `clean_files()` — same addition:

```python
        "wiki-resolution": [
            str(p.processing / "entities_classified.json"),
            str(p.processing / "registry.json"),
        ],
```

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: `754 passed, 31 skipped` (735 baseline + 19 new; skips unchanged). Zero failures.

Run: `mypy wiki_creator/`
Expected: `Success: no issues found`

- [ ] **Step 8: Commit**

```bash
git add scripts/write_registry.py .studio/contracts/write-registry.contract.yaml .studio/pipelines/wiki-resolution.pipeline.yaml run_wiki.py tests/test_write_registry.py
git commit -m "feat(pipeline): write-registry stage emits registry.json after wiki-resolution (STU-441)"
```

---

### Task 6: End-to-end verification

**Files:** none created — verification only.

- [ ] **Step 1: Full test suite + type check**

Run: `pytest -q && mypy wiki_creator/`
Expected: all green, no regressions.

- [ ] **Step 2: Smoke test on the committed fixture novella**

Run: `make smoke`
Expected: completes as on `main`; additionally `registry.json` now exists in the fixture's `processing_output/<slug>/` directory. If `make smoke` requires resources unavailable locally (studio CLI/provider), note it and verify instead by running `pytest tests/test_write_registry.py -v` plus a manual invocation:

```bash
python scripts/write_registry.py <<'EOF'
{"additional_context": "file_path: library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub\n", "previous_outputs": {}}
EOF
```

(uses the entities_classified.json fallback on an already-processed book, if present; skip if no processed artifacts exist locally).

- [ ] **Step 3: Inspect the produced registry.json**

Open the generated `registry.json` and spot-check: every entity has `canonical_name` in `aliases`; decisions reference real entities; warnings list looks sane (spec §3.3 benefit 1 — the file must answer "why is X an alias of Y?").

- [ ] **Step 4: Update Linear + finish the branch**

Move STU-441 to In Progress → In Review as appropriate; use superpowers:finishing-a-development-branch to decide merge/PR (PR expected, per repo flow with `Co-Authored-By` convention).

---

## Self-Review (done at planning time)

- **Spec coverage:** §3.2 model → Task 1 (with agreed Optional deviations); invariants 1–3 → Task 2; invariant 4 → Tasks 1/4 (content-derived ids + determinism test); §3.3 artifact → Tasks 3/5; §3.4 API minus `merge()` (explicitly pas 2) → Tasks 2–4; §3.5 pas 1 "pure addition" → Task 5 (append-only stage); §3.7 tests (invariants, round-trip, determinism, Run 16 reconstruction) → Tasks 2–4. Issue's "reconstruction depuis les fixtures Run 16" → `_run16_artifacts()` mirrors `tests/test_alias_resolution.py:1248`.
- **Placeholder scan:** none — every step carries complete code/commands.
- **Type consistency:** `Registry(entities, decisions, warnings)` constructor, `from_artifacts(splits, alias_output, full_registries)`, `entity_slug`, `_decision_id(strategy, inputs, evidence)` used identically across Tasks 1–5; test helper `_record_with_decision`/`_valid_registry` defined in Task 2 and reused in Task 3.
- **Test-count note:** Task 5 Step 7's expected total (754) assumes exactly 19 new tests (16 in test_registry.py + 3 in test_write_registry.py); if a task adds/renames tests, adjust the arithmetic, not the requirement (zero failures, skips unchanged).
