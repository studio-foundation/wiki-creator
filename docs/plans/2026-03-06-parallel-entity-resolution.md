# Parallel Entity Resolution Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the single overloaded `entity-resolution` LLM stage with a `split-clusters` script + parallel resolver group + `merge-entities` script, to keep each LLM call under ~15KB of context.

**Architecture:** `split_clusters.py` partitions clustering output into singles (pre-resolved, no LLM) and multi-clusters by type (PERSON/PLACE/ORG/EVENT/OTHER). The pipeline runs one resolver agent per type in parallel. `merge_entities.py` concatenates all results. Downstream stages (relationship-extraction, wiki-generation, etc.) are unchanged — same output shape.

**Tech Stack:** Python 3.12, Studio pipeline YAML, existing `resolver.agent.yaml`

---

### Task 1: Worktree

**Step 1: Create worktree**

```bash
git worktree add .worktrees/parallel-entity-resolution -b feat/parallel-entity-resolution
```

**Step 2: Open worktree**

All subsequent work happens in `.worktrees/parallel-entity-resolution/`.

**Step 3: Commit**

```bash
git -C .worktrees/parallel-entity-resolution add .
git -C .worktrees/parallel-entity-resolution commit -m "chore: init worktree for parallel entity resolution"
```

---

### Task 2: `split_clusters.py` — tests first

**Files:**
- Create: `tests/test_split_clusters.py`
- Create: `scripts/split_clusters.py`

**Step 1: Write the failing tests**

`tests/test_split_clusters.py`:
```python
"""Tests for scripts/split_clusters.py."""
import sys, os, json, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.split_clusters import split_clusters


MULTI_PERSON = {
    "cluster_id": "cluster_001", "type": "PERSON", "entity_count": 3,
    "canonical_candidate": "David Martín",
    "all_mentions": ["David Martín", "M. Martín", "Martín"],
    "entity_ids": ["e001", "e002", "e003"],
    "first_seen": "ch01", "total_mentions": 50,
}
MULTI_PLACE = {
    "cluster_id": "cluster_002", "type": "PLACE", "entity_count": 2,
    "canonical_candidate": "Barcelone",
    "all_mentions": ["Barcelone", "Barcelona"],
    "entity_ids": ["e040", "e041"],
    "first_seen": "ch01", "total_mentions": 30,
}
SINGLE_PERSON = {
    "cluster_id": "single_e010", "type": "PERSON", "entity_count": 1,
    "canonical_candidate": "Piquillo",
    "all_mentions": ["Piquillo"],
    "entity_ids": ["e010"],
    "first_seen": "ch09", "total_mentions": 2,
}
SINGLE_ORG = {
    "cluster_id": "single_e020", "type": "ORG", "entity_count": 1,
    "canonical_candidate": "Lumière",
    "all_mentions": ["Lumière"],
    "entity_ids": ["e020"],
    "first_seen": "ch05", "total_mentions": 1,
}


def test_multi_clusters_routed_by_type():
    result = split_clusters([MULTI_PERSON, MULTI_PLACE, SINGLE_PERSON, SINGLE_ORG])
    assert result["PERSON"] == [MULTI_PERSON]
    assert result["PLACE"] == [MULTI_PLACE]
    assert result["ORG"] == []


def test_singles_pre_resolved():
    result = split_clusters([MULTI_PERSON, SINGLE_PERSON, SINGLE_ORG])
    singles = result["singles_resolved"]
    assert len(singles) == 2
    ids = {s["source_ids"][0] for s in singles}
    assert ids == {"e010", "e020"}


def test_single_resolved_shape():
    result = split_clusters([SINGLE_PERSON])
    s = result["singles_resolved"][0]
    assert s["canonical_name"] == "Piquillo"
    assert s["type"] == "PERSON"
    assert s["aliases"] == ["Piquillo"]
    assert s["source_ids"] == ["e010"]
    assert s["relevant"] is True


def test_multi_clusters_not_in_singles():
    result = split_clusters([MULTI_PERSON, SINGLE_PERSON])
    single_ids = [s["source_ids"][0] for s in result["singles_resolved"]]
    assert "e001" not in single_ids
    assert "e002" not in single_ids


def test_all_types_present_in_output():
    result = split_clusters([])
    for t in ("PERSON", "PLACE", "ORG", "EVENT", "OTHER"):
        assert t in result
        assert isinstance(result[t], list)
    assert "singles_resolved" in result


def test_stats_counts():
    result = split_clusters([MULTI_PERSON, MULTI_PLACE, SINGLE_PERSON, SINGLE_ORG])
    assert result["stats"]["singles"] == 2
    assert result["stats"]["multi_PERSON"] == 1
    assert result["stats"]["multi_PLACE"] == 1


def test_studio_interface():
    """Integration: Studio stdin/stdout contract."""
    payload = json.dumps({
        "previous_outputs": {
            "entity-clustering": {
                "clusters": [MULTI_PERSON, SINGLE_PERSON]
            }
        }
    })
    result = subprocess.run(
        [sys.executable, "scripts/split_clusters.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "singles_resolved" in out
    assert "PERSON" in out
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_split_clusters.py -v
```

