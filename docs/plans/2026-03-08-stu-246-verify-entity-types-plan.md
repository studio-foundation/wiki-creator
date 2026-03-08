# STU-246 Verify Entity Types — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an optional `verify-entity-types` stage between `entity-clustering` and `split-clusters` that uses `mistral:7b-instruct` via Ollama to correct PERSON entities misclassified as PLACE or ORG by spaCy.

**Architecture:** New script executor stage `scripts/verify_entity_types.py` inserted in `wiki-extraction.pipeline.yaml`. When `verify_entity_types: false` (default), it's a pure pass-through. When enabled, it reads context from `places_full.json` / `orgs_full.json` on disk, filters obvious geographic names, sends ambiguous candidates to Ollama, and reclassifies confirmed PERSONs. Output is same shape as `entity-clustering` output + `type_corrections` list.

**Tech Stack:** Python 3.11, `requests` (Ollama HTTP API at `http://localhost:11434`), `yaml`, `json`. No new dependencies — `requests` is already available.

---

### Task 1: Create the test file with failing tests

**Files:**
- Create: `tests/test_verify_entity_types.py`

**Step 1: Write the failing tests**

```python
"""Tests for scripts/verify_entity_types.py — entity type verification."""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.verify_entity_types import (
    is_obvious_geographic,
    load_context_for_cluster,
    apply_corrections,
)


# --- is_obvious_geographic ---

def test_obvious_geographic_rue():
    assert is_obvious_geographic("rue de la Paix") is True

def test_obvious_geographic_avenue():
    assert is_obvious_geographic("avenue Barcelona") is True

def test_obvious_geographic_eglise():
    assert is_obvious_geographic("Église Saint-Pierre") is True

def test_obvious_geographic_proper_name_not_geo():
    assert is_obvious_geographic("Barrido") is False

def test_obvious_geographic_hispanic_name():
    assert is_obvious_geographic("Marlasca") is False

def test_obvious_geographic_case_insensitive():
    assert is_obvious_geographic("Boulevard du Temple") is True


# --- load_context_for_cluster ---

def test_load_context_finds_entity(tmp_path):
    # Write a fake places_full.json
    data = {
        "places_full": {
            "entity_042": {
                "type": "PLACE",
                "raw_mentions": ["Barrido"],
                "mentions_by_chapter": {
                    "ch03": ["Barrido lui tendit la main en souriant."]
                }
            }
        }
    }
    places_file = tmp_path / "places_full.json"
    places_file.write_text(json.dumps(data))

    ctx = load_context_for_cluster(
        entity_ids=["entity_042"],
        original_type="PLACE",
        search_dirs=[str(tmp_path)],
    )
    assert len(ctx) == 1
    assert "Barrido" in ctx[0] or "Barrido lui tendit" in ctx[0]

def test_load_context_missing_entity_returns_empty(tmp_path):
    data = {"places_full": {}}
    places_file = tmp_path / "places_full.json"
    places_file.write_text(json.dumps(data))

    ctx = load_context_for_cluster(
        entity_ids=["entity_999"],
        original_type="PLACE",
        search_dirs=[str(tmp_path)],
    )
    assert ctx == []


# --- apply_corrections ---

def test_apply_corrections_reclassifies_person():
    clusters = [
        {
            "cluster_id": "single_entity_042",
            "type": "PLACE",
            "canonical_candidate": "Barrido",
            "all_mentions": ["Barrido"],
            "entity_ids": ["entity_042"],
            "entity_count": 1,
            "total_mentions": 5,
        }
    ]
    corrections = [{"cluster_id": "single_entity_042", "from": "PLACE", "to": "PERSON"}]
    result = apply_corrections(clusters, corrections)
    assert result[0]["type"] == "PERSON"

def test_apply_corrections_leaves_others_unchanged():
    clusters = [
        {"cluster_id": "cluster_001", "type": "PERSON", "canonical_candidate": "Martín",
         "all_mentions": ["Martín"], "entity_ids": ["entity_001"], "entity_count": 1, "total_mentions": 10},
        {"cluster_id": "single_entity_042", "type": "PLACE", "canonical_candidate": "Barrido",
         "all_mentions": ["Barrido"], "entity_ids": ["entity_042"], "entity_count": 1, "total_mentions": 5},
    ]
    corrections = [{"cluster_id": "single_entity_042", "from": "PLACE", "to": "PERSON"}]
    result = apply_corrections(clusters, corrections)
    assert result[0]["type"] == "PERSON"   # Martín unchanged
    assert result[1]["type"] == "PERSON"   # Barrido corrected
```

**Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_verify_entity_types.py -v
```

Expected: `ImportError` — `verify_entity_types` module doesn't exist yet.

**Step 3: Commit the failing tests**

```bash
git add tests/test_verify_entity_types.py
git commit -m "test(stu-246): failing tests for verify_entity_types"
```

---

### Task 2: Implement `verify_entity_types.py` — pure logic (no Ollama yet)

**Files:**
- Create: `scripts/verify_entity_types.py`

**Step 1: Write the implementation for the three tested functions**

```python
#!/usr/bin/env python3
"""
Stage: verify-entity-types (script executor, optional LLM)

Checks clusters typed PLACE or ORG that might actually be PERSON,
using Ollama (mistral:7b-instruct) for ambiguous cases.

Activated via input YAML flag: verify_entity_types: true
When false (default): pure pass-through, no Ollama call.

Input (Studio stdin):
  additional_context: YAML with verify_entity_types, ollama_model
  previous_outputs["entity-clustering"]: {clusters, stats}

Side reads (from project root):
  places_full.json  — context sentences for PLACE-typed entities
  orgs_full.json    — context sentences for ORG-typed entities

Output (stdout):
  {clusters, stats, type_corrections: [{cluster_id, name, from, to, context_snippet}]}
"""

import json
import sys
import yaml

# Keywords that indicate a genuine geographic entity — skip LLM for these
GEOGRAPHIC_KEYWORDS = frozenset({
    "rue", "avenue", "boulevard", "place", "quartier", "ville",
    "église", "eglise", "cathédrale", "cathedrale", "cimetière",
    "cimetiere", "gare", "marché", "marche", "pont", "tour",
    "château", "chateau", "palais", "hotel", "hôtel",
    "calle", "plaza", "barrio",  # Spanish geographic terms
})

TYPE_TO_FILE = {
    "PLACE": "places_full.json",
    "ORG": "orgs_full.json",
}

TYPE_TO_KEY = {
    "PLACE": "places_full",
    "ORG": "orgs_full",
}


def is_obvious_geographic(name: str) -> bool:
    """Return True if the canonical name contains a geographic keyword."""
    tokens = name.lower().split()
    return bool(set(tokens) & GEOGRAPHIC_KEYWORDS)


def load_context_for_cluster(
    entity_ids: list[str],
    original_type: str,
    search_dirs: list[str] | None = None,
    max_sentences: int = 3,
) -> list[str]:
    """
    Load up to max_sentences context snippets for the given entity_ids
    from the appropriate *_full.json file.

    search_dirs: directories to look for the JSON file (default: ["."]).
    Returns a flat list of sentence strings.
    """
    if search_dirs is None:
        search_dirs = ["."]

    filename = TYPE_TO_FILE.get(original_type)
    json_key = TYPE_TO_KEY.get(original_type)
    if not filename or not json_key:
        return []

    data: dict = {}
    for d in search_dirs:
        path = f"{d}/{filename}"
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f).get(json_key, {})
            break
        except (FileNotFoundError, json.JSONDecodeError):
            continue

    sentences: list[str] = []
    for eid in entity_ids:
        entity = data.get(eid, {})
        mentions_by_chapter = entity.get("mentions_by_chapter", {})
        for chapter_sents in mentions_by_chapter.values():
            sentences.extend(chapter_sents)
            if len(sentences) >= max_sentences:
                return sentences[:max_sentences]

    return sentences[:max_sentences]


def apply_corrections(clusters: list[dict], corrections: list[dict]) -> list[dict]:
    """
    Apply type corrections to clusters in-place (returns new list).
    corrections: [{cluster_id, from, to}]
    """
    correction_map = {c["cluster_id"]: c["to"] for c in corrections}
    result = []
    for cluster in clusters:
        cid = cluster["cluster_id"]
        if cid in correction_map:
            cluster = dict(cluster)
            cluster["type"] = correction_map[cid]
        result.append(cluster)
    return result


