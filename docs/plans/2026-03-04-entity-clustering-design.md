# Design : Stage entity-clustering (STU-220)

## Contexte

L'extraction produit ~549 entités dont beaucoup sont des variantes du même personnage
(`Martín`, `David Martín`, `M. Martín`, `Monsieur Martín`, `David` = 5 entrées pour 1 personnage).
L'entity-resolution (LLM) reçoit ces entités en vrac et échoue à cause du volume de tokens et du bruit.

## Solution

Insérer un stage déterministe `entity-clustering` entre `entity-extraction` et `entity-resolution`.
Script Python pur, zéro LLM, zéro dépendance externe.

## Architecture

```
epub-parse → entity-extraction → entity-clustering → entity-resolution → wiki-generation
                                        ↑
                              scripts/entity_clustering.py
                              (script executor, zéro LLM)
```

## Algorithmes (dans scripts/entity_clustering.py)

1. **Token overlap avec stripping de titres** — `M.`, `Monsieur`, `inspecteur`, `Don`, etc. sont
   retirés avant comparaison. Un nom est clusterisé avec un autre si ses tokens sont un sous-ensemble.
2. **Jaro-Winkler ≥ 0.92** — attrape les variantes orthographiques (`Barcelona` ↔ `Barcelone`).
3. **Union-Find transitif** — si A~B et B~C → {A,B,C} dans le même cluster.

Garde-fous :
- Prénoms seuls (1 token, ≤8 chars) ne matchent jamais entre eux
- Seules les entités du même type sont comparées (PERSON/PLACE/ORG)
- `canonical_candidate` préfère la forme la plus complète après stripping des titres

## Format de sortie (Approche B — clusters uniformes)

Les entités non-clusterisées sont wrappées en clusters `entity_count: 1` (`cluster_id: "single_<eid>"`).
Entity-resolution reçoit une interface uniforme — uniquement `clusters`.

```json
{
  "clusters": [
    {
      "cluster_id": "cluster_001",
      "type": "PERSON",
      "canonical_candidate": "David Martín",
      "all_mentions": ["David Martín", "M. Martín", "Martín", "David"],
      "entity_ids": ["entity_001", "entity_002", "entity_003", "entity_005"],
      "entity_count": 4,
      "first_seen": "ch01"
    },
    {
      "cluster_id": "single_070",
      "type": "ORG",
      "canonical_candidate": "Intoxiqué",
      "all_mentions": ["Intoxiqué"],
      "entity_ids": ["entity_070"],
      "entity_count": 1,
      "first_seen": "ch05"
    }
  ],
  "stats": {
    "input_entities": 549,
    "output_clusters": 42,
    "unclustered_wrapped": 130,
    "reduction_pct": 67
  }
}
```

## Changements par fichier

| Fichier | Action |
|---|---|
| `scripts/entity_clustering.py` | Copier depuis prototype + adapter wrapping unclustered |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Insérer stage `entity-clustering` |
| `.studio/contracts/entity-clustering.contract.yaml` | Créer (valide `clusters`) |
| `.studio/agents/resolver.agent.yaml` | Mettre à jour le prompt (lit `clusters` au lieu de `entities_for_resolution`) |

## Détail : pipeline YAML

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

Inséré entre `entity-extraction` et `entity-resolution`.

## Détail : nouveau prompt resolver

Le resolver reçoit `clusters`. Pour chaque cluster, il décide combien de personnages distincts
il représente (1 pour les aliases, N pour les personnages homonymes comme les 3 Sempere).

```
You receive a "clusters" array. Each cluster groups entity mentions that look similar.
A cluster with entity_count > 1 may represent 1 entity (aliases) OR multiple distinct
entities sharing a name (e.g. three Sempere generations).

For each cluster:
- If all mentions refer to the same entity → produce 1 resolved entity
- If mentions refer to N distinct entities → split into N resolved entities
Use canonical_candidate as a starting point for the canonical_name.

Return: {"entities": [{canonical_name, type, aliases, source_ids, relevant}]}
```

## Test mode

`python scripts/entity_clustering.py --test` :
- Zéro LLM, zéro dépendance externe (pas de spacy, pas de yaml)
- Tourne en < 2s
- Données hardcodées simulant *Le Jeu de l'Ange*
- Valide : Martín ×5 → 1 cluster, Sempere ×4 → 1 cluster, Barcelona/Barcelone → 1 cluster

## Critères d'acceptation (depuis STU-220)

- [ ] `python scripts/entity_clustering.py --test` passe en < 2s
- [ ] Stage inséré dans `wiki-pipeline.pipeline.yaml`
- [ ] Contract `entity-clustering.contract.yaml` créé
- [ ] Resolver mis à jour pour lire `clusters`
- [ ] Réduction ≥ 50% sur les données du *Jeu de l'Ange*
- [ ] Les 3 Sempere dans le même cluster
- [ ] Aucune dépendance externe (Jaro-Winkler from scratch)