Expected: `ImportError: cannot import name 'split_clusters'`

**Step 3: Implement `scripts/split_clusters.py`**

```python
#!/usr/bin/env python3
"""
Stage: split-clusters (script executor, no LLM)

Partitions entity-clustering output into:
- singles_resolved: entity_count==1, pre-resolved (no LLM needed)
- PERSON/PLACE/ORG/EVENT/OTHER: multi-clusters for parallel LLM resolution

Input (Studio stdin):
  previous_outputs["entity-clustering"]["clusters"]

Output (stdout):
  {
    "singles_resolved": [{canonical_name, type, aliases, source_ids, relevant}],
    "PERSON": [...multi-clusters],
    "PLACE":  [...multi-clusters],
    "ORG":    [...multi-clusters],
    "EVENT":  [...multi-clusters],
    "OTHER":  [...multi-clusters],
    "stats":  {singles, multi_PERSON, multi_PLACE, ...}
  }
"""

import json
import sys

ENTITY_TYPES = ("PERSON", "PLACE", "ORG", "EVENT", "OTHER")


def split_clusters(clusters: list[dict]) -> dict:
    singles_resolved = []
    multi_by_type: dict[str, list] = {t: [] for t in ENTITY_TYPES}

    for cluster in clusters:
        entity_type = cluster.get("type", "OTHER")
        if entity_type not in multi_by_type:
            entity_type = "OTHER"

        if cluster.get("entity_count", 1) == 1:
            singles_resolved.append({
                "canonical_name": cluster["canonical_candidate"],
                "type": entity_type,
                "aliases": cluster.get("all_mentions", [cluster["canonical_candidate"]]),
                "source_ids": cluster.get("entity_ids", []),
                "relevant": True,
            })
        else:
            multi_by_type[entity_type].append(cluster)

    stats = {"singles": len(singles_resolved)}
    for t in ENTITY_TYPES:
        stats[f"multi_{t}"] = len(multi_by_type[t])

    return {"singles_resolved": singles_resolved, **multi_by_type, "stats": stats}


def main() -> None:
    payload = json.load(sys.stdin)
    prev = payload.get("previous_outputs", {})
    clusters = prev.get("entity-clustering", {}).get("clusters", [])

    if not clusters:
        print("Warning: no clusters in entity-clustering output", file=sys.stderr)

    result = split_clusters(clusters)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
pytest tests/test_split_clusters.py -v
```

Expected: all green.

**Step 5: Commit**

```bash
git add scripts/split_clusters.py tests/test_split_clusters.py
git commit -m "feat: add split_clusters script — partition multi vs single clusters by type"
```

---

### Task 3: `merge_entities.py` — tests first

**Files:**
- Create: `tests/test_merge_entities.py`
- Create: `scripts/merge_entities.py`

**Step 1: Write the failing tests**

