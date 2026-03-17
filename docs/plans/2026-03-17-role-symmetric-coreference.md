# Role-Symmetric Co-reference (STU-276) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect and merge entities like Brullo/Master that share identical relationship roles toward the same third parties, even when their names share no tokens.

**Architecture:** Reorder the wiki-resolution pipeline so `merge-entities` and `relationship-extraction` run before `alias-resolution`; add an inverted-index-based role-symmetry detector inside `alias_resolution.py`; teach `_pick_canonical_name` to prefer proper names over functional titles explicitly.

**Tech Stack:** Python 3.12, pytest, PyYAML, wiki-resolution pipeline (Studio script executor)

---

## Task 1: Reorder the pipeline YAML

**Files:**
- Modify: `.studio/pipelines/wiki-resolution.pipeline.yaml`

New stage order:
```
split-clusters → resolve-clusters → merge-entities → relationship-extraction → alias-resolution → entity-classification
```

Changes:
- Move the `merge-entities` block to appear immediately after `resolve-clusters`.
- Move the `relationship-extraction` block to appear immediately after `merge-entities`.
- `alias-resolution` now comes after `relationship-extraction`.
- Change `alias-resolution` context from `[input, previous_stage_output]` → `[input, all_stage_outputs]` (needs access to relationship-extraction output).
- `merge-entities` context stays `all_stage_outputs` (fallback chain in the code handles the new order with no code changes).

New YAML content for the relevant section:

```yaml
stages:
  - name: split-clusters
    kind: extraction
    executor: script
    runtime: python
    script: scripts/load_splits.py
    contract: split-clusters
    context:
      include:
        - input

  - name: resolve-clusters
    kind: extraction
    executor: script
    runtime: python
    script: scripts/resolve_clusters.py
    contract: resolve-clusters
    context:
      include:
        - previous_stage_output

  - name: merge-entities
    kind: extraction
    executor: script
    runtime: python
    script: scripts/merge_entities.py
    contract: merge-entities
    context:
      include:
        - all_stage_outputs

  - name: relationship-extraction
    kind: analysis
    executor: script
    runtime: python
    script: scripts/relationship_extraction.py
    contract: relationship-extraction
    timeout_ms: 600000
    context:
      include:
        - input
        - previous_stage_output

  - name: alias-resolution
    kind: extraction
    executor: script
    runtime: python
    script: scripts/alias_resolution.py
    contract: alias-resolution
    context:
      include:
        - input
        - all_stage_outputs

  - name: entity-classification
    kind: extraction
    executor: script
    runtime: python
    script: scripts/entity_classification.py
    contract: entity-classification
    context:
      include:
        - input
        - previous_stage_output
```

**Step 1: Apply the YAML edit**

Replace the entire `stages:` section with the new order above.

**Step 2: Verify no test breaks yet**

```bash
pytest -q
```
Expected: same pass count as baseline (288 passed).

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-resolution.pipeline.yaml
git commit -m "refactor(pipeline): reorder wiki-resolution — merge-entities + relationship-extraction before alias-resolution (STU-276)"
```

---

## Task 2: Update `alias_resolution.main()` to read from `merge-entities`

Currently `main()` reads entities from `previous_outputs["resolve-clusters"]`. After the pipeline reorder, the previous stage is `relationship-extraction`, not `resolve-clusters`. The entities come from `merge-entities` in `all_stage_outputs`.

**Files:**
- Modify: `scripts/alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

### Step 1: Write the failing test

Add to `tests/test_alias_resolution.py`:

