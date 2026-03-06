# STU-188 — Contracts de validation : un contract par stage

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ajouter un contract de validation par stage du pipeline wiki-creator, corriger les contracts erronés, et ajouter les guards sémantiques dans les scripts.

**Architecture:** Les contracts RALPH valident uniquement la présence des champs top-level (`schema.required_fields`). Les invariants sémantiques (non-vide, réduction effective) vivent dans les scripts comme early exits. 2 nouveaux contracts, 2 corrections/mises à jour, 3 stages câblés dans le pipeline, 2 guards dans les scripts.

**Tech Stack:** Python 3, pytest, YAML, Studio RALPH validator

---

### Task 1 : Worktree pour STU-188

**Files:**
- N/A (commande git seulement)

**Step 1: Créer le worktree**

```bash
git worktree add .worktrees/stu-188-contracts -b feat/stu-188-contracts
cd .worktrees/stu-188-contracts
```

**Step 2: Vérifier qu'on est sur la bonne branche**

```bash
git branch
```
Expected: `* feat/stu-188-contracts`

---

### Task 2 : Créer `epub-parse.contract.yaml`

**Files:**
- Create: `.studio/contracts/epub-parse.contract.yaml`

**Step 1: Vérifier l'output réel du script**

Ouvrir `scripts/parse_epub.py` ligne 152 — le script retourne `title`, `author`, `chapters`, `pov_detection`. Le champ STU-188 l'appelle `pov` — c'est incorrect, le vrai nom est `pov_detection`. `author` est nullable → ne pas inclure dans required_fields.

**Step 2: Créer le fichier**

```yaml
name: epub-parse
version: 1
schema:
  required_fields:
    - title
    - chapters
    - pov_detection
# Semantic guard: chapters not empty — checked in script (parse_epub.py)
```

**Step 3: Commit**

```bash
git add .studio/contracts/epub-parse.contract.yaml
git commit -m "feat(stu-188): add epub-parse contract"
```

---

### Task 3 : Créer `wiki-export.contract.yaml`

**Files:**
- Create: `.studio/contracts/wiki-export.contract.yaml`

**Step 1: Vérifier l'output réel du script**

Ouvrir `scripts/wiki_export.py` ligne 100 — `json.dump({"files_written": files_written, "wiki_dir": str(wiki_dir)}, sys.stdout)`.

**Step 2: Créer le fichier**

```yaml
name: wiki-export
version: 1
schema:
  required_fields:
    - files_written
    - wiki_dir
```

**Step 3: Commit**

```bash
git add .studio/contracts/wiki-export.contract.yaml
git commit -m "feat(stu-188): add wiki-export contract"
```

---

### Task 4 : Corriger `entity-extraction.contract.yaml`

**Files:**
- Modify: `.studio/contracts/entity-extraction.contract.yaml`

**Step 1: Vérifier le bug**

Ouvrir le fichier actuel — il déclare `required_fields: [entities]`. Ouvrir `scripts/entity_extraction.py` ligne 372 — le script output `{"entities_for_resolution": ...}`. Le champ `entities` n'existe pas.

**Step 2: Corriger**

Remplacer le contenu par :

```yaml
name: entity-extraction
version: 1
schema:
  required_fields:
    - entities_for_resolution
# Semantic guard: entities_for_resolution not empty — checked in script (entity_extraction.py)
```

**Step 3: Commit**

```bash
git add .studio/contracts/entity-extraction.contract.yaml
git commit -m "fix(stu-188): entity-extraction contract — entities_for_resolution (was entities)"
```

---

### Task 5 : Mettre à jour `entity-resolution.contract.yaml`

**Files:**
- Modify: `.studio/contracts/entity-resolution.contract.yaml`

**Step 1: Vérifier l'output du resolver**

Ouvrir `.studio/agents/resolver.agent.yaml` ligne 68-72 — le resolver produit `{"entities": [...], "narrator": {...} | null}`. Le `narrator` est toujours présent (objet ou null). Le contract actuel ne le déclare pas.

**Step 2: Ajouter narrator**

```yaml
name: entity-resolution
version: 1
schema:
  required_fields:
    - entities
    - narrator
# narrator: null pour POV omniscient/troisième personne
# Chaque entité : canonical_name, type, aliases, source_ids, relevant
```