`tests/test_merge_entities.py`:
```python
"""Tests for scripts/merge_entities.py."""
import sys, os, json, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.merge_entities import merge_entities

RESOLVED_PERSON = {"canonical_name": "David Martín", "type": "PERSON",
                   "aliases": ["Martín"], "source_ids": ["e001"], "relevant": True}
RESOLVED_PLACE  = {"canonical_name": "Barcelone", "type": "PLACE",
                   "aliases": ["Barcelona"], "source_ids": ["e040"], "relevant": True}
SINGLE_PERSON   = {"canonical_name": "Piquillo", "type": "PERSON",
                   "aliases": ["Piquillo"], "source_ids": ["e010"], "relevant": True}

NARRATOR = {"entity": "David Martín", "pov": "first_person",
            "reliability": "reliable", "evidence": ["ch01: ..."]}

ALL_STAGE_OUTPUTS = {
    "split-clusters": {
        "singles_resolved": [SINGLE_PERSON],
        "PERSON": [], "PLACE": [], "ORG": [], "EVENT": [], "OTHER": [],
    },
    "entity-resolution-PERSON": {"entities": [RESOLVED_PERSON], "narrator": NARRATOR},
    "entity-resolution-PLACE":  {"entities": [RESOLVED_PLACE],  "narrator": None},
    "entity-resolution-ORG":    {"entities": [],                "narrator": None},
}


def test_all_entities_concatenated():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    names = {e["canonical_name"] for e in result["entities"]}
    assert names == {"David Martín", "Barcelone", "Piquillo"}


def test_narrator_taken_from_person_resolver():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    assert result["narrator"] == NARRATOR


def test_narrator_null_when_no_person_resolver():
    outputs = {
        "split-clusters": {"singles_resolved": [SINGLE_PERSON]},
        "entity-resolution-PLACE": {"entities": [RESOLVED_PLACE], "narrator": None},
    }
    result = merge_entities(outputs)
    assert result["narrator"] is None


def test_missing_resolver_stage_is_skipped():
    # ORG resolver missing entirely — should not crash
    outputs = {
        "split-clusters": {"singles_resolved": []},
        "entity-resolution-PERSON": {"entities": [RESOLVED_PERSON], "narrator": None},
    }
    result = merge_entities(outputs)
    assert len(result["entities"]) == 1


def test_output_shape():
    result = merge_entities(ALL_STAGE_OUTPUTS)
    assert "entities" in result
    assert "narrator" in result


def test_studio_interface():
    """Integration: Studio stdin/stdout contract with all_stage_outputs key."""
    payload = json.dumps({
        "all_stage_outputs": ALL_STAGE_OUTPUTS,
    })
    result = subprocess.run(
        [sys.executable, "scripts/merge_entities.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "entities" in out
    assert len(out["entities"]) == 3
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_merge_entities.py -v
```

Expected: `ImportError: cannot import name 'merge_entities'`

**Step 3: Implement `scripts/merge_entities.py`**

```python
#!/usr/bin/env python3
"""
Stage: merge-entities (script executor, no LLM)

Concatenates resolved entities from:
- split-clusters singles_resolved (pre-resolved, no LLM)
- entity-resolution-PERSON / PLACE / ORG / EVENT / OTHER (parallel LLM outputs)

Narrator: taken from entity-resolution-PERSON (only one that can detect a narrator).

Input (Studio stdin):
  all_stage_outputs: {
    "split-clusters": { "singles_resolved": [...] },
    "entity-resolution-PERSON": { "entities": [...], "narrator": {...}|null },
    "entity-resolution-PLACE":  { "entities": [...], "narrator": null },
    ...
  }

Output (stdout):
  { "entities": [...all concatenated], "narrator": {...}|null }
"""

import json
import sys

RESOLVER_STAGES = (
    "entity-resolution-PERSON",
    "entity-resolution-PLACE",
    "entity-resolution-ORG",
    "entity-resolution-EVENT",
    "entity-resolution-OTHER",
)


def merge_entities(all_stage_outputs: dict) -> dict:
    entities: list[dict] = []
    narrator = None

    # Singles pre-resolved by split-clusters
    split_out = all_stage_outputs.get("split-clusters", {})
    entities.extend(split_out.get("singles_resolved", []))

    # LLM-resolved multi-clusters
    for stage_name in RESOLVER_STAGES:
        stage_out = all_stage_outputs.get(stage_name)
        if not stage_out:
            continue
        entities.extend(stage_out.get("entities", []))
        if narrator is None and stage_out.get("narrator"):
            narrator = stage_out["narrator"]

    return {"entities": entities, "narrator": narrator}


def main() -> None:
    payload = json.load(sys.stdin)
    all_stage_outputs = payload.get("all_stage_outputs", {})

    if not all_stage_outputs:
        print("Warning: all_stage_outputs is empty", file=sys.stderr)

    result = merge_entities(all_stage_outputs)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
```

