# STU-188 — Contracts de validation : un contract par stage

**Date:** 2026-03-06
**Ticket:** [STU-188](https://linear.app/studioag/issue/STU-188/contracts-de-validation-un-contract-par-stage-du-pipeline)

---

## Contexte

Chaque stage du pipeline produit un output JSON structuré. Sans contracts de validation, un output malformé passe silencieusement au stage suivant et provoque des erreurs en cascade.

RALPH (`ralph/src/validator.ts`) supporte uniquement :
- `schema.required_fields` — présence des champs top-level
- `tool_calls` — min/max, required_tools (pour stages LLM)
- `post_validation.rejection_detection` — détection de rejet

Les `custom_rules` et `min_items`/`min_length` sont définis dans le type TypeScript mais **non implémentés**. Les validations sémantiques (champs non vides, comparaisons numériques) doivent donc vivre dans les scripts comme early exits.

---

## Approche retenue : B — Contracts + guards dans les scripts

Les contracts valident la **forme** (présence des champs). Les scripts valident les **invariants** (non-vide, réduction effective).

---

## Section 1 — Fichiers contracts

### Nouveaux fichiers

**`.studio/contracts/epub-parse.contract.yaml`**
```yaml
name: epub-parse
version: 1
schema:
  required_fields:
    - title
    - chapters
    - pov_detection
# Semantic guard: chapters not empty — checked in script
```
Note : le champ réel est `pov_detection` (pas `pov` comme indiqué dans STU-188). `author` est nullable → absent de required_fields.

**`.studio/contracts/wiki-export.contract.yaml`**
```yaml
name: wiki-export
version: 1
schema:
  required_fields:
    - files_written
    - wiki_dir
```

### Fichier à corriger

**`.studio/contracts/entity-extraction.contract.yaml`**
Le contract actuel déclare `entities` — champ inexistant. Le script sort `entities_for_resolution`.
```yaml
name: entity-extraction
version: 1
schema:
  required_fields:
    - entities_for_resolution
# Semantic guard: entities_for_resolution not empty — checked in script
```

### Fichier à mettre à jour

**`.studio/contracts/entity-resolution.contract.yaml`**
Ajouter `narrator` (toujours présent — objet ou null selon POV).
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

### Fichiers inchangés (déjà corrects)

- `entity-clustering.contract.yaml` — ajouter commentaire sur le guard reduction_pct
- `relationship-extraction.contract.yaml`
- `wiki-generation.contract.yaml`
- `entity-classification.contract.yaml`

---

## Section 2 — Pipeline

Trois stages sans `contract:` à câbler :

| Stage | Ajouter |
|---|---|
| `epub-parse` | `contract: epub-parse` |
| `entity-extraction` | `contract: entity-extraction` |
| `wiki-export` | `contract: wiki-export` |

Les autres stages ont déjà leur `contract:`.

---

## Section 3 — Guards dans les scripts

### `scripts/entity_extraction.py`

Après construction de `entities_for_resolution`, avant l'écriture des fichiers :

```python
if not entities_for_resolution:
    json.dump({"error": "no entities extracted — verify spaCy model and input chapters"}, sys.stdout)
    sys.exit(1)
```

### `scripts/entity_clustering.py`

Warning stderr (pas un exit) si aucun clustering ne s'est produit sur un input significatif. `reduction_pct == 0` est valide pour un très petit livre — le seuil `> 10` évite les faux positifs :

```python
if result["stats"]["reduction_pct"] == 0 and result["stats"]["input_entities"] > 10:
    print(
        f"Warning: reduction_pct=0 with {result['stats']['input_entities']} input entities — "
        "no clustering occurred, check clustering thresholds",
        file=sys.stderr,
    )
```

---

## Fichiers touchés

| Fichier | Action |
|---|---|
| `.studio/contracts/epub-parse.contract.yaml` | Créer |
| `.studio/contracts/wiki-export.contract.yaml` | Créer |
| `.studio/contracts/entity-extraction.contract.yaml` | Corriger (`entities` → `entities_for_resolution`) |
| `.studio/contracts/entity-resolution.contract.yaml` | Ajouter `narrator` |
| `.studio/contracts/entity-clustering.contract.yaml` | Ajouter commentaire guard |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Ajouter `contract:` aux 3 stages manquants |
| `scripts/entity_extraction.py` | Guard non-vide |
| `scripts/entity_clustering.py` | Warning reduction_pct |