```python
def test_main_reads_entities_from_merge_entities_when_available(tmp_path):
    """After pipeline reorder, alias-resolution receives merge-entities output in all_stage_outputs."""
    import subprocess, json
    book_yaml = tmp_path / "library" / "a" / "s" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n")
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(json.dumps({"persons_full": {}}))

    merged_entity = {
        "canonical_name": "Brullo",
        "type": "PERSON",
        "aliases": ["Brullo"],
        "source_ids": [],
        "relevant": True,
    }
    payload = {
        "additional_context": f"file_path: {book_yaml}\n",
        "previous_outputs": {
            "merge-entities": {"entities": [merged_entity], "narrator": None},
        },
        "all_stage_outputs": {
            "merge-entities": {"entities": [merged_entity], "narrator": None},
            "relationship-extraction": {"relationships": []},
        },
    }
    result = subprocess.run(
        ["python", "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=str(Path(__file__).parents[1]),
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert len(output["entities"]) == 1
    assert output["entities"][0]["canonical_name"] == "Brullo"
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_alias_resolution.py::test_main_reads_entities_from_merge_entities_when_available -v
```
Expected: FAIL — script reads from `resolve-clusters` which is absent → entities is empty list.

**Step 3: Implement in `alias_resolution.main()`**

In `scripts/alias_resolution.py`, locate the `main()` function. Change the entity-loading block from:

```python
    previous_outputs = payload.get("previous_outputs", {})
    resolve_output = previous_outputs.get("resolve-clusters", {})
    entities = resolve_output.get("entities", [])
    narrator = resolve_output.get("narrator")
```

to:

```python
    previous_outputs = payload.get("previous_outputs", {})
    all_stage_outputs = payload.get("all_stage_outputs", {})
    # New pipeline: entities come from merge-entities; fall back to resolve-clusters for compat.
    entity_source = (
        all_stage_outputs.get("merge-entities")
        or previous_outputs.get("merge-entities")
        or previous_outputs.get("resolve-clusters")
        or {}
    )
    entities = entity_source.get("entities", [])
    narrator = entity_source.get("narrator")
    # Relationships from relationship-extraction (empty list if stage not run yet).
    relationships: list[dict] = (
        all_stage_outputs.get("relationship-extraction", {}).get("relationships", [])
    )
```

Also pass `relationships` into `resolve_aliases()` (signature change handled in Task 4).

**Step 4: Run test**

```bash
pytest tests/test_alias_resolution.py::test_main_reads_entities_from_merge_entities_when_available -v
```
Expected: PASS.

**Step 5: Run full suite**

```bash
pytest -q
```
Expected: all pass.

**Step 6: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(alias-resolution): read entities from merge-entities stage output (STU-276)"
```

---

## Task 3: Explicit proper-name > title rule in `_pick_canonical_name`

**Files:**
- Modify: `scripts/alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

### Step 1: Write the failing tests

Add to `tests/test_alias_resolution.py`:

