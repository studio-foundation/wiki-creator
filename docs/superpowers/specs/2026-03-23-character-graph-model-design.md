# Design Spec — Character Graph Model (STU-309)

**Date:** 2026-03-23
**Status:** Approved
**Linear:** [STU-309](https://linear.app/studioag/issue/STU-309/featwiki-resolution-graph-model-pour-les-relations-entre-personnages)

---

## Contexte

Le modèle de relations actuel est une liste plate de paires `(entity_a, entity_b, relationship_type, cooccurrence_count)` dans `relationships_classified.json`. Ce modèle ne permet pas de capturer :

- Les relations **indirectes** (ex: Cain est une menace pour Nehemia *via* Celaena) sans fabriquer de fausses interactions directes
- Les **factions/groupes** nommés comme entités propres
- L'**évolution par chapitre** d'une relation
- La **persistance entre livres** d'une même série

---

## Approche retenue

**Approche A — Graph-builder stage post-résolution**

Un nouveau stage `build-character-graph` s'insère dans wiki-resolution après entity-classification. Il consomme les artefacts existants (relationships_classified.json, entities_classified.json) et produit un graphe de série (`character_graph.json`). Le reste du pipeline (extraction, résolution) reste intact.

```
wiki-resolution order:
1. merge-entities
2. relationship-extraction
3. alias-resolution
4. entity-classification
5. build-character-graph  ← nouveau
```

**Bibliothèque :** NetworkX (`nx.DiGraph`) avec une fine couche `CharacterGraph` qui expose le vocabulaire métier. NetworkX est retenu pour ses algorithmes de traversée (2-hop paths, community detection pour factions futures) et sa stabilité.

---

## Modèle de données

### Nœuds

Deux types de nœuds coexistent dans le même graphe dirigé :

```python
# CHARACTER node
{
  "type": "CHARACTER",
  "canonical_name": "Celaena Sardothien",
  "aliases": ["Laena", "Lillian"],
  "importance": "major",
  "books": ["01-throne-of-glass", "02-crown-of-midnight"]
}

# GROUP node
{
  "type": "GROUP",
  "canonical_name": "Champions de Perrington",
  "books": ["01-throne-of-glass"]
}
```

### Arêtes

```python
# INTERACTION (CHARACTER ↔ CHARACTER)
{
  "edge_type": "INTERACTION",
  "relationship_type": "antagoniste",     # du LLM classifier
  "direction": "asymétrique",
  "cooccurrence_count": 34,               # total série
  "chapter_weights": {                    # count par chapitre
    "C01.xhtml": 3,
    "C05.xhtml": 8
  },
  "sample_contexts": ["..."],             # global, pas par chapitre
  "evolution": "...",
  "books": ["01-throne-of-glass"]
}

# MEMBER_OF (CHARACTER → GROUP)
{
  "edge_type": "MEMBER_OF",
  "since_chapter": "C03.xhtml",
  "until_chapter": None,                  # None si encore membre en fin de livre
  "books": ["01-throne-of-glass"]
}
```

### Accumulation série

Quand le livre N est traité :
- Les nœuds existants sont enrichis (`books` s'allonge, aliases mergés)
- Les arêtes INTERACTION ont `cooccurrence_count` et `chapter_weights` accumulés
- Les nouvelles arêtes (nouveaux personnages, nouvelles interactions) sont ajoutées

---

## Fichiers et paths

### Nouveaux fichiers

```
wiki_creator/character_graph.py       ← classe CharacterGraph (wrapper NetworkX)
scripts/build_character_graph.py      ← script Studio (stdin/stdout)
tests/test_character_graph.py
tests/test_build_character_graph.py
tests/test_character_graph_pipeline.py
```

### Nouveaux paths (wiki_creator/paths.py)

```python
paths.series_character_graph   # library/<author>/<series>/character_graph.json
paths.book_graph_delta         # processing_output/<slug>/character_graph_delta.json
```

- `character_graph.json` — graphe série complet (NetworkX `node_link_data` format), mis à jour à chaque livre
- `character_graph_delta.json` — contribution du livre courant seul (debug)

---

## Classe `CharacterGraph`

```python
# wiki_creator/character_graph.py

class CharacterGraph:
    def add_character(name: str, metadata: dict) -> None
    def add_group(name: str, metadata: dict) -> None
    def add_interaction(a: str, b: str, edge_data: dict) -> None
    def add_membership(character: str, group: str, edge_data: dict) -> None
    def merge_book(other: CharacterGraph) -> None      # accumulation série
    def direct_relationships(name: str) -> list[Edge]
    def indirect_relationships(name: str, max_hops: int = 2) -> list[IndirectRelationship]
    def factions_for(name: str) -> list[str]
    def to_json() -> dict                              # node_link_data
    @classmethod def from_json(data: dict) -> CharacterGraph
```

---

## Relations indirectes à la volée

### Dataclass

```python
@dataclass
class IndirectRelationship:
    entity_a: str
    entity_b: str
    via: list[str]                    # nœuds intermédiaires
    path_edge_types: list[str]        # types des arêtes sur le chemin
    strength: float                   # produit des cooccurrence_counts normalisés
    inferred: bool = True
```

### Exemple

```python
IndirectRelationship(
    entity_a="Nehemia",
    entity_b="Cain",
    via=["Celaena"],
    path_edge_types=["allié", "antagoniste"],
    strength=0.72,
    inferred=True
)
```

### Intégration dans wiki-preparation

`build_entity_bundle()` appelle `graph.indirect_relationships(name, max_hops=2)` et ajoute les résultats au bundle :

```json
{
  "relationships": [...],
  "indirect_relationships": [...]
}
```

Dans `generate_wiki_pages.py`, les relations indirectes alimentent une section optionnelle du prompt :

```
- related_entity: Cain | via: Celaena | path: allié → antagoniste | inferred: true
```

**Condition d'inclusion :** `importance == "major"` ET au moins 2 relations indirectes trouvées. Les personnages mineurs ne reçoivent pas cette section pour éviter le bruit.

---

## Factions extraites par LLM

### Flow

Dans `build_character_graph.py`, après construction des nœuds INTERACTION, une passe LLM (pipeline Studio `extract-factions`) identifie les groupes nommés.

**Input LLM :**
```yaml
entities: [liste des PERSON major/supporting]
relationships: [arêtes INTERACTION classifiées]
book_summary: "..."
```

**Output LLM attendu :**
```json
[
  {
    "name": "Champions de Perrington",
    "members": ["Cain", "Xavier"],
    "first_chapter": "C02.xhtml"
  }
]
```

**Conversion :** chaque faction → nœud GROUP + arêtes MEMBER_OF pour chaque membre.

**Consommation :** `graph.factions_for("Celaena")` → `["Alliés de Celaena"]`, ajouté au bundle, tag optionnel `{{faction: ...}}` dans le prompt wiki.

---

## Stratégie de tests

### `tests/test_character_graph.py`

```python
def test_add_and_retrieve_character()
def test_add_interaction_bidirectional()
def test_indirect_relationships_two_hop()
def test_indirect_relationships_max_hops()
def test_merge_book_accumulates_counts()
def test_merge_book_extends_books_list()
def test_faction_membership_added_and_retrieved()
def test_serialization_roundtrip()
```

### `tests/test_build_character_graph.py`

```python
def test_builds_nodes_from_entities()
def test_builds_edges_from_relationships()
def test_chapter_weights_aggregated_correctly()
def test_faction_nodes_created_from_llm_output()
def test_delta_json_written_separately()
```

### `tests/test_character_graph_pipeline.py`

```python
def test_series_graph_updated_on_second_book()
def test_wiki_preparation_reads_indirect_relationships()
def test_bundle_contains_indirect_relationships_for_major_character()
def test_bundle_no_indirect_relationships_for_minor_character()
```

### Régression

`relationships.json` continue d'être produit par relationship-extraction — les tests existants sur wiki_preparation et generate_wiki_pages passent sans modification.

---

## Résumé des changements par composant

| Composant | Changement |
|---|---|
| `wiki_creator/character_graph.py` | Nouveau — classe CharacterGraph + IndirectRelationship |
| `wiki_creator/paths.py` | +2 propriétés (series_character_graph, book_graph_delta) |
| `scripts/build_character_graph.py` | Nouveau — script Studio stdin/stdout |
| `scripts/wiki_preparation.py` | Lit le graphe, appelle indirect_relationships(), enrichit bundle |
| `scripts/generate_wiki_pages.py` | Section indirecte optionnelle dans le prompt, tag faction |
| `.studio/pipelines/wiki-resolution.pipeline.yaml` | +1 stage build-character-graph |
| Tests | ~20 nouveaux tests |
