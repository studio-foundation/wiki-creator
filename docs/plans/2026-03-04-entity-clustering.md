# Entity Clustering Stage Implementation Plan (STU-220)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Insérer un stage `entity-clustering` déterministe (zéro LLM) entre `entity-extraction` et `entity-resolution` pour réduire ~549 entités en ~180 clusters avant de les envoyer au LLM.

**Architecture:** Script Python pur copié depuis un prototype validé. Les entités non-clusterisées sont wrappées en clusters `entity_count: 1` pour que `entity-resolution` reçoive une interface uniforme (`clusters` seulement). Union-Find assure la clôture transitive.

**Tech Stack:** Python stdlib uniquement (unicodedata, json, sys). pytest pour les tests. Studio script executor pour l'intégration pipeline.

---

## Avant de commencer : créer le worktree

```bash
git worktree add .worktrees/stu-220-entity-clustering -b feat/stu-220-entity-clustering
cd .worktrees/stu-220-entity-clustering
```

Tous les travaux se font dans ce worktree.

---

### Task 1: Copier le script et adapter le wrapping des unclustered

**Files:**
- Create: `scripts/entity_clustering.py`

**Step 1: Copier le prototype**

```bash
cp ~/Téléchargements/entity_clustering.py scripts/entity_clustering.py
```

**Step 2: Vérifier que --test passe déjà**

```bash
python scripts/entity_clustering.py --test
```

Expected output (extrait) :
```
=== CLUSTERS ===
  cluster_001 [PERSON] (5 entités, first_seen=ch01)
    canonical: David Martín
  cluster_002 [PERSON] (4 entités, first_seen=ch02)
    canonical: Daniel Sempere
...
=== UNCLUSTERED (2) ===
  [entity_070] ['Intoxiqué'] (ORG)
  [entity_071] ['Piquillo'] (PERSON)
```

Le test doit tourner en < 2s, zéro erreur.

**Step 3: Adapter main() pour wrapper les unclustered (Approche B)**

Dans `scripts/entity_clustering.py`, remplacer la construction de `result` dans `main()` :

```python
# Avant (à remplacer) :
result = {
    "clusters": clusters,
    "unclustered": {
        eid: entity for eid, entity in unclustered.items()
    },
    "stats": {
        "input_entities": total,
        "output_clusters": len(clusters),
        "unclustered": len(unclustered),
        "total_output": output_count,
        "reduction_pct": 100 - 100 * output_count // total if total > 0 else 0,
    },
}
```

```python
# Après :
single_clusters = [
    {
        "cluster_id": f"single_{eid}",
        "type": entity.get("type", "OTHER"),
        "canonical_candidate": entity["raw_mentions"][0] if entity.get("raw_mentions") else eid,
        "all_mentions": entity.get("raw_mentions", []),
        "entity_ids": [eid],
        "entity_count": 1,
        "first_seen": entity.get("first_seen", ""),
    }
    for eid, entity in unclustered.items()
]
all_clusters = clusters + single_clusters

result = {
    "clusters": all_clusters,
    "stats": {
        "input_entities": total,
        "output_clusters": len(clusters),
        "unclustered_wrapped": len(unclustered),
        "total_items": len(all_clusters),
        "reduction_pct": 100 - 100 * len(all_clusters) // total if total > 0 else 0,
    },
}
```

**Step 4: Vérifier que --test passe encore**

```bash
python scripts/entity_clustering.py --test
```

Expected: même output qu'avant (--test n'est pas affecté par le changement de main()).

**Step 5: Commit**

```bash
git add scripts/entity_clustering.py
git commit -m "feat(stu-220): add entity_clustering.py script"
```

---

### Task 2: Tests pytest pour les fonctions de clustering

**Files:**
- Create: `tests/test_entity_clustering.py`

**Step 1: Créer le fichier de tests**