```python
def test_pick_canonical_name_prefers_proper_name_over_pure_title():
    """'Brullo' must win over 'Master' when 'master' is a role_word."""
    from scripts.alias_resolution import _pick_canonical_name
    brullo = {
        "canonical_name": "Brullo",
        "aliases": ["Brullo"],
        "source_ids": [],
    }
    master = {
        "canonical_name": "Master",
        "aliases": ["Master"],
        "source_ids": [],
    }
    # Frequency is equal (no persons_full context); proper name must still win.
    canonical = _pick_canonical_name(brullo, master, persons_full={}, role_words=["master"])
    assert canonical == "Brullo"


def test_pick_canonical_name_keeps_frequency_when_no_pure_title():
    """With no pure title involved, frequency still wins."""
    from scripts.alias_resolution import _pick_canonical_name
    celaena = {
        "canonical_name": "Celaena",
        "aliases": ["Celaena"],
        "source_ids": ["e1"],
    }
    aelin = {
        "canonical_name": "Aelin",
        "aliases": ["Aelin"],
        "source_ids": ["e2"],
    }
    persons_full = {
        "e1": {"mentions_by_chapter": {"ch01": ["Celaena Celaena Celaena walked in."]}},
        "e2": {"mentions_by_chapter": {"ch01": ["Aelin smiled."]}},
    }
    canonical = _pick_canonical_name(celaena, aelin, persons_full=persons_full, role_words=["captain"])
    assert canonical == "Celaena"  # higher frequency
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_alias_resolution.py::test_pick_canonical_name_prefers_proper_name_over_pure_title tests/test_alias_resolution.py::test_pick_canonical_name_keeps_frequency_when_no_pure_title -v
```
Expected: first test FAIL (`_pick_canonical_name` doesn't accept `role_words`).

**Step 3: Add `_is_pure_title` helper and update `_pick_canonical_name`**

In `scripts/alias_resolution.py`, add this function just above `_pick_canonical_name`:

```python
def _is_pure_title(name: str, role_words: list[str]) -> bool:
    """Return True if name consists entirely of role_words (e.g. 'Master', 'Captain')."""
    tokens = name.lower().split()
    if not tokens:
        return False
    role_set = {r.lower() for r in role_words}
    return all(t in role_set for t in tokens)
```

Update `_pick_canonical_name` signature and sort key:

```python
def _pick_canonical_name(
    entity_a: dict,
    entity_b: dict,
    persons_full: dict,
    role_words: list[str] | None = None,
) -> str:
    role_words = role_words or []
    counts: dict[str, int] = {}
    for entity in (entity_a, entity_b):
        for name in _entity_names(entity):
            counts[name] = 0
    for entity in (entity_a, entity_b):
        contexts = " ".join(_gather_contexts(entity, persons_full)).lower()
        for name in counts:
            counts[name] += contexts.count(name.lower())
    return sorted(
        counts,
        key=lambda name: (
            _is_pure_title(name, role_words),   # False (0) sorts before True (1) — proper names first
            -counts[name],
            -len(name.split()),
            -len(name),
            name.lower(),
        ),
    )[0]
```

Also update the two call sites of `_pick_canonical_name` inside `_merge_entities` to pass through `role_words`. This requires `_merge_entities` to also accept and forward `role_words`. Change its signature to:

```python
def _merge_entities(
    entity_a: dict,
    entity_b: dict,
    evidence: dict,
    persons_full: dict,
    role_words: list[str] | None = None,
) -> dict:
    canonical = _pick_canonical_name(entity_a, entity_b, persons_full, role_words=role_words)
    # ... rest unchanged
```

Update all callers of `_merge_entities` in `resolve_aliases()` to pass `role_words=role_words`.

**Step 4: Run tests**

```bash
pytest tests/test_alias_resolution.py::test_pick_canonical_name_prefers_proper_name_over_pure_title tests/test_alias_resolution.py::test_pick_canonical_name_keeps_frequency_when_no_pure_title -v
```
Expected: PASS.

**Step 5: Run full suite**

```bash
pytest -q
```
Expected: all pass.

**Step 6: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(alias-resolution): explicit proper-name > title rule in _pick_canonical_name (STU-276)"
```

---

## Task 4: `_build_role_index` + `_detect_role_symmetric_pairs`

**Files:**
- Modify: `scripts/alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

### Data shape reminder

A relationship dict from `relationship-extraction` looks like:
```json
{
  "entity_a": "Celaena Sardothien",
  "entity_b": "Master",
  "cooccurrence_count": 12,
  "relationship_type": "mentor/protégé",
  "direction": "..."
}
```

`relationship_type` may be `null` for unclassified relationships — skip those.

### Step 1: Write the failing tests

Add to `tests/test_alias_resolution.py`:

```python
def test_build_role_index_groups_by_third_party_and_rel_type():
    from scripts.alias_resolution import _build_role_index
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Master", "relationship_type": "mentor/protégé", "cooccurrence_count": 12},
        {"entity_a": "Brullo",  "entity_b": "Celaena", "relationship_type": "mentor/protégé", "cooccurrence_count": 8},
        {"entity_a": "Dorian",  "entity_b": "Celaena", "relationship_type": "ami",            "cooccurrence_count": 5},
    ]
    index = _build_role_index(relationships)
    # ("Celaena", "mentor/protégé") should have both Master and Brullo
    key = ("Celaena", "mentor/protégé")
    assert key in index
    assert set(index[key]) == {"Master", "Brullo"}


def test_build_role_index_skips_unclassified():
    from scripts.alias_resolution import _build_role_index
    relationships = [
        {"entity_a": "A", "entity_b": "C", "relationship_type": None, "cooccurrence_count": 3},
    ]
    index = _build_role_index(relationships)
    assert index == {}


def test_detect_role_symmetric_finds_brullo_master():
    from scripts.alias_resolution import _detect_role_symmetric_pairs
    brullo = {
        "canonical_name": "Brullo",
        "type": "PERSON",
        "aliases": ["Brullo"],
        "source_ids": [],
        "relevant": True,
    }
    master = {
        "canonical_name": "Master",
        "type": "PERSON",
        "aliases": ["Master"],
        "source_ids": [],
        "relevant": True,
    }
    celaena = {
        "canonical_name": "Celaena Sardothien",
        "type": "PERSON",
        "aliases": ["Celaena Sardothien", "Celaena"],
        "source_ids": [],
        "relevant": True,
    }
    dorian = {
        "canonical_name": "Dorian",
        "type": "PERSON",
        "aliases": ["Dorian"],
        "source_ids": [],
        "relevant": True,
    }
    relationships = [
        # Both Brullo and Master share: Celaena as mentor/protégé AND Dorian as connaissance
        {"entity_a": "Celaena Sardothien", "entity_b": "Master", "relationship_type": "mentor/protégé", "cooccurrence_count": 12},
        {"entity_a": "Brullo", "entity_b": "Celaena Sardothien", "relationship_type": "mentor/protégé", "cooccurrence_count": 8},
        {"entity_a": "Dorian",  "entity_b": "Master",  "relationship_type": "connaissance", "cooccurrence_count": 3},
        {"entity_a": "Dorian",  "entity_b": "Brullo",  "relationship_type": "connaissance", "cooccurrence_count": 2},
    ]
    pairs = _detect_role_symmetric_pairs(
        [brullo, master, celaena, dorian],
        relationships,
        min_shared=2,
        direct_cooc_max=3,
    )
    assert len(pairs) == 1
    names = {pairs[0][0]["canonical_name"], pairs[0][1]["canonical_name"]}
    assert names == {"Brullo", "Master"}


def test_detect_role_symmetric_no_false_positive_with_one_shared_third_party():
    """Two guards sharing only one common (third_party, rel_type) bucket do not trigger."""
    from scripts.alias_resolution import _detect_role_symmetric_pairs
    guard_a = {"canonical_name": "Guard A", "type": "PERSON", "aliases": ["Guard A"], "source_ids": [], "relevant": True}
    guard_b = {"canonical_name": "Guard B", "type": "PERSON", "aliases": ["Guard B"], "source_ids": [], "relevant": True}
    lord = {"canonical_name": "Lord X", "type": "PERSON", "aliases": ["Lord X"], "source_ids": [], "relevant": True}
    relationships = [
        {"entity_a": "Lord X", "entity_b": "Guard A", "relationship_type": "employeur/employé", "cooccurrence_count": 5},
        {"entity_a": "Lord X", "entity_b": "Guard B", "relationship_type": "employeur/employé", "cooccurrence_count": 3},
    ]
    pairs = _detect_role_symmetric_pairs(
        [guard_a, guard_b, lord],
        relationships,
        min_shared=2,  # only 1 shared bucket → no merge
        direct_cooc_max=3,
    )
    assert pairs == []


def test_detect_role_symmetric_skips_high_direct_cooccurrence():
    """If A and B already co-occur heavily, they are likely already handled."""
    from scripts.alias_resolution import _detect_role_symmetric_pairs
    a = {"canonical_name": "A", "type": "PERSON", "aliases": ["A"], "source_ids": [], "relevant": True}
    b = {"canonical_name": "B", "type": "PERSON", "aliases": ["B"], "source_ids": [], "relevant": True}
    c = {"canonical_name": "C", "type": "PERSON", "aliases": ["C"], "source_ids": [], "relevant": True}
    d = {"canonical_name": "D", "type": "PERSON", "aliases": ["D"], "source_ids": [], "relevant": True}
    relationships = [
        {"entity_a": "A", "entity_b": "C", "relationship_type": "ami", "cooccurrence_count": 5},
        {"entity_a": "B", "entity_b": "C", "relationship_type": "ami", "cooccurrence_count": 5},
        {"entity_a": "A", "entity_b": "D", "relationship_type": "ami", "cooccurrence_count": 5},
        {"entity_a": "B", "entity_b": "D", "relationship_type": "ami", "cooccurrence_count": 5},
        # A and B also appear directly together with high cooccurrence
        {"entity_a": "A", "entity_b": "B", "relationship_type": "ami", "cooccurrence_count": 20},
    ]
    pairs = _detect_role_symmetric_pairs(
        [a, b, c, d],
        relationships,
        min_shared=2,
        direct_cooc_max=3,  # 20 > 3 → skip
    )
    assert pairs == []
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_alias_resolution.py::test_build_role_index_groups_by_third_party_and_rel_type tests/test_alias_resolution.py::test_build_role_index_skips_unclassified tests/test_alias_resolution.py::test_detect_role_symmetric_finds_brullo_master tests/test_alias_resolution.py::test_detect_role_symmetric_no_false_positive_with_one_shared_third_party tests/test_alias_resolution.py::test_detect_role_symmetric_skips_high_direct_cooccurrence -v
```
Expected: all FAIL with `ImportError` or `AttributeError`.

**Step 3: Implement `_build_role_index` and `_detect_role_symmetric_pairs`**

Add to `scripts/alias_resolution.py` just above `resolve_aliases`:

```python
def _build_role_index(relationships: list[dict]) -> dict[tuple[str, str], list[str]]:
    """
    Build an inverted index: (third_party_canonical, relationship_type) → [entity names with this role].

    For each relationship (A ↔ B, rel_type), B is a third party for A and vice versa.
    Skips relationships with null relationship_type.
    """
    index: dict[tuple[str, str], list[str]] = {}
    for rel in relationships:
        rel_type = rel.get("relationship_type")
        if not rel_type:
            continue
        entity_a: str = rel.get("entity_a", "")
        entity_b: str = rel.get("entity_b", "")
        if not entity_a or not entity_b:
            continue
        # A plays a role toward B
        key_a = (entity_b, rel_type)
        index.setdefault(key_a, [])
        if entity_a not in index[key_a]:
            index[key_a].append(entity_a)
        # B plays a role toward A
        key_b = (entity_a, rel_type)
        index.setdefault(key_b, [])
        if entity_b not in index[key_b]:
            index[key_b].append(entity_b)
    return index


def _direct_cooccurrence(name_a: str, name_b: str, relationships: list[dict]) -> int:
    """Return the cooccurrence_count for the direct A↔B relationship, or 0."""
    na, nb = name_a.lower(), name_b.lower()
    for rel in relationships:
        ea = rel.get("entity_a", "").lower()
        eb = rel.get("entity_b", "").lower()
        if (ea == na and eb == nb) or (ea == nb and eb == na):
            return rel.get("cooccurrence_count", 0)
    return 0


def _detect_role_symmetric_pairs(
    entities: list[dict],
    relationships: list[dict],
    min_shared: int = 2,
    direct_cooc_max: int = 3,
) -> list[tuple[dict, dict, dict]]:
    """
    Return (entity_a, entity_b, evidence) triples where A and B share ≥ min_shared
    (third_party, relationship_type) buckets AND their direct cooccurrence is ≤ direct_cooc_max.

    Evidence dict has keys: method, confidence, snippet.
    """
    role_index = _build_role_index(relationships)
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]

    # For each entity, collect its set of (third_party, rel_type) buckets.
    def signature(entity: dict) -> set[tuple[str, str]]:
        name = entity.get("canonical_name", "")
        result: set[tuple[str, str]] = set()
        for (third_party, rel_type), names in role_index.items():
            if name in names:
                result.add((third_party, rel_type))
        return result

    pairs: list[tuple[dict, dict, dict]] = []
    for i in range(len(persons)):
        for j in range(i + 1, len(persons)):
            a, b = persons[i], persons[j]
            name_a = a.get("canonical_name", "")
            name_b = b.get("canonical_name", "")
            # Skip if they already co-occur heavily (likely already handled or distinct)
            if _direct_cooccurrence(name_a, name_b, relationships) > direct_cooc_max:
                continue
            shared = signature(a) & signature(b)
            if len(shared) < min_shared:
                continue
            shared_list = sorted(shared)
            snippet = "; ".join(
                f"{name_a} and {name_b} both have '{rel}' relation toward '{third}'"
                for third, rel in shared_list[:2]
            )
            evidence = {
                "method": "role_symmetric",
                "confidence": "medium",
                "snippet": snippet,
                "shared_roles": [{"third_party": t, "relationship_type": r} for t, r in shared_list],
            }
            pairs.append((a, b, evidence))
    return pairs
```

**Step 4: Run tests**

```bash
pytest tests/test_alias_resolution.py::test_build_role_index_groups_by_third_party_and_rel_type tests/test_alias_resolution.py::test_build_role_index_skips_unclassified tests/test_alias_resolution.py::test_detect_role_symmetric_finds_brullo_master tests/test_alias_resolution.py::test_detect_role_symmetric_no_false_positive_with_one_shared_third_party tests/test_alias_resolution.py::test_detect_role_symmetric_skips_high_direct_cooccurrence -v
```
Expected: all PASS.

**Step 5: Run full suite**

```bash
pytest -q
```
Expected: all pass.

**Step 6: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(alias-resolution): add _build_role_index and _detect_role_symmetric_pairs (STU-276)"
```

---

## Task 5: Wire role-symmetric detection into `resolve_aliases()`

**Files:**
- Modify: `scripts/alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

### Step 1: Write the failing test

Add to `tests/test_alias_resolution.py`:

```python
def test_resolve_aliases_role_symmetric_with_llm_merges():
    """Role-symmetric pairs go to LLM; confirmed pairs are merged with Brullo winning over Master."""
    from scripts.alias_resolution import resolve_aliases
    brullo = {
        "canonical_name": "Brullo",
        "type": "PERSON",
        "aliases": ["Brullo"],
        "source_ids": [],
        "relevant": True,
    }
    master = {
        "canonical_name": "Master",
        "type": "PERSON",
        "aliases": ["Master"],
        "source_ids": [],
        "relevant": True,
    }
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Master",  "relationship_type": "mentor/protégé", "cooccurrence_count": 12},
        {"entity_a": "Brullo",  "entity_b": "Celaena", "relationship_type": "mentor/protégé", "cooccurrence_count": 8},
        {"entity_a": "Dorian",  "entity_b": "Master",  "relationship_type": "connaissance",   "cooccurrence_count": 3},
        {"entity_a": "Dorian",  "entity_b": "Brullo",  "relationship_type": "connaissance",   "cooccurrence_count": 2},
    ]

    def confirm_yes(candidate):
        return {"same_person": True, "confidence": "medium", "evidence": "same role toward Celaena"}

    result = resolve_aliases(
        [brullo, master],
        persons_full={},
        llm_confirmer=confirm_yes,
        relationships=relationships,
        role_words=["master"],
        role_symmetric_min_shared=2,
    )
    assert len(result["entities"]) == 1
    assert result["entities"][0]["canonical_name"] == "Brullo"
    assert result["stats"]["merges_by_method"].get("role_symmetric", 0) >= 1


def test_resolve_aliases_role_symmetric_no_llm_stays_ambiguous():
    """Without LLM confirmer, role-symmetric candidates stay as ambiguous_pairs."""
    from scripts.alias_resolution import resolve_aliases
    brullo = {"canonical_name": "Brullo", "type": "PERSON", "aliases": ["Brullo"], "source_ids": [], "relevant": True}
    master = {"canonical_name": "Master", "type": "PERSON", "aliases": ["Master"], "source_ids": [], "relevant": True}
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Master",  "relationship_type": "mentor/protégé", "cooccurrence_count": 12},
        {"entity_a": "Brullo",  "entity_b": "Celaena", "relationship_type": "mentor/protégé", "cooccurrence_count": 8},
        {"entity_a": "Dorian",  "entity_b": "Master",  "relationship_type": "connaissance",   "cooccurrence_count": 3},
        {"entity_a": "Dorian",  "entity_b": "Brullo",  "relationship_type": "connaissance",   "cooccurrence_count": 2},
    ]
    result = resolve_aliases(
        [brullo, master],
        persons_full={},
        llm_confirmer=None,
        relationships=relationships,
        role_words=["master"],
        role_symmetric_min_shared=2,
    )
    assert len(result["entities"]) == 2  # not merged
    assert result["stats"]["ambiguous_pairs"] >= 1
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_alias_resolution.py::test_resolve_aliases_role_symmetric_with_llm_merges tests/test_alias_resolution.py::test_resolve_aliases_role_symmetric_no_llm_stays_ambiguous -v
```
Expected: FAIL — `resolve_aliases` doesn't accept `relationships` or `role_symmetric_min_shared`.

**Step 3: Update `_empty_stats()`**

In `_empty_stats()`, add `"role_symmetric": 0` to `merges_by_method`:

```python
def _empty_stats() -> dict:
    return {
        "candidates_considered": 0,
        "merges_applied": 0,
        "merges_by_method": {"pattern": 0, "cooccurrence": 0, "llm": 0, "title_alias": 0, "role_symmetric": 0},
        "ambiguous_pairs": 0,
        "llm_attempts": 0,
        "llm_confirmed": 0,
        "llm_failed": 0,
    }
```

**Step 4: Update `resolve_aliases()` signature and logic**

Add `relationships` and `role_symmetric_min_shared` parameters, and add the role-symmetric detection after the existing heuristics:

```python
def resolve_aliases(
    entities: list[dict],
    persons_full: dict,
    narrator=None,
    llm_confirmer=None,
    reveal_words: tuple[str, ...] = (),
    role_words: list[str] | None = None,
    pattern_templates: tuple[str, ...] = (),
    relationships: list[dict] | None = None,
    role_symmetric_min_shared: int = 2,
) -> dict:
    stats = _empty_stats()
    role_words = role_words or []
    relationships = relationships or []
    resolved: list[dict] = []
    consumed: set[int] = set()

    # Pre-compute role-symmetric candidate pairs (index-based for efficiency)
    role_sym_pairs: set[tuple[int, int]] = set()
    if relationships:
        sym_candidates = _detect_role_symmetric_pairs(
            entities, relationships,
            min_shared=role_symmetric_min_shared,
        )
        # Build a lookup by canonical_name → index
        name_to_idx = {e.get("canonical_name", ""): i for i, e in enumerate(entities)}
        for ea, eb, _ev in sym_candidates:
            ia = name_to_idx.get(ea.get("canonical_name", ""))
            ib = name_to_idx.get(eb.get("canonical_name", ""))
            if ia is not None and ib is not None:
                role_sym_pairs.add((min(ia, ib), max(ia, ib)))

    for index, entity in enumerate(entities):
        if index in consumed:
            continue
        if entity.get("type") != "PERSON" or not entity.get("relevant", True):
            resolved.append(entity)
            continue

        merged = None
        for candidate_index in range(index + 1, len(entities)):
            if candidate_index in consumed:
                continue
            candidate = entities[candidate_index]
            if candidate.get("type") != "PERSON" or not candidate.get("relevant", True):
                continue

            stats["candidates_considered"] += 1

            evidence = _detect_pattern_match(entity, candidate, persons_full, pattern_templates)
            if evidence:
                merged = _merge_entities(entity, candidate, evidence, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["pattern"] += 1
                consumed.add(candidate_index)
                break

            title = _detect_title_alias(entity, candidate, role_words)
            if title:
                merged = _merge_entities(entity, candidate, title, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["title_alias"] += 1
                consumed.add(candidate_index)
                break

            reveal = _detect_reveal_signal(entity, candidate, persons_full, reveal_words=reveal_words)
            pair_key = (min(index, candidate_index), max(index, candidate_index))
            role_sym = None
            if not reveal and pair_key in role_sym_pairs:
                # Build evidence from the pre-computed pair
                for ea, eb, ev in (sym_candidates if relationships else []):
                    ea_name = ea.get("canonical_name", "")
                    eb_name = eb.get("canonical_name", "")
                    curr_names = {entity.get("canonical_name", ""), candidate.get("canonical_name", "")}
                    if {ea_name, eb_name} == curr_names:
                        role_sym = ev
                        break

            signal = reveal or role_sym
            if not signal:
                continue

            if llm_confirmer is None:
                stats["ambiguous_pairs"] += 1
                continue

            stats["llm_attempts"] += 1
            try:
                decision = llm_confirmer({
                    "entity_a": entity,
                    "entity_b": candidate,
                    "evidence": signal,
                    "persons_full": persons_full,
                }) or {}
            except Exception:
                stats["llm_failed"] += 1
                stats["ambiguous_pairs"] += 1
                continue

            if decision.get("same_person"):
                method = signal.get("method", "llm")
                merged_evidence = {
                    "method": method if method == "role_symmetric" else "llm",
                    "confidence": decision.get("confidence", "medium"),
                    "snippet": decision.get("evidence", signal["snippet"]),
                }
                merged = _merge_entities(entity, candidate, merged_evidence, persons_full, role_words=role_words)
                stats["merges_applied"] += 1
                stat_key = "role_symmetric" if method == "role_symmetric" else "llm"
                stats["merges_by_method"][stat_key] += 1
                stats["llm_confirmed"] += 1
                consumed.add(candidate_index)
                break

            stats["ambiguous_pairs"] += 1

        resolved.append(merged or entity)

    return {"entities": resolved, "narrator": narrator, "stats": stats}
```

> **Note:** `sym_candidates` is referenced inside the loop. Move it to the outer scope: in the pre-computation block, assign it with a default of `[]` when `relationships` is empty.

**Step 5: Update `main()` to pass `relationships` into `resolve_aliases()`**

In `main()`, add `relationships=relationships` to the `resolve_aliases(...)` call:

```python
    result = resolve_aliases(
        entities, persons_full=persons_full, narrator=narrator,
        llm_confirmer=llm_confirmer, reveal_words=reveal_words,
        role_words=role_words, pattern_templates=pattern_templates,
        relationships=relationships,
        role_symmetric_min_shared=ctx.get("role_symmetric_min_shared", 2),
    )
```

**Step 6: Run tests**

```bash
pytest tests/test_alias_resolution.py::test_resolve_aliases_role_symmetric_with_llm_merges tests/test_alias_resolution.py::test_resolve_aliases_role_symmetric_no_llm_stays_ambiguous -v
```
Expected: PASS.

**Step 7: Run full suite**

```bash
pytest -q
```
Expected: all pass.

**Step 8: Commit**

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(alias-resolution): wire role_symmetric detection into resolve_aliases (STU-276)"
```

---

## Task 6: Final smoke test and acceptance criteria check

**Step 1: Run full suite**

```bash
pytest -q
```
Expected: ≥ 288 passed (original baseline + new tests).

**Step 2: Check acceptance criteria from STU-276**

- [ ] `Brullo` and `Master` would be fused given the relationships in batch_000.json run 5 → verified by `test_detect_role_symmetric_finds_brullo_master` + `test_resolve_aliases_role_symmetric_with_llm_merges`
- [ ] Canonical is `Brullo` (proper name > title) → verified by `test_resolve_aliases_role_symmetric_with_llm_merges` + `test_pick_canonical_name_prefers_proper_name_over_pure_title`
- [ ] No false positive for one shared third-party → verified by `test_detect_role_symmetric_no_false_positive_with_one_shared_third_party`
- [ ] Logic is thresholded (`min_shared`, `direct_cooc_max`) → verified by threshold tests

**Step 3: Invoke finishing skill**

Use `superpowers:finishing-a-development-branch` to complete the work.