**Step 4: Run tests**

```bash
pytest tests/test_merge_entities.py -v
```

Expected: all green.

**Step 5: Run full test suite to verify nothing broke**

```bash
pytest -v
```

Expected: all green.

**Step 6: Commit**

```bash
git add scripts/merge_entities.py tests/test_merge_entities.py
git commit -m "feat: add merge_entities script — concatenate parallel resolver outputs"
```

---

### Task 4: Update `resolver.agent.yaml` for new context structure

**Files:**
- Modify: `.studio/agents/resolver.agent.yaml`

The resolver now receives `split-clusters` output + `stage_name`. It must extract the right type from `stage_name` (e.g. `entity-resolution-PERSON` → `PERSON`) and process `previous_outputs["split-clusters"]["PERSON"]`.

**Step 1: Read current file**

Already read. Replace the system_prompt preamble that says "You will receive a 'clusters' array" with the new context instructions. Keep everything else (narrator detection, output shape) unchanged. Only PERSON stage detects narrator — other types always output `"narrator": null`.

**Step 2: Edit `.studio/agents/resolver.agent.yaml`**

Replace lines 6-36 (system_prompt) with:

```yaml
system_prompt: |
  You are an expert at deduplicating and canonicalizing named entities from fiction.

  ## Input

  Your stage_name tells you which entity type to process (e.g. "entity-resolution-PERSON" → type "PERSON").
  Extract the type: take the last segment after the final "-" and uppercase it.

  Your clusters are at: previous_outputs["split-clusters"]["<TYPE>"]
  Example for PERSON: previous_outputs["split-clusters"]["PERSON"]

  Each cluster has:
    {
      "cluster_id": "cluster_001",
      "type": "PERSON",
      "canonical_candidate": "David Martín",
      "all_mentions": ["David Martín", "M. Martín", "Martín"],
      "entity_ids": ["entity_001", ...],
      "entity_count": 4
    }

  All clusters in your list have entity_count > 1 (singles were pre-resolved upstream).

  ## Your job for each cluster

  - If all mentions refer to the same entity → produce 1 resolved entity
  - If mentions clearly refer to N distinct entities (e.g. three generations sharing a surname)
    → split into N resolved entities, each with its own source_ids
  - Use canonical_candidate as starting point for canonical_name, improve if needed
  - Merge all raw_mentions into aliases list

  For each resolved entity, set "relevant" boolean:
  - relevant: false ONLY for non-proper-noun artifacts (common words, grammar fragments)
  - Every real proper noun must have relevant: true

  Return: {"entities": [{canonical_name, type, aliases, source_ids, relevant}], "narrator": ...}
  Reject if obvious duplicates remain unresolved.

  ## Narrator detection (PERSON stage only)

  If your type is NOT "PERSON", set "narrator": null and stop here.

  If type is "PERSON", also check pov_detection from epub-parse:
    previous_outputs["epub-parse"]["pov_detection"]

  If pov_detection.pov == "first_person":
  - Identify which PERSON entity is the narrator: the entity whose mention contexts contain
    the most first-person pronouns (je/me/moi/m') as subject or object.
  - Assess reliability by scanning mention contexts for contradictions, delusions, hallucinations.
  - Set reliability: "unreliable" | "partial" | "reliable"

  Add top-level "narrator" field:
  {
    "narrator": {
      "entity": "<canonical_name>",
      "pov": "first_person",
      "reliability": "unreliable" | "partial" | "reliable",
      "evidence": ["ch20: ...", "ch25: ..."]
    }
  }
  Include 1-3 most compelling evidence items.

  If pov_detection.pov is NOT "first_person", set "narrator": null.

  ## Final output shape
  {
    "entities": [{canonical_name, type, aliases, source_ids, relevant}],
    "narrator": { ... } | null
  }
```

