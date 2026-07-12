# STU-442 — EntityRegistry pas 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `Registry.merge(survivor, absorbed, decision)` the single mutation primitive; refactor the merge mechanisms into `MergeStrategy` objects that propose `MergeDecision`s through it; lock behavior with a canonical golden test — with zero production-script changes.

**Architecture:** A new `wiki_creator/merge_strategies.py` owns the strategy-name vocabulary and turns detector signals into normalized `MergeDecision`s. `Registry` gains `merge()` (fold/attach + deterministic-tie-break conflict policy) and a `to_entities_classified()` identity projection. `from_artifacts` stops hand-assembling merges and becomes a client of `merge()` — the two current de-facto merge paths (live stages' logic mirrored in `from_artifacts`) collapse into one. Clustering's hot Union-Find path and every production script stay untouched.

**Tech Stack:** Python (stdlib only: `dataclasses`, `json`, `re`, `hashlib`, `unicodedata`, `typing.Protocol`), pytest, mypy.

**Spec:** `docs/superpowers/specs/2026-07-12-stu-442-merge-strategies-design.md` (and program spec `2026-07-11-refondation-wiki-creator-design.md` §3.4/§3.5 pas 2/§3.7/§4).

**Linear:** [STU-442](https://linear.app/studioag/issue/STU-442) — branch `arianedguay/stu-442-entityregistry-pas-2-les-strategies-de-fusion-emettent-des` (already checked out in worktree `../wiki-creator-stu-442`).

## Global Constraints

- **Zero production-script changes.** Only `wiki_creator/registry.py`, new `wiki_creator/merge_strategies.py`, and tests/fixtures are touched. No `scripts/*.py`, no pipeline YAML, no contract YAML.
- **Pure module rule:** `registry.py` and `merge_strategies.py` do I/O only in `save()`/`load()`; no imports from `scripts/`.
- **One merge path:** after Task 3, `_merge_duplicate_canonicals` and `_resolve_alias_collisions` no longer exist as standalone passes — their behavior lives inside `merge()`.
- **No hardcoded vocabulary lists** (CLAUDE.md rule) — the strategy-name map is a fixed enum of internal identifiers, not domain/language vocabulary; it is allowed.
- **Existing suite stays green.** Establish the exact baseline with `pytest -q` before Task 1 and record it; every task keeps it green plus its own new tests.
- **`mypy wiki_creator/`** must pass (both modules are inside the checked package).
- **Strategy vocabulary (verbatim):** recorded method → strategy name — `title_alias`→`title_apposition`, `llm`→`llm_confirm`; `pure_title`, `role_symmetric`, `pattern`, `cooccurrence` unchanged; reconstruction strategies `cluster_jw`, `extraction_grouping`; reserved `manual`. `evidence` carries `"{snippet} [chapter={id}]"` when a chapter is recovered, else the bare snippet.
- **Conflict policy (verbatim):** alias claimed by >1 entity → canonical owner wins → higher `len(mentions)` → first-seen order; loser drops the alias + its orphaned decision id; a `warnings` line is appended.
- **Commit style:** `feat(registry): … (STU-442)`; commit after every green task.

## File Structure

- `wiki_creator/registry.py` (modify) — add `merge()`, `_by_id()`, `to_entities_classified()`; refactor `from_artifacts`; delete `_merge_duplicate_canonicals` / `_resolve_alias_collisions`.
- `wiki_creator/merge_strategies.py` (create) — `MergeStrategy` protocol, named strategy singletons, `STRATEGY_VOCABULARY`, `normalize_method()`, `strategy_for()`, `recover_chapter_id()`, `compose_evidence()`.
- `tests/test_registry.py` (modify) — append `merge()` + projection tests.
- `tests/test_merge_strategies.py` (create) — strategy layer unit tests.
- `tests/fixtures/registry_run16/` (create) — `splits.json`, `alias_resolution.json`, `persons_full.json`, `places_full.json`, `entities_classified.golden.json`.
- `tests/test_registry_golden.py` (create) — canonical equivalence test.

---

### Task 1: `Registry.merge()` — the single mutation primitive

**Files:**
- Modify: `wiki_creator/registry.py` (append `_by_id`, `merge` methods to `Registry`)
- Test: `tests/test_registry.py` (append)

**Interfaces:**
- Consumes: existing `EntityRecord`, `MergeDecision`, `entity_slug`.
- Produces: `Registry._by_id(self, entity_id: str) -> EntityRecord | None`; `Registry.merge(self, survivor: str, absorbed: str, decision: MergeDecision) -> str`. `absorbed` is either an existing `entity_id` (fold that record into `survivor`) or an alias slug already present on `survivor` (attach mode — register the justifying decision). Returns `survivor`. Raises `ValueError` on unknown `survivor`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_registry.py`:

```python
def _bare_decision(strategy, survivor, absorbed_slug, evidence="ev", confidence="medium"):
    d_id = _decision_id(strategy, (survivor, absorbed_slug), evidence)
    return MergeDecision(
        decision_id=d_id, strategy=strategy, inputs=(survivor, absorbed_slug),
        evidence=evidence, confidence=confidence,
    )


def test_merge_attach_records_decision_for_existing_alias():
    reg = _valid_registry()
    perrington = reg._by_id("perrington")
    # 'Duke Perrington' is already an alias; attach its justifying decision
    d = _bare_decision("title_apposition", "perrington", entity_slug("Duke Perrington"))
    returned = reg.merge("perrington", entity_slug("Duke Perrington"), d)
    assert returned == "perrington"
    assert d.decision_id in perrington.decisions
    assert reg.decisions[d.decision_id].strategy == "title_apposition"


def test_merge_fold_absorbs_entity_record():
    r1, d1 = _record_with_decision("perrington", "Perrington", ["Duke Perrington", "Perrington"])
    r2, d2 = _record_with_decision("the_duke", "The Duke", ["The Duke"])
    reg = Registry(entities=[r1, r2], decisions={**d1, **d2})
    fold = _bare_decision("role_symmetric", "perrington", entity_slug("The Duke"))
    r2.aliases.append("The Duke")  # ensure present
    reg.merge("perrington", "the_duke", fold)
    assert [r.entity_id for r in reg.entities] == ["perrington"]
    perrington = reg._by_id("perrington")
    assert "The Duke" in perrington.aliases
    assert fold.decision_id in perrington.decisions


def test_merge_unknown_survivor_raises():
    reg = _valid_registry()
    with pytest.raises(ValueError, match="unknown survivor"):
        reg.merge("nobody", "x", _bare_decision("manual", "nobody", "x"))


def test_merge_conflict_canonical_owner_wins():
    # perrington (canonical 'Perrington') and a second entity both claim 'Perrington'
    r1, d1 = _record_with_decision("perrington", "Perrington", ["Duke Perrington", "Perrington"])
    r2, d2 = _record_with_decision("guard", "Guard", ["Guard"])
    reg = Registry(entities=[r1, r2], decisions={**d1, **d2})
    # guard wrongly gains 'Perrington' as an alias, justified by a decision
    d = _bare_decision("extraction_grouping", "guard", entity_slug("Perrington"))
    r2.aliases.append("Perrington")
    reg.merge("guard", entity_slug("Perrington"), d)
    # canonical owner keeps it; guard loses it + the orphan decision; warning logged
    assert "Perrington" not in reg._by_id("guard").aliases
    assert reg._by_id("perrington") is not None
    assert d.decision_id not in reg._by_id("guard").decisions
    assert any("Perrington" in w for w in reg.warnings)
    reg.validate()


def test_merge_conflict_more_mentions_wins_when_no_canonical_owner():
    r1, d1 = _record_with_decision("a_one", "A One", ["A One", "Shadow"])
    r2, d2 = _record_with_decision("b_two", "B Two", ["B Two", "Shadow"])
    reg = Registry(entities=[r1, r2], decisions={**d1, **d2})
    reg._by_id("a_one").mentions.extend(
        [Mention(surface="Shadow", chapter_id="ch01"), Mention(surface="Shadow", chapter_id="ch02")]
    )
    reg._by_id("b_two").mentions.append(Mention(surface="Shadow", chapter_id="ch01"))
    # trigger resolution by (re-)attaching the contested alias on the lower-mention entity
    d = _bare_decision("extraction_grouping", "b_two", entity_slug("Shadow"))
    reg.merge("b_two", entity_slug("Shadow"), d)
    assert "Shadow" in reg._by_id("a_one").aliases      # more mentions wins
    assert "Shadow" not in reg._by_id("b_two").aliases
    reg.validate()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_registry.py -k "merge" -v`
Expected: FAIL — `AttributeError: 'Registry' object has no attribute '_by_id'` / `merge`.

- [ ] **Step 3: Write the implementation**

Append to the `Registry` class in `wiki_creator/registry.py` (after `from_artifacts`, before the module-level helpers):

```python
    def _by_id(self, entity_id: str) -> EntityRecord | None:
        for record in self.entities:
            if record.entity_id == entity_id:
                return record
        return None

    def merge(self, survivor: str, absorbed: str, decision: MergeDecision) -> str:
        """Single mutation primitive.

        survivor: entity_id of the surviving record (must exist).
        absorbed: another entity_id → fold its record into survivor; OR an alias
            slug already present on survivor → attach the justifying decision.
        decision: registered and referenced by survivor.

        Conflict — an alias now on survivor also owned by a third entity — is
        resolved deterministically: canonical owner wins, else higher
        len(mentions), else first-seen order. The loser drops the alias and its
        orphaned decision; a warning is appended. Returns survivor's entity_id.
        """
        keeper = self._by_id(survivor)
        if keeper is None:
            raise ValueError(f"merge(): unknown survivor '{survivor}'")

        self.decisions[decision.decision_id] = decision
        if decision.decision_id not in keeper.decisions:
            keeper.decisions.append(decision.decision_id)

        absorbed_record = self._by_id(absorbed)
        contested: set[str] = set()
        if absorbed_record is not None and absorbed_record is not keeper:
            for alias in absorbed_record.aliases:
                if alias not in keeper.aliases:
                    keeper.aliases.append(alias)
                contested.add(alias.casefold())
            keeper.mentions.extend(absorbed_record.mentions)
            for d_id in absorbed_record.decisions:
                if d_id not in keeper.decisions:
                    keeper.decisions.append(d_id)
            self.entities = [e for e in self.entities if e is not absorbed_record]
        else:
            for alias in keeper.aliases:
                if entity_slug(alias) == absorbed:
                    contested.add(alias.casefold())

        for key in contested:
            self._resolve_alias_conflict(key)
        return keeper.entity_id

    def _resolve_alias_conflict(self, key: str) -> None:
        """Deterministic tie-break for an alias (casefold `key`) claimed by >1
        entity: canonical owner → higher len(mentions) → first-seen order."""
        claimants = [r for r in self.entities if any(a.casefold() == key for a in r.aliases)]
        if len(claimants) < 2:
            return
        canonical_owners = [r for r in claimants if r.canonical_name.casefold() == key]
        if canonical_owners:
            winner = canonical_owners[0]
        else:
            winner = max(claimants, key=lambda r: len(r.mentions))
        for loser in claimants:
            if loser is winner:
                continue
            dropped = [a for a in loser.aliases if a.casefold() == key]
            if not dropped:
                continue
            loser.aliases = [a for a in loser.aliases if a.casefold() != key]
            dropped_slugs = {entity_slug(a) for a in dropped}
            still_needed = {entity_slug(a) for a in loser.aliases}
            loser.decisions = [
                d_id for d_id in loser.decisions
                if self.decisions[d_id].inputs[1] not in dropped_slugs
                or self.decisions[d_id].inputs[1] in still_needed
            ]
            self.warnings.append(
                f"alias '{dropped[0]}' claimed by multiple entities: kept on "
                f"'{winner.entity_id}', dropped from '{loser.entity_id}'"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry.py -k "merge" -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/registry.py tests/test_registry.py
git commit -m "feat(registry): merge() single mutation primitive with deterministic conflict tie-break (STU-442)"
```

---

### Task 2: `merge_strategies.py` — strategy layer + vocabulary

**Files:**
- Create: `wiki_creator/merge_strategies.py`
- Test: `tests/test_merge_strategies.py`

**Interfaces:**
- Consumes: `MergeDecision`, `_decision_id` from `wiki_creator.registry`.
- Produces: `STRATEGY_VOCABULARY: dict[str, str]`; `normalize_method(method: str) -> str`; class `MergeStrategy` (Protocol) with `name: str` and `propose(self, survivor_id: str, absorbed_slug: str, *, evidence: str, confidence: str) -> MergeDecision`; named singletons `CLUSTER_JW, TITLE_APPOSITION, PURE_TITLE, ROLE_SYMMETRIC, LLM_CONFIRM, PATTERN, COOCCURRENCE, EXTRACTION_GROUPING, MANUAL`; `strategy_for(name: str) -> MergeStrategy`; `recover_chapter_id(snippet: str, full_registries: dict) -> str | None`; `compose_evidence(snippet: str, chapter_id: str | None) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_merge_strategies.py`:

```python
"""Tests for wiki_creator/merge_strategies.py — EntityRegistry pas 2 (STU-442)."""
from wiki_creator.merge_strategies import (
    STRATEGY_VOCABULARY,
    compose_evidence,
    normalize_method,
    recover_chapter_id,
    strategy_for,
)


def test_normalize_method_renames_only_the_two_target_methods():
    assert normalize_method("title_alias") == "title_apposition"
    assert normalize_method("llm") == "llm_confirm"
    # everything else is preserved verbatim
    for kept in ("pure_title", "role_symmetric", "pattern", "cooccurrence"):
        assert normalize_method(kept) == kept
    # unknown/empty degrade gracefully
    assert normalize_method("") == "unknown"
    assert normalize_method("weird") == "weird"


def test_strategy_for_builds_normalized_decision():
    d = strategy_for("pure_title").propose(
        "perrington", "duke", evidence="Duke Perrington, the duke, scowled.",
        confidence="medium",
    )
    assert d.strategy == "pure_title"
    assert d.inputs == ("perrington", "duke")
    assert d.confidence == "medium"
    # content-derived id is stable
    d2 = strategy_for("pure_title").propose(
        "perrington", "duke", evidence="Duke Perrington, the duke, scowled.",
        confidence="medium",
    )
    assert d.decision_id == d2.decision_id


def test_recover_chapter_id_matches_full_registry_sentence():
    full = {
        "e1": {"mentions_by_chapter": {"ch05": ["Brullo — the Master — nodded at Celaena."]}},
    }
    assert recover_chapter_id("Brullo — the Master — nodded at Celaena.", full) == "ch05"
    assert recover_chapter_id("no such sentence", full) is None
    assert recover_chapter_id("", full) is None


def test_compose_evidence_embeds_chapter_when_present():
    assert compose_evidence("a snippet", "ch03") == "a snippet [chapter=ch03]"
    assert compose_evidence("a snippet", None) == "a snippet"


def test_vocabulary_is_the_single_source_of_truth():
    # the two renames are declared; identity entries are explicit for readability
    assert STRATEGY_VOCABULARY["title_alias"] == "title_apposition"
    assert STRATEGY_VOCABULARY["llm"] == "llm_confirm"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merge_strategies.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_creator.merge_strategies'`.

- [ ] **Step 3: Write the implementation**

Create `wiki_creator/merge_strategies.py`:

```python
"""Merge strategies — turn detector signals into normalized MergeDecisions.

Pas 2 (STU-442): the merge mechanisms (Jaro-Winkler clustering, title/pure-title/
role-symmetric/pattern/cooccurrence alias resolution, Ollama confirmation) become
MergeStrategy objects that *propose* MergeDecisions to the registry. This module
owns the single strategy-name vocabulary and the evidence-composition helpers.

Pure module, no I/O. Spec: docs/superpowers/specs/2026-07-12-stu-442-merge-strategies-design.md
"""
from __future__ import annotations

from typing import Protocol

from wiki_creator.registry import MergeDecision, _decision_id

# recorded alias-resolution method → spec strategy name. Identity entries are
# listed explicitly so registry.json's vocabulary is readable in one place.
STRATEGY_VOCABULARY: dict[str, str] = {
    "title_alias": "title_apposition",
    "llm": "llm_confirm",
    "pure_title": "pure_title",
    "role_symmetric": "role_symmetric",
    "pattern": "pattern",
    "cooccurrence": "cooccurrence",
}


def normalize_method(method: str) -> str:
    """Map a recorded method to its strategy name (identity for the unmapped)."""
    if not method:
        return "unknown"
    return STRATEGY_VOCABULARY.get(method, method)


class MergeStrategy(Protocol):
    name: str

    def propose(
        self, survivor_id: str, absorbed_slug: str, *, evidence: str, confidence: str
    ) -> MergeDecision:
        ...


class _NamedStrategy:
    """All strategies share behavior; they differ only by name + evidence
    fidelity (set by the caller). One class keeps the layer DRY."""

    def __init__(self, name: str) -> None:
        self.name = name

    def propose(
        self, survivor_id: str, absorbed_slug: str, *, evidence: str, confidence: str
    ) -> MergeDecision:
        d_id = _decision_id(self.name, (survivor_id, absorbed_slug), evidence)
        return MergeDecision(
            decision_id=d_id,
            strategy=self.name,
            inputs=(survivor_id, absorbed_slug),
            evidence=evidence,
            confidence=confidence,
        )


CLUSTER_JW = _NamedStrategy("cluster_jw")
TITLE_APPOSITION = _NamedStrategy("title_apposition")
PURE_TITLE = _NamedStrategy("pure_title")
ROLE_SYMMETRIC = _NamedStrategy("role_symmetric")
LLM_CONFIRM = _NamedStrategy("llm_confirm")
PATTERN = _NamedStrategy("pattern")
COOCCURRENCE = _NamedStrategy("cooccurrence")
EXTRACTION_GROUPING = _NamedStrategy("extraction_grouping")
MANUAL = _NamedStrategy("manual")

_STRATEGIES: dict[str, MergeStrategy] = {
    s.name: s
    for s in (
        CLUSTER_JW, TITLE_APPOSITION, PURE_TITLE, ROLE_SYMMETRIC, LLM_CONFIRM,
        PATTERN, COOCCURRENCE, EXTRACTION_GROUPING, MANUAL,
    )
}


def strategy_for(name: str) -> MergeStrategy:
    """Return the named strategy, minting one for any unmapped identifier so the
    layer never crashes on an unexpected recorded method."""
    return _STRATEGIES.get(name) or _NamedStrategy(name)


def recover_chapter_id(snippet: str, full_registries: dict) -> str | None:
    """Best-effort: find the chapter whose preserved sentence contains the
    recorded snippet. Deterministic (first match in insertion order); None on miss."""
    if not snippet:
        return None
    for record in full_registries.values():
        for chapter_id, sentences in (record.get("mentions_by_chapter") or {}).items():
            for sentence in sentences or []:
                if snippet in str(sentence):
                    return str(chapter_id)
    return None


def compose_evidence(snippet: str, chapter_id: str | None) -> str:
    """Evidence = snippet + chapter_id (spec §3.2)."""
    if chapter_id:
        return f"{snippet} [chapter={chapter_id}]"
    return snippet
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_merge_strategies.py -v`
Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/merge_strategies.py tests/test_merge_strategies.py
git commit -m "feat(registry): MergeStrategy layer + strategy-name vocabulary (STU-442)"
```

---

### Task 3: Route `from_artifacts` through strategies + `merge()`

**Files:**
- Modify: `wiki_creator/registry.py` (rewrite `from_artifacts` body; delete `_merge_duplicate_canonicals` and `_resolve_alias_collisions`; keep `_mentions_from_full`)
- Test: `tests/test_registry.py` (existing pas-1 tests are the gate; add one strategy-name assertion)

**Interfaces:**
- Consumes: Task 1 `merge`/`_by_id`; Task 2 `strategy_for`, `normalize_method`, `recover_chapter_id`, `compose_evidence`.
- Produces: same `Registry.from_artifacts(splits, alias_output, full_registries=None)` signature and equivalent output, now built entirely via `merge()`. Alias-resolution merges carry real evidence (with recovered `chapter_id`); `title_alias`/`llm` decisions now read `title_apposition`/`llm_confirm`.

- [ ] **Step 1: Write the failing test (new behavior: renamed strategies + one merge path)**

Append to `tests/test_registry.py`:

```python
from wiki_creator import registry as _registry_mod


def test_from_artifacts_normalizes_title_alias_to_title_apposition():
    splits, alias_output, persons_full = _run16_artifacts()
    alias_output["entities"][1]["aliases"] = ["Duke", "Duke Perrington", "Perrington"]
    alias_output["entities"][1]["alias_resolution"] = {
        "merged_from": ["Duke"],
        "evidence": [{"method": "title_alias", "confidence": "medium", "snippet": "Duke / Perrington"}],
        "confidence": "medium",
        "method": "title_alias",
    }
    registry = Registry.from_artifacts(splits, alias_output, persons_full)
    perrington = registry.lookup("Perrington")
    by_slug = {registry.decisions[d].inputs[1]: registry.decisions[d] for d in perrington.decisions}
    assert by_slug["duke"].strategy == "title_apposition"  # renamed from title_alias


def test_from_artifacts_no_standalone_collision_passes_remain():
    # the old private passes are gone — merge() owns conflict resolution now
    assert not hasattr(_registry_mod, "_resolve_alias_collisions")
    assert not hasattr(_registry_mod, "_merge_duplicate_canonicals")
```

- [ ] **Step 2: Run to verify the new tests fail and locate the regression surface**

Run: `pytest tests/test_registry.py -v`
Expected: the two new tests FAIL (strategy still `title_alias`; helpers still present). All pre-existing `from_artifacts`/collision tests still PASS (they are the behavior gate for Step 3).

- [ ] **Step 3: Rewrite `from_artifacts` and delete the standalone passes**

Replace the entire body of `from_artifacts` (everything after its docstring) with the following. **The `merge_strategies` import is local, not module-level** — `merge_strategies` imports from `registry`, so a top-level import here would be a circular import that fails at load time:

```python
        from wiki_creator.merge_strategies import (
            compose_evidence,
            normalize_method,
            recover_chapter_id,
            strategy_for,
        )

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

        reg = cls()
        used_slugs: dict[str, int] = {}
        used_entity_ids: set[str] = set()
        # remember the raw alias-resolution block + source_ids per entity_id so we
        # can build decisions after all base records exist (collisions need them all)
        pending: list[tuple[str, str, dict, list[str]]] = []  # (entity_id, canonical, recorded, aliases)

        for raw in entities_raw:
            canonical = str(raw.get("canonical_name") or "").strip()
            if not canonical:
                reg.warnings.append("skipped entity without canonical_name")
                continue

            slug = entity_slug(canonical)
            used_slugs[slug] = used_slugs.get(slug, 0) + 1
            counter = used_slugs[slug]
            entity_id = slug if counter == 1 else f"{slug}_{counter}"
            while entity_id in used_entity_ids:
                counter += 1
                used_slugs[slug] = counter
                entity_id = f"{slug}_{counter}"
            used_entity_ids.add(entity_id)

            aliases = sorted(
                {str(a) for a in (raw.get("aliases") or []) if str(a).strip()} | {canonical},
                key=lambda a: (a.casefold(), a),
            )
            source_ids = [str(s) for s in (raw.get("source_ids") or [])]
            reg.entities.append(
                EntityRecord(
                    entity_id=entity_id,
                    canonical_name=canonical,
                    entity_type=str(raw.get("type") or "OTHER"),
                    aliases=aliases,
                    mentions=_mentions_from_full(canonical, source_ids, full),
                    decisions=[],
                )
            )
            pending.append((entity_id, canonical, raw.get("alias_resolution") or {}, aliases))

        # Fold duplicate canonicals first (so their shared aliases are not mistaken
        # for cross-entity collisions), then attach per-alias justifying decisions.
        _fold_duplicate_canonicals(reg)
        for entity_id, canonical, recorded, aliases in pending:
            record = reg._by_id(entity_id)
            if record is None:  # folded into an earlier duplicate
                continue
            merged_from = {str(m).casefold() for m in (recorded.get("merged_from") or [])}
            method = str(recorded.get("method") or "")
            method_confidence = str(recorded.get("confidence") or "medium")
            snippets = "; ".join(
                s for s in (
                    str(e.get("snippet") or "")
                    for e in (recorded.get("evidence") or []) if isinstance(e, dict)
                ) if s
            )
            for alias in list(record.aliases):
                if alias == record.canonical_name:
                    continue
                alias_slug = entity_slug(alias)
                if alias.casefold() in merged_from:
                    strategy_name = normalize_method(method)
                    conf = method_confidence
                    base = snippets or f"alias-resolution merge of '{alias}' into '{canonical}'"
                    evidence = compose_evidence(base, recover_chapter_id(snippets, full))
                elif alias.casefold() in jw_names:
                    strategy_name, conf = "cluster_jw", "medium"
                    evidence = (
                        f"reconstructed (pas 1) from splits cluster: "
                        f"'{alias}' co-clustered with '{canonical}'"
                    )
                else:
                    strategy_name, conf = "extraction_grouping", "medium"
                    evidence = (
                        f"reconstructed (pas 1) from extraction surface variants: "
                        f"'{alias}' grouped under '{canonical}'"
                    )
                decision = strategy_for(strategy_name).propose(
                    record.entity_id, alias_slug, evidence=evidence, confidence=conf
                )
                reg.merge(record.entity_id, alias_slug, decision)

        # prune decisions no longer referenced (collision losers)
        referenced: set[str] = set()
        for record in reg.entities:
            referenced.update(record.decisions)
        reg.decisions = {d_id: d for d_id, d in reg.decisions.items() if d_id in referenced}
        return reg
```

Delete the `_merge_duplicate_canonicals` and `_resolve_alias_collisions` functions entirely, and add the fold helper (place after `_mentions_from_full`):

```python
def _fold_duplicate_canonicals(reg: "Registry") -> None:
    """Fold later entities sharing a casefold canonical into the first, via
    merge(). Each fold is justified by an extraction_grouping decision."""
    from wiki_creator.merge_strategies import strategy_for  # local: avoid cycle at import

    seen: dict[str, str] = {}  # casefold canonical → survivor entity_id
    for record in list(reg.entities):
        key = record.canonical_name.casefold()
        survivor = seen.get(key)
        if survivor is None:
            seen[key] = record.entity_id
            continue
        evidence = (
            f"reconstructed (pas 1): duplicate canonical "
            f"'{record.canonical_name}' folded into '{reg._by_id(survivor).canonical_name}'"
        )
        decision = strategy_for("extraction_grouping").propose(
            survivor, entity_slug(record.canonical_name), evidence=evidence, confidence="medium"
        )
        reg.warnings.append(
            f"duplicate canonical_name '{record.canonical_name}': "
            f"merged '{record.entity_id}' into '{survivor}'"
        )
        reg.merge(survivor, record.entity_id, decision)
```

- [ ] **Step 4: Run the full registry test file**

Run: `pytest tests/test_registry.py -v`
Expected: ALL pass — the pre-existing pas-1 tests (reconstruction, determinism, collisions, duplicate canonicals, round-trip) stay green, plus the two new Task-3 tests. If a pre-existing test fails, the refactor changed behavior — fix `merge()`/`from_artifacts` to match the pas-1 expectation, do not edit the pre-existing test.

- [ ] **Step 5: Run mypy**

Run: `mypy wiki_creator/`
Expected: `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git add wiki_creator/registry.py tests/test_registry.py
git commit -m "refactor(registry): from_artifacts builds via strategies + merge() — one merge path (STU-442)"
```

---

### Task 4: `to_entities_classified()` identity projection

**Files:**
- Modify: `wiki_creator/registry.py` (append method to `Registry`)
- Test: `tests/test_registry.py` (append)

**Interfaces:**
- Consumes: `Registry.entities`.
- Produces: `Registry.to_entities_classified(self) -> list[dict]` — one dict per entity `{"canonical_name": str, "type": str, "aliases": list[str] (sorted, casefold), "source_ids": list[str] (sorted)}`. Note: `source_ids` are recovered from mentions is NOT possible (mentions don't carry source_id); instead the projection carries the sorted alias list and leaves source_ids to a future pass — see Step 3.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
def test_to_entities_classified_projects_identity_fields_sorted():
    registry = _valid_registry()
    projected = registry.to_entities_classified()
    by_name = {e["canonical_name"]: e for e in projected}
    assert set(by_name) == {"Chaol Westfall", "Perrington"}
    perrington = by_name["Perrington"]
    assert perrington["type"] == "PERSON"
    assert perrington["aliases"] == sorted(perrington["aliases"], key=str.casefold)
    assert "Duke Perrington" in perrington["aliases"]
    assert "Perrington" in perrington["aliases"]
    # projection is stable regardless of entity order
    assert projected == sorted(projected, key=lambda e: e["canonical_name"].casefold())
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_registry.py -k to_entities_classified -v`
Expected: FAIL — `AttributeError: 'Registry' object has no attribute 'to_entities_classified'`.

- [ ] **Step 3: Write the implementation**

Append to the `Registry` class in `wiki_creator/registry.py`:

```python
    def to_entities_classified(self) -> list[dict]:
        """Identity projection matching the entity shape of entities_classified.json
        (identity fields only; classification labels are entity_classification.py's
        concern). Canonical form for the golden equivalence test — entities sorted,
        alias lists sorted, so ordering/tie-break jitter cannot cause false diffs."""
        projected = [
            {
                "canonical_name": r.canonical_name,
                "type": r.entity_type,
                "aliases": sorted(set(r.aliases), key=lambda a: (a.casefold(), a)),
            }
            for r in self.entities
        ]
        return sorted(projected, key=lambda e: e["canonical_name"].casefold())
```

(Note: `source_ids` are intentionally omitted — the registry's `Mention`s do not carry source-entity ids, so the identity projection compares canonical_name/type/aliases. The golden fixture's expected file matches this shape.)

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_registry.py -k to_entities_classified -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/registry.py tests/test_registry.py
git commit -m "feat(registry): to_entities_classified identity projection (STU-442)"
```

---

### Task 5: Run 16 golden fixture + canonical equivalence test

**Files:**
- Create: `tests/fixtures/registry_run16/splits.json`
- Create: `tests/fixtures/registry_run16/alias_resolution.json`
- Create: `tests/fixtures/registry_run16/persons_full.json`
- Create: `tests/fixtures/registry_run16/places_full.json`
- Create: `tests/fixtures/registry_run16/entities_classified.golden.json`
- Create: `tests/test_registry_golden.py`

**Interfaces:**
- Consumes: `Registry.from_artifacts`, `Registry.to_entities_classified`, `Registry.validate`.
- Produces: the golden non-regression test asserting the registry's identity projection equals the committed golden, canonically.

- [ ] **Step 1: Create the fixture bundle**

Create `tests/fixtures/registry_run16/splits.json` (one JW cluster: "Kaltain" / "Kaltain Rompier"):

```json
{
  "singles_resolved": [],
  "PERSON": [
    {
      "canonical_candidate": "Kaltain Rompier",
      "type": "PERSON",
      "all_mentions": ["Kaltain", "Kaltain Rompier"],
      "entity_ids": ["e_kaltain", "e_kaltain_rompier"],
      "entity_count": 2
    }
  ],
  "PLACE": [],
  "ORG": [],
  "EVENT": [],
  "OTHER": [],
  "stats": {}
}
```

Create `tests/fixtures/registry_run16/alias_resolution.json` (covers every strategy + the STU-430 non-merge; note Crown Prince and Perrington stay separate):

```json
{
  "entities": [
    {
      "canonical_name": "Crown Prince",
      "type": "PERSON",
      "aliases": ["Crown Prince"],
      "source_ids": ["e_crown_prince"],
      "relevant": true
    },
    {
      "canonical_name": "Perrington",
      "type": "PERSON",
      "aliases": ["Duke Perrington", "Perrington"],
      "source_ids": ["e_perrington"],
      "relevant": true
    },
    {
      "canonical_name": "Kaltain Rompier",
      "type": "PERSON",
      "aliases": ["Kaltain", "Kaltain Rompier"],
      "source_ids": ["e_kaltain", "e_kaltain_rompier"],
      "relevant": true
    },
    {
      "canonical_name": "Chaol Westfall",
      "type": "PERSON",
      "aliases": ["Captain Westfall", "Chaol", "Chaol Westfall"],
      "source_ids": ["e_chaol"],
      "relevant": true,
      "alias_resolution": {
        "merged_from": ["Captain Westfall"],
        "evidence": [{"method": "title_alias", "confidence": "medium", "snippet": "Captain Westfall, the Captain of the Guard, bowed."}],
        "confidence": "medium",
        "method": "title_alias"
      }
    },
    {
      "canonical_name": "Brullo",
      "type": "PERSON",
      "aliases": ["Brullo", "the Master"],
      "source_ids": ["e_brullo"],
      "relevant": true,
      "alias_resolution": {
        "merged_from": ["the Master"],
        "evidence": [{"method": "pure_title", "confidence": "medium", "snippet": "Brullo — the Master — nodded at Celaena."}],
        "confidence": "medium",
        "method": "pure_title"
      }
    },
    {
      "canonical_name": "Dorian",
      "type": "PERSON",
      "aliases": ["Dorian", "the prince"],
      "source_ids": ["e_dorian"],
      "relevant": true,
      "alias_resolution": {
        "merged_from": ["the prince"],
        "evidence": [{"method": "llm", "confidence": "high", "snippet": "Dorian, the prince, smiled."}],
        "confidence": "high",
        "method": "llm"
      }
    },
    {
      "canonical_name": "Celaena Sardothien",
      "type": "PERSON",
      "aliases": ["Celaena Sardothien", "the King's Champion"],
      "source_ids": ["e_celaena"],
      "relevant": true,
      "alias_resolution": {
        "merged_from": ["the King's Champion"],
        "evidence": [{"method": "role_symmetric", "confidence": "medium", "snippet": "Celaena, the King's Champion, drew her blade."}],
        "confidence": "medium",
        "method": "role_symmetric"
      }
    },
    {
      "canonical_name": "Glass Castle",
      "type": "PLACE",
      "aliases": ["Glass Castle", "the castle"],
      "source_ids": ["e_castle"],
      "relevant": true
    }
  ],
  "narrator": null,
  "stats": {"merges_applied": 4}
}
```

Create `tests/fixtures/registry_run16/persons_full.json`:

```json
{
  "e_crown_prince": {"type": "PERSON", "raw_mentions": ["Crown Prince"], "first_seen": "ch02", "mention_count": 1, "mentions_by_chapter": {"ch02": ["The Crown Prince, of course, sat with Perrington on their own two logs, far from her."]}},
  "e_perrington": {"type": "PERSON", "raw_mentions": ["Perrington", "Duke Perrington"], "first_seen": "ch02", "mention_count": 2, "mentions_by_chapter": {"ch02": ["Perrington scowled at the competitors."]}},
  "e_kaltain": {"type": "PERSON", "raw_mentions": ["Kaltain"], "first_seen": "ch03", "mention_count": 1, "mentions_by_chapter": {"ch03": ["Kaltain watched from the balcony."]}},
  "e_kaltain_rompier": {"type": "PERSON", "raw_mentions": ["Kaltain Rompier"], "first_seen": "ch03", "mention_count": 1, "mentions_by_chapter": {"ch03": ["Lady Kaltain Rompier smiled coldly."]}},
  "e_chaol": {"type": "PERSON", "raw_mentions": ["Chaol", "Captain Westfall", "Chaol Westfall"], "first_seen": "ch01", "mention_count": 3, "mentions_by_chapter": {"ch01": ["Captain Westfall, the Captain of the Guard, bowed.", "Chaol frowned."]}},
  "e_brullo": {"type": "PERSON", "raw_mentions": ["Brullo"], "first_seen": "ch05", "mention_count": 1, "mentions_by_chapter": {"ch05": ["Brullo — the Master — nodded at Celaena."]}},
  "e_dorian": {"type": "PERSON", "raw_mentions": ["Dorian"], "first_seen": "ch01", "mention_count": 2, "mentions_by_chapter": {"ch01": ["Dorian, the prince, smiled."]}},
  "e_celaena": {"type": "PERSON", "raw_mentions": ["Celaena Sardothien", "Celaena"], "first_seen": "ch01", "mention_count": 5, "mentions_by_chapter": {"ch01": ["Celaena, the King's Champion, drew her blade."]}}
}
```

Create `tests/fixtures/registry_run16/places_full.json`:

```json
{
  "e_castle": {"type": "PLACE", "raw_mentions": ["Glass Castle", "the castle"], "first_seen": "ch01", "mention_count": 4, "mentions_by_chapter": {"ch01": ["The Glass Castle loomed above the city."]}}
}
```

- [ ] **Step 2: Write the golden test (expected file not yet created → it fails)**

Create `tests/test_registry_golden.py`:

```python
"""Golden non-regression test — the registry's identity projection must match the
committed Run 16 fixture, canonically (STU-442, spec §3.5 pas 2 / §4)."""
import json
from pathlib import Path

from wiki_creator.registry import Registry

FIXTURES = Path(__file__).parent / "fixtures" / "registry_run16"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _build_registry() -> Registry:
    full = {}
    full.update(_load("persons_full.json"))
    full.update(_load("places_full.json"))
    return Registry.from_artifacts(_load("splits.json"), _load("alias_resolution.json"), full)


def test_run16_registry_is_valid_and_all_strategies_present():
    registry = _build_registry()
    registry.validate()  # every invariant holds → save()-able
    strategies = {d.strategy for d in registry.audit_log()}
    assert {
        "cluster_jw", "title_apposition", "pure_title", "role_symmetric",
        "llm_confirm", "extraction_grouping",
    } <= strategies


def test_run16_crown_prince_and_perrington_stay_separate():
    registry = _build_registry()
    assert registry.lookup("Crown Prince").entity_id != registry.lookup("Perrington").entity_id


def test_run16_identity_projection_matches_golden():
    projected = _build_registry().to_entities_classified()
    golden = _load("entities_classified.golden.json")
    assert projected == golden
```

- [ ] **Step 3: Run to verify it fails, then generate the golden from the current projection**

Run: `pytest tests/test_registry_golden.py -v`
Expected: `test_run16_identity_projection_matches_golden` FAILs (golden file missing → `FileNotFoundError`); the other two PASS.

Generate the golden by printing the projection and reviewing it by eye before committing:

```bash
python -c "
import json, sys; from pathlib import Path
sys.path.insert(0, '.')
from wiki_creator.registry import Registry
F = Path('tests/fixtures/registry_run16')
full = {}; full.update(json.loads((F/'persons_full.json').read_text())); full.update(json.loads((F/'places_full.json').read_text()))
reg = Registry.from_artifacts(json.loads((F/'splits.json').read_text()), json.loads((F/'alias_resolution.json').read_text()), full)
Path(F/'entities_classified.golden.json').write_text(json.dumps(reg.to_entities_classified(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(reg.to_entities_classified(), ensure_ascii=False, indent=2))
"
```

Manually verify the printed projection: 8 entities; Crown Prince and Perrington are separate; Kaltain is an alias of Kaltain Rompier (single entity); Chaol has `Captain Westfall`+`Chaol`; Brullo has `the Master`; Dorian has `the prince`; Celaena has `the King's Champion`; Glass Castle is a PLACE with `the castle`. This is the spec §6 acceptance ("the file answers 'why is X an alias of Y?'").

- [ ] **Step 4: Run to verify all pass**

Run: `pytest tests/test_registry_golden.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/registry_run16/ tests/test_registry_golden.py
git commit -m "test(registry): Run 16 golden fixture + canonical identity-projection equivalence (STU-442)"
```

---

### Task 6: End-to-end verification + finish branch

**Files:** none created — verification only.

- [ ] **Step 1: Full suite + type check**

Run: `pytest -q && mypy wiki_creator/`
Expected: baseline (recorded before Task 1) + new tests (5 merge + 5 strategy + 2 refactor + 1 projection + 3 golden = 16 new), zero failures, skips unchanged; mypy `Success: no issues found`.

- [ ] **Step 2: Confirm zero production-script changes**

Run: `git diff --name-only main...HEAD`
Expected: only `docs/superpowers/**`, `wiki_creator/registry.py`, `wiki_creator/merge_strategies.py`, `tests/**`. No `scripts/`, no `.studio/`.

- [ ] **Step 3: Smoke check the write-registry stage still works**

Run: `pytest tests/test_write_registry.py -v`
Expected: unchanged pass (the stage consumes `from_artifacts`; behavior preserved). If `make smoke` is runnable locally, run it and confirm `registry.json` is still produced.

- [ ] **Step 4: Update Linear + finish the branch**

Move STU-442 Todo → In Progress → In Review. Use superpowers:finishing-a-development-branch to open the PR (repo flow, `Co-Authored-By` convention).

---

## Self-Review (done at planning time)

- **Spec coverage:** §2.1 hybrid emission → Task 3 (real evidence for alias merges via `recover_chapter_id`; `cluster_jw` reconstructed). §2.2 production path untouched → Global Constraints + Task 6 Step 2. §2.3 tie-break conflict → Task 1 `_resolve_alias_conflict`. §2.4 no rejections → nothing records rejects (Ollama path untouched). §2.5 contained footprint → Task 6 Step 2. §3 one merge path → Task 3 (deletes standalone passes). §4 MergeStrategy + vocabulary → Task 2. §5 merge() semantics → Task 1. §6 golden + fixture → Tasks 4+5. §7 minimal stage scope (chapter_id recovered in registry layer) → Task 2 `recover_chapter_id` + Task 3. §8 test net order → Tasks 1→6.
- **Placeholder scan:** none — every step carries complete code/commands. The one "future pass" note (source_ids in projection) is an explicit scope statement, not a deferred task.
- **Type consistency:** `merge(survivor, absorbed, decision) -> str`, `_by_id(entity_id) -> EntityRecord | None`, `strategy_for(name).propose(survivor_id, absorbed_slug, *, evidence, confidence) -> MergeDecision`, `recover_chapter_id(snippet, full_registries) -> str | None`, `compose_evidence(snippet, chapter_id) -> str`, `to_entities_classified() -> list[dict]` used identically across Tasks 1–5.
- **Behavior-preservation risk (Task 3):** the pas-1 test suite (reconstruction/determinism/collisions/duplicate-canonicals/round-trip) is the gate; Step 4 forbids editing those tests to pass. Known intentional deltas: strategy renames (`title_apposition`/`llm_confirm`) and evidence now carrying `[chapter=…]` — both covered by new Task-3 tests and not asserted by pas-1 tests (verified: no test asserts `title_alias`/`llm`). 3+-claimant alias collisions resolve pairwise (documented in `merge()`); the golden fixture deliberately contains no such case.