**Step 3: Commit**

```bash
git add .studio/contracts/entity-resolution.contract.yaml
git commit -m "feat(stu-188): entity-resolution contract — add narrator field"
```

---

### Task 6 : Annoter `entity-clustering.contract.yaml`

**Files:**
- Modify: `.studio/contracts/entity-clustering.contract.yaml`

**Step 1: Vérifier l'output réel**

Ouvrir `scripts/entity_clustering.py` ligne 455-464 — output : `{"clusters": [...], "stats": {input_entities, output_clusters, unclustered_wrapped, total_items, reduction_pct}}`. Le contract actuel est correct mais manque une annotation sur le guard.

**Step 2: Ajouter le commentaire**

```yaml
name: entity-clustering
version: 1
schema:
  required_fields:
    - clusters
    - stats
# Semantic guard: if stats.reduction_pct == 0 and stats.input_entities > 10 → stderr warning
# Guard is checked in script (entity_clustering.py), not enforced here (valid for small books)
```

**Step 3: Commit**

```bash
git add .studio/contracts/entity-clustering.contract.yaml
git commit -m "docs(stu-188): entity-clustering contract — annotate reduction_pct guard"
```

---

### Task 7 : Câbler les contracts manquants dans le pipeline

**Files:**
- Modify: `.studio/pipelines/wiki-pipeline.pipeline.yaml`

**Step 1: Identifier les stages sans contract**

Ouvrir le fichier. Trois stages n'ont pas de ligne `contract:` :
- `epub-parse` (ligne 6)
- `entity-extraction` (ligne 15)
- `wiki-export` (ligne 85)

**Step 2: Ajouter `contract:` à chaque stage**

Pour `epub-parse` (après `script: scripts/parse_epub.py`) :
```yaml
    contract: epub-parse
```

Pour `entity-extraction` (après `script: scripts/entity_extraction.py`) :
```yaml
    contract: entity-extraction
```

Pour `wiki-export` (après `script: scripts/wiki_export.py`) :
```yaml
    contract: wiki-export
```

Le fichier final doit avoir `contract:` sur les 8 stages.