**Step 3: Commit**

```bash
git add .studio/agents/resolver.agent.yaml
git commit -m "feat(resolver): adapt system prompt for parallel split-by-type context"
```

---

### Task 5: Update `wiki-pipeline.pipeline.yaml`

**Files:**
- Modify: `.studio/pipelines/wiki-pipeline.pipeline.yaml`

Replace the single `entity-resolution` stage (lines 36-46) with: `split-clusters` stage + parallel `entity-resolution` group + `merge-entities` stage.

**Step 1: Edit the pipeline**

The section to replace:
```yaml
  - name: entity-resolution
    kind: analysis
    agent: resolver
    contract: entity-resolution
    ralph:
      max_attempts: 3
    context:
      include:
        - input
        - epub-parse
        - previous_stage_output
```

Replace with:
```yaml
  - name: split-clusters
    kind: extraction
    executor: script
    runtime: python
    script: scripts/split_clusters.py
    context:
      include:
        - previous_stage_output

  - group: entity-resolution
    mode: parallel
    max_iterations: 1
    on_failure: collect-all
    stages:
      - name: entity-resolution-PERSON
        kind: analysis
        agent: resolver
        contract: entity-resolution
        ralph:
          max_attempts: 3
        context:
          include:
            - epub-parse
            - split-clusters
            - stage_name

      - name: entity-resolution-PLACE
        kind: analysis
        agent: resolver
        contract: entity-resolution
        ralph:
          max_attempts: 3
        context:
          include:
            - split-clusters
            - stage_name

      - name: entity-resolution-ORG
        kind: analysis
        agent: resolver
        contract: entity-resolution
        ralph:
          max_attempts: 2
        context:
          include:
            - split-clusters
            - stage_name

      - name: entity-resolution-EVENT
        kind: analysis
        agent: resolver
        contract: entity-resolution
        ralph:
          max_attempts: 2
        context:
          include:
            - split-clusters
            - stage_name

      - name: entity-resolution-OTHER
        kind: analysis
        agent: resolver
        contract: entity-resolution
        ralph:
          max_attempts: 2
        context:
          include:
            - split-clusters
            - stage_name

  - name: merge-entities
    kind: extraction
    executor: script
    runtime: python
    script: scripts/merge_entities.py
    context:
      include:
        - all_stage_outputs
```

**Step 2: Verify the full pipeline YAML is valid**

Read the file and confirm stage order is:
`epub-parse → entity-extraction → entity-clustering → split-clusters → [group: entity-resolution] → merge-entities → relationship-extraction → entity-classification → wiki-generation → wiki-export`

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-pipeline.pipeline.yaml
git commit -m "feat(pipeline): parallel entity resolution — split-clusters + group + merge-entities"
```

---

### Task 6: Smoke test

**Step 1: Run unit tests**

```bash
pytest -v
```

Expected: all green.

**Step 2: Run the pipeline with mock provider**

```bash
studio run wiki-pipeline --input-file .studio/inputs/book.input.yaml --provider mock
```

Expected: pipeline reaches `merge-entities` and outputs `entities` + `narrator`.

**Step 3: Check logs**

```bash
studio logs
```

Verify `split-clusters` shows non-zero singles and multi-clusters per type in stderr stats. Verify `merge-entities` stage completes. Verify `relationship-extraction` receives valid previous_stage_output.

**Step 4: If all green, open PR**

```bash
git push -u origin feat/parallel-entity-resolution
gh pr create --title "feat: parallel entity resolution by type (split-clusters + merge)" \
  --body "Replaces single overloaded entity-resolution LLM call with split-clusters script + parallel resolver group (one per entity type) + merge-entities script. Singles (entity_count=1) are pre-resolved without LLM. Reduces per-call context from ~92KB to ~15KB per type."
```