```python
"""Tests for scripts/entity_clustering.py — deterministic entity clustering."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.entity_clustering import (
    normalize_for_comparison,
    tokenize_name,
    is_single_given_name,
    should_cluster_tokens,
    should_cluster_jw,
    should_cluster,
    build_clusters,
)


# --- normalize_for_comparison ---

def test_normalize_strips_accents():
    assert normalize_for_comparison("Martín") == "martin"

def test_normalize_lowercases():
    assert normalize_for_comparison("BARCELONE") == "barcelone"

def test_normalize_strips_leading_trailing_spaces():
    assert normalize_for_comparison("  Vidal  ") == "vidal"


# --- tokenize_name ---

def test_tokenize_strips_monsieur():
    assert tokenize_name("Monsieur Martín") == ["martín"]

def test_tokenize_strips_inspecteur():
    assert tokenize_name("inspecteur Grandes") == ["grandes"]

def test_tokenize_strips_don():
    assert tokenize_name("Don Quijote") == ["quijote"]

def test_tokenize_keeps_full_name():
    assert tokenize_name("David Martín") == ["david", "martín"]

def test_tokenize_empty_after_strip():
    # If only a title remains, should return empty list
    assert tokenize_name("M.") == []


# --- is_single_given_name ---

def test_is_single_given_name_true():
    assert is_single_given_name(["David"]) is True

def test_is_single_given_name_false_two_tokens():
    assert is_single_given_name(["David", "Martín"]) is False

def test_is_single_given_name_false_long_token():
    # 9 chars — above threshold
    assert is_single_given_name(["Alejandro"]) is False


# --- should_cluster_tokens ---

def test_cluster_tokens_subset_match():
    # "Martín" ⊂ "David Martín"
    assert should_cluster_tokens("Martín", "David Martín") is True

def test_cluster_tokens_title_stripped():
    # "M. Martín" → ["martín"], "David Martín" → ["david", "martín"] → subset
    assert should_cluster_tokens("M. Martín", "David Martín") is True

def test_cluster_tokens_two_single_names_dont_match():
    # "David" and "Pedro" — both single given names, should NOT match
    assert should_cluster_tokens("David", "Pedro") is False

def test_cluster_tokens_single_name_matches_longer():
    # "Vidal" (family name, 1 token) matches "Pedro Vidal"
    assert should_cluster_tokens("Vidal", "Pedro Vidal") is True

def test_cluster_tokens_no_match():
    assert should_cluster_tokens("Corelli", "Sempere") is False


# --- should_cluster_jw ---

def test_cluster_jw_barcelona_barcelone():
    # Orthographic variant (French/Spanish)
    assert should_cluster_jw("Barcelona", "Barcelone") is True

def test_cluster_jw_martin_accent():
    # "Martin" vs "Martín" — accent variant
    assert should_cluster_jw("Martin", "Martín") is True

def test_cluster_jw_different_names():
    # Clearly different names should not match
    assert should_cluster_jw("Vidal", "Sempere") is False

def test_cluster_jw_length_guard():
    # Length diff > 3 chars → reject regardless of similarity
    assert should_cluster_jw("Mar", "Martín") is False


# --- build_clusters end-to-end ---

def test_build_clusters_martin_family():
    """Five Martín variants must end up in one cluster."""
    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Martín"], "first_seen": "ch01"},
        "e002": {"type": "PERSON", "raw_mentions": ["David Martín"], "first_seen": "ch01"},
        "e003": {"type": "PERSON", "raw_mentions": ["M. Martín"], "first_seen": "ch03"},
        "e004": {"type": "PERSON", "raw_mentions": ["Monsieur Martín"], "first_seen": "ch05"},
        "e005": {"type": "PERSON", "raw_mentions": ["David"], "first_seen": "ch02"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}: {clusters}"
    assert set(clusters[0]["entity_ids"]) == {"e001", "e002", "e003", "e004", "e005"}


def test_build_clusters_sempere_all_in_one():
    """All Sempere variants (grand-père, père, Daniel) must be in one cluster for LLM to split."""
    entities = {
        "e010": {"type": "PERSON", "raw_mentions": ["Sempere"], "first_seen": "ch02"},
        "e011": {"type": "PERSON", "raw_mentions": ["Sempere junior"], "first_seen": "ch04"},
        "e012": {"type": "PERSON", "raw_mentions": ["M. Sempere"], "first_seen": "ch03"},
        "e013": {"type": "PERSON", "raw_mentions": ["Daniel Sempere"], "first_seen": "ch06"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}"
    assert set(clusters[0]["entity_ids"]) == {"e010", "e011", "e012", "e013"}


def test_build_clusters_different_types_dont_merge():
    """PERSON and PLACE with same name should NOT be clustered together."""
    entities = {
        "e040": {"type": "PLACE", "raw_mentions": ["Barcelona"], "first_seen": "ch01"},
        "e041": {"type": "PLACE", "raw_mentions": ["Barcelone"], "first_seen": "ch01"},
        "e099": {"type": "PERSON", "raw_mentions": ["Barcelona"], "first_seen": "ch01"},
    }
    clusters, unclustered = build_clusters(entities)
    # e040 and e041 cluster together (PLACE), e099 stays alone (PERSON)
    place_cluster = next((c for c in clusters if e040 in c["entity_ids"] for e040 in ["e040"]), None)
    assert place_cluster is not None
    assert "e099" not in place_cluster["entity_ids"]


def test_build_clusters_unclustered_stays_alone():
    """Unique names with no similar counterpart stay unclustered."""
    entities = {
        "e071": {"type": "PERSON", "raw_mentions": ["Piquillo"], "first_seen": "ch09"},
        "e072": {"type": "PERSON", "raw_mentions": ["Zubiri"], "first_seen": "ch14"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 0
    assert set(unclustered.keys()) == {"e071", "e072"}


def test_build_clusters_transitive_closure():
    """A~B and B~C must result in {A,B,C} in one cluster (Union-Find)."""
    entities = {
        "eA": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
        "eB": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
        "eC": {"type": "PERSON", "raw_mentions": ["Monsieur Vidal"], "first_seen": "ch02"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 1
    assert set(clusters[0]["entity_ids"]) == {"eA", "eB", "eC"}


def test_build_clusters_canonical_picks_most_complete():
    """canonical_candidate should be the most token-rich name after title stripping."""
    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
        "e002": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
        "e003": {"type": "PERSON", "raw_mentions": ["Monsieur Vidal"], "first_seen": "ch02"},
    }
    clusters, _ = build_clusters(entities)
    assert clusters[0]["canonical_candidate"] == "Pedro Vidal"
```