def _call_ollama(name: str, context_sentences: list[str], model: str) -> str | None:
    """
    Ask Ollama to classify `name` as PERSON, PLACE, or ORG.
    Returns "PERSON", "PLACE", "ORG", or None on failure.
    """
    try:
        import requests
    except ImportError:
        print("Warning: requests not available, skipping Ollama call", file=sys.stderr)
        return None

    context_text = " ".join(context_sentences)
    prompt = (
        f"Given these sentences from a novel, is '{name}' a person, "
        f"a place, or an organization? "
        f"Reply with exactly one word: PERSON, PLACE, or ORG.\n"
        f"Sentences: {context_text}"
    )

    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=30,
        )
        resp.raise_for_status()
        reply = resp.json().get("response", "").upper()
        for label in ("PERSON", "PLACE", "ORG"):
            if label in reply:
                return label
        return None
    except Exception as exc:
        print(f"Warning: Ollama call failed for '{name}': {exc}", file=sys.stderr)
        return None


def verify_clusters(
    clusters: list[dict],
    model: str = "mistral:7b-instruct",
    search_dirs: list[str] | None = None,
) -> list[dict]:
    """
    Identify and return corrections for clusters that should be reclassified.
    Returns list of {cluster_id, name, from, to, context_snippet}.
    """
    corrections = []

    for cluster in clusters:
        original_type = cluster.get("type", "OTHER")
        if original_type not in ("PLACE", "ORG"):
            continue

        name = cluster.get("canonical_candidate", "")
        if not name or is_obvious_geographic(name):
            continue

        entity_ids = cluster.get("entity_ids", [])
        context = load_context_for_cluster(entity_ids, original_type, search_dirs)
        if not context:
            continue

        new_type = _call_ollama(name, context, model)
        if new_type == "PERSON":
            snippet = context[0][:80] if context else ""
            print(
                f"[VERIFY] {name}: {original_type} → PERSON "
                f"(context: \"{snippet}...\")",
                file=sys.stderr,
            )
            corrections.append({
                "cluster_id": cluster["cluster_id"],
                "name": name,
                "from": original_type,
                "to": "PERSON",
                "context_snippet": snippet,
            })

    return corrections


def main() -> None:
    payload = json.load(sys.stdin)
    input_data = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    enabled = input_data.get("verify_entity_types", False)

    clustering_output = payload.get("previous_outputs", {}).get("entity-clustering", {})
    clusters = clustering_output.get("clusters", [])
    stats = clustering_output.get("stats", {})

    if not enabled:
        json.dump(
            {"clusters": clusters, "stats": stats, "type_corrections": []},
            sys.stdout,
            ensure_ascii=False,
        )
        return

    model = input_data.get("ollama_model", "mistral:7b-instruct")
    corrections = verify_clusters(clusters, model=model)
    corrected_clusters = apply_corrections(clusters, corrections)

    json.dump(
        {
            "clusters": corrected_clusters,
            "stats": stats,
            "type_corrections": corrections,
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
```

**Step 2: Run the tests**

```bash
pytest tests/test_verify_entity_types.py -v
```

Expected: all tests PASS (no Ollama needed — tests stub the pure logic).

**Step 3: Commit**

```bash
git add scripts/verify_entity_types.py
git commit -m "feat(stu-246): implement verify_entity_types pure logic"
```

---

### Task 3: Create the Studio contract

**Files:**
- Create: `.studio/contracts/verify-entity-types.contract.yaml`

**Step 1: Write the contract**

```yaml
name: verify-entity-types
version: 1
schema:
  required_fields:
    - clusters
    - stats
    - type_corrections
# type_corrections: list of {cluster_id, name, from, to, context_snippet}
# Empty list when verify_entity_types is false or no corrections found.
```

**Step 2: Commit**

```bash
git add .studio/contracts/verify-entity-types.contract.yaml
git commit -m "feat(stu-246): add verify-entity-types contract"
```

---

### Task 4: Insert stage in `wiki-extraction.pipeline.yaml`

**Files:**
- Modify: `.studio/pipelines/wiki-extraction.pipeline.yaml`

**Step 1: Insert the new stage between `entity-clustering` and `split-clusters`**

Current order: `epub-parse` → `entity-extraction` → `entity-clustering` → `split-clusters`
New order: `epub-parse` → `entity-extraction` → `entity-clustering` → `verify-entity-types` → `split-clusters`

Add after the `entity-clustering` block:

```yaml
  - name: verify-entity-types
    kind: extraction
    executor: script
    runtime: python
    script: scripts/verify_entity_types.py
    contract: verify-entity-types
    context:
      include:
        - input
        - previous_stage_output
```

**Step 2: Update `split-clusters` context**

`split-clusters` currently reads `previous_stage_output` (which was `entity-clustering`). After insertion, `previous_stage_output` will be `verify-entity-types` — which emits the same shape. No change needed to `split_clusters.py`. Verify the pipeline YAML still has `split-clusters` reading `previous_stage_output`.

**Step 3: Verify the final pipeline YAML looks correct**

```yaml
stages:
  - name: epub-parse
    ...
  - name: entity-extraction
    ...
  - name: entity-clustering
    ...
  - name: verify-entity-types      # ← new
    kind: extraction
    executor: script
    runtime: python
    script: scripts/verify_entity_types.py
    contract: verify-entity-types
    context:
      include:
        - input
        - previous_stage_output
  - name: split-clusters
    ...
```

**Step 4: Run the full test suite to check for regressions**

```bash
pytest tests/ -v
```

Expected: all existing tests still PASS.

**Step 5: Commit**

```bash
git add .studio/pipelines/wiki-extraction.pipeline.yaml
git commit -m "feat(stu-246): insert verify-entity-types stage in wiki-extraction pipeline"
```

---

### Task 5: Add pass-through integration test

**Files:**
- Modify: `tests/test_verify_entity_types.py`

**Step 1: Add integration test for the pass-through mode (no Ollama)**

Add at the end of `tests/test_verify_entity_types.py`:

```python
# --- pass-through integration (no Ollama) ---

def test_passthrough_mode_via_main(monkeypatch, capsys):
    """When verify_entity_types is false, output equals input clusters."""
    import io
    clusters = [
        {"cluster_id": "single_entity_042", "type": "PLACE",
         "canonical_candidate": "Barrido", "all_mentions": ["Barrido"],
         "entity_ids": ["entity_042"], "entity_count": 1, "total_mentions": 5}
    ]
    payload = {
        "additional_context": "verify_entity_types: false",
        "previous_outputs": {
            "entity-clustering": {
                "clusters": clusters,
                "stats": {"input_entities": 1, "total_items": 1}
            }
        }
    }
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(
        io.BytesIO(json.dumps(payload).encode()), encoding="utf-8"
    ))
    captured_output = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured_output)

    from scripts.verify_entity_types import main
    main()

    result = json.loads(captured_output.getvalue())
    assert result["type_corrections"] == []
    assert result["clusters"][0]["type"] == "PLACE"  # unchanged