**Step 3: Vérifier que le YAML est valide**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/pipelines/wiki-pipeline.pipeline.yaml'))"
```
Expected: pas d'erreur

**Step 4: Commit**

```bash
git add .studio/pipelines/wiki-pipeline.pipeline.yaml
git commit -m "feat(stu-188): wire epub-parse, entity-extraction, wiki-export contracts in pipeline"
```

---

### Task 8 : Guard non-vide dans `entity_extraction.py`

**Files:**
- Modify: `scripts/entity_extraction.py`
- Test: `tests/test_entity_extraction.py`

**Step 1: Écrire le test en premier**

Ajouter à la fin de `tests/test_entity_extraction.py` :

```python
def test_main_exits_on_empty_entities():
    """main() must exit 1 with error JSON when no entities are extracted."""
    import subprocess
    import json as _json

    # Chapters whose content produces zero named entities (no PERSON/PLACE/ORG)
    payload = _json.dumps({
        "additional_context": "spacy_model: en_core_web_sm",
        "previous_outputs": {
            "epub-parse": {
                "title": "Test",
                "author": None,
                "chapters": [
                    {"id": "ch01", "title": "Ch1", "content": "It was 42 degrees. The year was 1900."},
                ],
            }
        },
    })
    result = subprocess.run(
        [sys.executable, "scripts/entity_extraction.py"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}. stdout={result.stdout}"
    output = _json.loads(result.stdout)
    assert "error" in output, f"Expected error field in output: {output}"
    assert "no entities" in output["error"].lower(), f"Unexpected error message: {output['error']}"
```

**Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
pytest tests/test_entity_extraction.py::test_main_exits_on_empty_entities -v
```
Expected: FAIL (le guard n'existe pas encore)

**Step 3: Ajouter le guard dans `entity_extraction.py`**

Dans `main()`, après la ligne `entities_for_resolution, entities_full = split_entities(result["entities"])` (ligne ~356), ajouter :

```python
    if not entities_for_resolution:
        json.dump({"error": "no entities extracted — verify spaCy model and input chapters"}, sys.stdout)
        sys.exit(1)
```

**Step 4: Lancer le test pour vérifier qu'il passe**

```bash
pytest tests/test_entity_extraction.py::test_main_exits_on_empty_entities -v
```
Expected: PASS

**Step 5: Vérifier que les tests existants passent toujours**

```bash
pytest tests/test_entity_extraction.py -v
```
Expected: tous PASS

**Step 6: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat(stu-188): entity_extraction — exit 1 when entities_for_resolution is empty"
```

---

### Task 9 : Warning `reduction_pct` dans `entity_clustering.py`

**Files:**
- Modify: `scripts/entity_clustering.py`
- Test: `tests/test_entity_clustering.py`

**Step 1: Écrire le test en premier**

Ajouter à la fin de `tests/test_entity_clustering.py` :

```python
def test_main_warns_when_no_reduction_and_many_entities():
    """main() must print a stderr warning when reduction_pct==0 with >10 input entities."""
    import subprocess
    import json as _json

    # 11 completely unique entities — nothing will cluster
    entities = {
        f"entity_{i:03d}": {
            "type": "PERSON",
            "raw_mentions": [f"UniqueNameXyz{i:02d}"],
            "first_seen": f"ch{i:02d}",
            "mention_count": 1,
        }
        for i in range(1, 12)  # 11 entities
    }
    payload = _json.dumps({
        "additional_context": "",
        "previous_outputs": {
            "entity-extraction": {
                "entities_for_resolution": entities,
            }
        },
    })
    result = subprocess.run(
        [sys.executable, "scripts/entity_clustering.py"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr={result.stderr}"
    assert "reduction_pct=0" in result.stderr, (
        f"Expected reduction_pct warning in stderr. Got: {result.stderr!r}"
    )
```

**Step 2: Lancer le test pour vérifier qu'il échoue**

```bash
pytest tests/test_entity_clustering.py::test_main_warns_when_no_reduction_and_many_entities -v
```
Expected: FAIL

**Step 3: Ajouter le warning dans `entity_clustering.py`**

Dans `main()`, après la construction de `result` (ligne ~464, avant `json.dump`), ajouter :

```python
    if result["stats"]["reduction_pct"] == 0 and result["stats"]["input_entities"] > 10:
        print(
            f"Warning: reduction_pct=0 with {result['stats']['input_entities']} input entities — "
            "no clustering occurred, check clustering thresholds",
            file=sys.stderr,
        )
```

**Step 4: Lancer le test pour vérifier qu'il passe**

```bash
pytest tests/test_entity_clustering.py::test_main_warns_when_no_reduction_and_many_entities -v
```
Expected: PASS

**Step 5: Vérifier que les tests existants passent toujours**

```bash
pytest tests/test_entity_clustering.py -v
```
Expected: tous PASS

**Step 6: Commit**

```bash
git add scripts/entity_clustering.py tests/test_entity_clustering.py
git commit -m "feat(stu-188): entity_clustering — warn on stderr when reduction_pct=0 with >10 entities"
```

---

### Task 10 : Vérification finale

**Step 1: Lancer tous les tests**

```bash
pytest
```
Expected: tous PASS, aucune régression

**Step 2: Vérifier que tous les stages ont leur contract dans le pipeline**

```bash
grep "contract:" .studio/pipelines/wiki-pipeline.pipeline.yaml
```
Expected: 8 lignes (une par stage)

**Step 3: Vérifier que tous les contracts existent**

```bash
ls .studio/contracts/
```
Expected: `entity-classification.contract.yaml`, `entity-clustering.contract.yaml`, `entity-extraction.contract.yaml`, `entity-resolution.contract.yaml`, `epub-parse.contract.yaml`, `relationship-extraction.contract.yaml`, `wiki-export.contract.yaml`, `wiki-generation.contract.yaml`

**Step 4: Type checking**

```bash
mypy wiki_creator/
```
Expected: pas d'erreurs

**Step 5: Commit final si des ajustements ont été faits**

```bash
git add -A
git commit -m "chore(stu-188): final verification pass"
```