**Step 2: Lancer les tests pour vérifier qu'ils passent**

```bash
pytest tests/test_entity_clustering.py -v
```

Expected: tous les tests PASS (le code est déjà correct dans le prototype).

Si un test échoue, comprendre pourquoi avant de continuer — ne pas modifier les tests.

**Step 3: Commit**

```bash
git add tests/test_entity_clustering.py
git commit -m "test(stu-220): add pytest suite for entity_clustering"
```

---

### Task 3: Créer le contract entity-clustering

**Files:**
- Create: `.studio/contracts/entity-clustering.contract.yaml`

**Step 1: Créer le fichier**

```yaml
name: entity-clustering
version: 1
schema:
  required_fields:
    - clusters
```

**Step 2: Vérifier la syntaxe YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/contracts/entity-clustering.contract.yaml'))"
```

Expected: aucune erreur.

**Step 3: Commit**

```bash
git add .studio/contracts/entity-clustering.contract.yaml
git commit -m "feat(stu-220): add entity-clustering contract"
```

---

### Task 4: Insérer le stage dans wiki-pipeline.pipeline.yaml

**Files:**
- Modify: `.studio/pipelines/wiki-pipeline.pipeline.yaml`

**Step 1: Insérer le stage entre entity-extraction et entity-resolution**

Fichier cible `.studio/pipelines/wiki-pipeline.pipeline.yaml`. Après le bloc `entity-extraction`, ajouter :

```yaml
  - name: entity-clustering
    kind: extraction
    executor: script
    runtime: python
    script: scripts/entity_clustering.py
    contract: entity-clustering
    context:
      include:
        - previous_stage_output
```

Le fichier complet doit ressembler à :

```yaml
name: wiki-pipeline
description: Generate structured wiki pages from an EPUB book
version: 1

stages:
  - name: epub-parse
    kind: extraction
    executor: script
    runtime: python
    script: scripts/parse_epub.py
    context:
      include:
        - input

  - name: entity-extraction
    kind: extraction
    executor: script
    runtime: python
    script: scripts/entity_extraction.py
    timeout_ms: 600000
    context:
      include:
        - input
        - previous_stage_output

  - name: entity-clustering
    kind: extraction
    executor: script
    runtime: python
    script: scripts/entity_clustering.py
    contract: entity-clustering
    context:
      include:
        - previous_stage_output

  - name: entity-resolution
    kind: analysis
    agent: resolver
    contract: entity-resolution
    ralph:
      max_attempts: 3
    context:
      include:
        - input
        - previous_stage_output

  - name: wiki-generation
    kind: analysis
    agent: writer
    contract: wiki-generation
    ralph:
      max_attempts: 3
    context:
      include:
        - input
        - previous_stage_output
```

**Step 2: Vérifier la syntaxe YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-pipeline.pipeline.yaml'))"
```