```

**Step 2: Run the new test**

```bash
pytest tests/test_verify_entity_types.py::test_passthrough_mode_via_main -v
```

Expected: PASS.

**Step 3: Run full suite**

```bash
pytest tests/ -v
```

Expected: all PASS.

**Step 4: Commit**

```bash
git add tests/test_verify_entity_types.py
git commit -m "test(stu-246): add pass-through integration test for verify_entity_types"
```

---

### Task 6: Update the input YAML for Le Jeu de l'Ange

**Files:**
- Modify: relevant `*.input.yaml` in `.studio/inputs/`

**Step 1: Find the input file for Le Jeu de l'Ange**

```bash
ls .studio/inputs/
```

Look for the input file used for *Le Jeu de l'Ange* (likely `jeu-de-lange.input.yaml` or similar).

**Step 2: Add the flag**

In the input YAML, add:

```yaml
verify_entity_types: true
ollama_model: mistral:7b-instruct
```

**Step 3: Commit**

```bash
git add .studio/inputs/<filename>.input.yaml
git commit -m "feat(stu-246): enable verify_entity_types for Le Jeu de l'Ange"
```

---

### Task 7: Final check — run full test suite + create PR

**Step 1: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all PASS, no regressions.

**Step 2: Check mypy**

```bash
mypy scripts/verify_entity_types.py
```

Fix any type errors before proceeding.

**Step 3: Create PR**

Branch should be `arianedguay/stu-246-verification-de-coherence-de-type-ner-apres-clustering` (matches Linear git branch name).

```bash
git push -u origin arianedguay/stu-246-verification-de-coherence-de-type-ner-apres-clustering
gh pr create \
  --title "feat(stu-246): verify entity types after clustering" \
  --body "Adds optional verify-entity-types stage between entity-clustering and split-clusters. Uses mistral:7b-instruct via Ollama to detect PERSON entities misclassified as PLACE/ORG by spaCy (e.g. Barrido in Le Jeu de l'Ange). Activated via verify_entity_types: true in input YAML." \
  --base main
```