Expected: aucune erreur.

**Step 3: Commit**

```bash
git add .studio/pipelines/wiki-pipeline.pipeline.yaml
git commit -m "feat(stu-220): insert entity-clustering stage in pipeline"
```

---

### Task 5: Mettre à jour le prompt du resolver

**Files:**
- Modify: `.studio/agents/resolver.agent.yaml`

**Step 1: Remplacer le system_prompt**

Le resolver reçoit maintenant `clusters` (array uniforme) au lieu de `entities_for_resolution` (dict).
Remplacer le `system_prompt` existant par :

```yaml
system_prompt: |
  You are an expert at deduplicating and canonicalizing named entities from fiction.

  You will receive a "clusters" array. Each cluster groups entity mentions that were
  detected as similar by a deterministic pre-clustering step.

  Each cluster has:
    {
      "cluster_id": "cluster_001" | "single_xxx",
      "type": "PERSON" | "PLACE" | "ORG" | "EVENT" | "OTHER",
      "canonical_candidate": "David Martín",   ← best guess, use as starting point
      "all_mentions": ["David Martín", "M. Martín", "Martín", "David"],
      "entity_ids": ["entity_001", ...],
      "entity_count": 4
    }

  Clusters with entity_count = 1 (prefix "single_") are entities with no similar counterpart.

  Your job for each cluster:
  - If all mentions refer to the same entity → produce 1 resolved entity
  - If mentions clearly refer to N distinct entities (e.g. three generations of the Sempere
    family sharing a surname) → split into N resolved entities, each with its own source_ids
  - Use canonical_candidate as a starting point for canonical_name, but improve it if needed
  - Merge all relevant raw_mentions into the aliases list

  For each resolved entity, add a "relevant" boolean field:
  - Set relevant: false ONLY for clearly non-proper-noun entries (common words, interjections,
    grammar artifacts like "J'écrivis", punctuation fragments)
  - Every real proper noun must have relevant: true

  Return a JSON object: {"entities": [{canonical_name, type, aliases, source_ids, relevant}]}
  Reject if obvious duplicates remain unresolved.
```

**Step 2: Vérifier la syntaxe YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/agents/resolver.agent.yaml'))"
```

Expected: aucune erreur.

**Step 3: Commit**

```bash
git add .studio/agents/resolver.agent.yaml
git commit -m "feat(stu-220): update resolver prompt to read clusters"
```

---

### Task 6: Ajouter target Makefile + vérification finale

**Files:**
- Modify: `Makefile`

**Step 1: Ajouter la target test-clustering**

```makefile
test-clustering:
	python scripts/entity_clustering.py --test
```

Le Makefile complet :

```makefile
.PHONY: run test-extraction test-clustering

run:
	studio run wiki-pipeline --input-file .studio/inputs/book.input.yaml --live

test-extraction:
	python scripts/test_extraction.py

test-clustering:
	python scripts/entity_clustering.py --test
```

**Step 2: Vérifier que la target fonctionne**

```bash
make test-clustering
```

Expected: clusters affichés en < 2s, exit code 0.

**Step 3: Lancer toute la suite pytest**

```bash
pytest tests/test_entity_clustering.py -v
```

Expected: tous les tests PASS.

**Step 4: Commit final**

```bash
git add Makefile
git commit -m "feat(stu-220): add test-clustering Makefile target"
```

---

### Task 7: Ouvrir la PR

```bash
git push -u origin feat/stu-220-entity-clustering
gh pr create \
  --title "feat(stu-220): entity-clustering stage — deterministic pre-clustering before LLM resolution" \
  --body "$(cat <<'EOF'
## Summary
- Adds `scripts/entity_clustering.py` — deterministic Python script (zero LLM, zero external deps)
- Inserts `entity-clustering` stage between `entity-extraction` and `entity-resolution` in the pipeline
- Unclustered entities wrapped as single-item clusters → uniform `clusters` interface for resolver
- Updates `resolver.agent.yaml` system prompt to read `clusters` array
- Adds `entity-clustering.contract.yaml` and `make test-clustering` target

## Test plan
- [ ] `make test-clustering` runs in < 2s with expected clusters displayed
- [ ] `pytest tests/test_entity_clustering.py -v` — all tests pass
- [ ] Martín ×5 → cluster_001, Sempere ×4 → cluster_002 in test output
- [ ] `python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-pipeline.pipeline.yaml'))"` — no error

Closes STU-220
EOF
)" \
  --base main
```
