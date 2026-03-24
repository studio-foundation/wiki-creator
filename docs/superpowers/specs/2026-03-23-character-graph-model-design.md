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

## Périmètre — Phase 1 vs Phase 2

### Phase 1 (ce spec)

- Modèle de données `CharacterGraph` (nœuds CHARACTER + arêtes INTERACTION)
- Stage `build-character-graph` dans wiki-resolution
- Graphe de série avec accumulation inter-livres
- Relations indirectes calculées à la volée dans wiki-preparation
- Intégration dans generate_wiki_pages (section indirecte optionnelle)

### Phase 2 (hors scope)

- **Factions/groupes** — nœuds GROUP + arêtes MEMBER_OF + pipeline LLM `extract-factions`. Dépend de la fiabilité d'extraction LLM et de la validation des noms canoniques. Reporté après validation de la Phase 1.
- Community detection automatique via Louvain

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

**Bibliothèque :** NetworkX `>=3.0` (`nx.DiGraph`) avec une fine couche `CharacterGraph`. NetworkX est retenu pour ses algorithmes de traversée (2-hop paths) et sa stabilité (API stable depuis v3.0). Ajout dans `pyproject.toml` : `networkx>=3.0`.

**Concurrence :** Le pipeline traite les livres d'une même série de façon séquentielle. Pas de locking nécessaire en Phase 1. `build-character-graph` effectue un write atomique (write-to-temp + rename) sur `character_graph.json` pour éviter la corruption en cas d'interruption.

---

## Modèle de données

### Nœuds (Phase 1 : CHARACTER uniquement)

```python
# CHARACTER node
{
  "type": "CHARACTER",
  "canonical_name": "Celaena Sardothien",
  "aliases": ["Laena", "Lillian"],
  "importance": "major",
  "books": ["01-throne-of-glass", "02-crown-of-midnight"]
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
  "chapter_weights": {                    # <book_slug>/<chapter_id> → count
    "01-throne-of-glass/C01.xhtml": 3,
    "01-throne-of-glass/C05.xhtml": 8,
    "02-crown-of-midnight/C02.xhtml": 5
  },
  "sample_contexts": ["..."],             # global, pas par chapitre
  "evolution": "...",
  "books": ["01-throne-of-glass"]
}
```

**Clés chapter_weights :** format `<book_slug>/<chapter_id>` pour garantir l'unicité globale à travers la série. Pas de collision entre chapitres de livres différents.

### Accumulation série (`merge_book`)

Quand le livre N est traité, `CharacterGraph.merge_book(book_graph)` :
- **Nœuds existants :** `books` s'allonge, `aliases` mergés (union), autres attributs inchangés
- **Arêtes existantes :** `cooccurrence_count` += delta, `chapter_weights` mergés (union des clés), `books` s'allonge, `sample_contexts` enrichis (jusqu'à 3 exemples par arête)
- **Nouveaux nœuds/arêtes :** ajoutés directement

---

## Fichiers et paths

### Nouveaux fichiers

```
wiki_creator/character_graph.py       ← classe CharacterGraph (wrapper NetworkX)
scripts/build_character_graph.py      ← script Studio (stdin/stdout)
tests/test_character_graph.py
tests/test_build_character_graph.py
tests/test_character_graph_pipeline.py
tests/fixtures/character_graph/       ← fixtures partagées (voir Tests)
```

### Nouveaux paths (wiki_creator/paths.py)

```python
# Basé sur book_yaml : library/<author>/<series>/books/<book>.yaml
# series_dir = book_yaml.parent.parent  (= library/<author>/<series>/)

@property
def series_character_graph(self) -> Path:
    return self._series_dir / "character_graph.json"

@property
def book_graph_delta(self) -> Path:
    return self.processing_output / "character_graph_delta.json"
```

- `character_graph.json` — graphe série complet, format NetworkX `node_link_data` (v3.x), mis à jour à chaque livre
- `character_graph_delta.json` — contribution du livre courant seul (debug, non consommé downstream)

**Format `node_link_data` (NetworkX ≥3.0) :** `{"directed": true, "multigraph": false, "graph": {}, "nodes": [...], "links": [...]}`. `from_json()` vérifie la présence de la clé `"directed"` pour détecter un format incompatible et lève `ValueError` avec message explicite.

---

## Classe `CharacterGraph`

```python
# wiki_creator/character_graph.py

@dataclass
class IndirectRelationship:
    entity_a: str
    entity_b: str
    via: list[str]                    # nœuds intermédiaires sur le chemin
    path_edge_types: list[str]        # relationship_type de chaque arête du chemin
    strength: float                   # voir formule ci-dessous
    inferred: bool = True             # toujours True ; distingue des arêtes directes


class CharacterGraph:
    def add_character(name: str, metadata: dict) -> None
    def add_interaction(a: str, b: str, edge_data: dict) -> None
    def merge_book(other: CharacterGraph) -> None
    def direct_relationships(name: str) -> list[dict]
    def indirect_relationships(name: str, max_hops: int = 2) -> list[IndirectRelationship]
    def to_json() -> dict                              # node_link_data NetworkX
    @classmethod def from_json(data: dict) -> CharacterGraph   # valide format
```

### Formule `strength`

Pour un chemin de longueur k passant par des arêtes avec `cooccurrence_count` c₁, c₂, … cₖ :

```
max_count = max cooccurrence_count sur toutes les arêtes INTERACTION du graphe
strength = product(cᵢ / max_count for i in 1..k)
```

Borné dans [0.0, 1.0]. Si `max_count == 0`, `strength = 0.0`. Les chemins avec `strength < 0.1` sont filtrés (bruit).

---

## Relations indirectes à la volée

### Intégration dans wiki-preparation

`wiki_preparation.py` charge le graphe série depuis disk au début de l'exécution :

```python
graph = CharacterGraph.from_json(json.loads(paths.series_character_graph.read_text()))
```

Si le fichier est absent (première run, graphe pas encore produit), `graph = None` et le bundle est construit sans relations indirectes — pas d'erreur.

`build_entity_bundle()` enrichit le bundle :

```python
indirect = graph.indirect_relationships(name, max_hops=2) if graph else []
bundle["indirect_relationships"] = [asdict(r) for r in indirect]
```

### Format dans le bundle

```json
{
  "relationships": [...],
  "indirect_relationships": [
    {
      "entity_a": "Nehemia",
      "entity_b": "Cain",
      "via": ["Celaena"],
      "path_edge_types": ["allié", "antagoniste"],
      "strength": 0.72,
      "inferred": true
    }
  ]
}
```

### Intégration dans generate_wiki_pages

Section optionnelle dans le prompt LLM :

```
- related_entity: Cain | via: Celaena | path: allié → antagoniste | inferred: true
```

**Condition d'inclusion :** `importance == "major"` ET `len(indirect_relationships) >= 2`. Les personnages mineurs ne reçoivent pas cette section.

---

## Stratégie de tests

### Fixtures (`tests/fixtures/character_graph/`)

```
minimal_graph.json       ← 3 CHARACTER nodes, 3 INTERACTION edges (Celaena↔Chaol, Celaena↔Nehemia, Celaena↔Cain)
book1_delta.json         ← delta livre 1 (subset du minimal_graph)
book2_delta.json         ← delta livre 2 (nouveaux chapitres sur mêmes arêtes)
```

Toutes les fixtures sont des `node_link_data` valides et suffisent pour tester l'ensemble des cas sans mocker NetworkX.

### `tests/test_character_graph.py`

```python
def test_add_and_retrieve_character()
def test_add_interaction_bidirectional()
def test_indirect_relationships_two_hop()           # Nehemia←Celaena→Cain
def test_indirect_relationships_max_hops_respected()
def test_indirect_relationships_strength_formula()  # vérifie la formule exacte
def test_indirect_relationships_strength_below_threshold_filtered()
def test_merge_book_accumulates_cooccurrence_counts()
def test_merge_book_merges_chapter_weights_with_namespaced_keys()
def test_merge_book_extends_books_list()
def test_serialization_roundtrip()
def test_from_json_raises_on_incompatible_format()
```

### `tests/test_build_character_graph.py`

```python
def test_builds_character_nodes_from_entities()
def test_builds_interaction_edges_from_relationships()
def test_chapter_weights_use_namespaced_keys()
def test_delta_json_written_to_book_output_path()
def test_series_graph_atomic_write()               # vérifie write-to-temp + rename
```

### `tests/test_character_graph_pipeline.py`

```python
def test_series_graph_updated_on_second_book()      # utilise book1_delta + book2_delta
def test_wiki_preparation_loads_graph_from_disk()
def test_wiki_preparation_graceful_if_no_graph()    # graph absent → pas d'erreur
def test_bundle_contains_indirect_relationships_for_major_character()
def test_bundle_no_indirect_relationships_for_minor_character()
```

### Régression

`relationships.json` continue d'être produit par relationship-extraction — les tests existants sur wiki_preparation et generate_wiki_pages passent sans modification.

---

## Clarifications d'implémentation

### Validation des inputs dans `build_character_graph.py`

- Arêtes avec `entity_a` ou `entity_b` absent du graphe de nœuds → **ignorées** avec warning (pas d'erreur fatale)
- Arêtes avec `cooccurrence_count` manquant ou <= 0 → ignorées avec warning
- `relationship_type` inconnu → conservé tel quel (pas de whitelist — le classifier peut évoluer)
- Nœuds sans `importance` → défaut `"minor"`

### Atomic write

```python
tmp = series_character_graph.with_suffix(".json.tmp")
tmp.write_text(json.dumps(graph.to_json()))
tmp.rename(series_character_graph)   # atomique sur POSIX
```

Si `write_text` lève → `tmp` n'existe pas, série intacte. Si `rename` lève → `tmp` orphelin, série intacte. Cleanup de `tmp` sur exception dans `finally`.

**Note concurrence :** les livres d'une même série DOIVENT être traités séquentiellement (documenté dans le pipeline YAML via `concurrency: 1` sur le stage `build-character-graph`). Traitement parallèle = corruption silencieuse.

### Indirect relationships — filtrage

`indirect_relationships(name)` retourne **tous** les chemins valides (strength >= 0.1), indépendamment de l'importance du nœud cible. Le filtrage `importance == "major"` s'applique uniquement dans `generate_wiki_pages.py` pour décider d'inclure la section dans le prompt — pas dans `CharacterGraph`.

`max_hops=2` : au-delà de 2 sauts, le signal est trop faible (strength chute en O(1/max_count²)) et le risque de chemins non pertinents augmente. `wiki_preparation.py` peut passer `max_hops=1` pour les personnages `supporting`.

### Merge chapter_weights

`cooccurrence_count` et `chapter_weights` counts sont **sommés** lors du merge (pas écrasés). `sample_contexts` : jusqu'à 3 exemples — sélection des 3 premiers du nouveau livre si < 3 en stock, sinon conservés. Contexts tronqués à 500 caractères.

### Signatures `CharacterGraph` (annotées)

```python
def add_character(self, name: str, metadata: dict) -> None
def add_interaction(self, a: str, b: str, edge_data: dict) -> None
def merge_book(self, other: "CharacterGraph") -> None
def direct_relationships(self, name: str) -> list[dict]
def indirect_relationships(self, name: str, max_hops: int = 2) -> list[IndirectRelationship]
def to_json(self) -> dict           # NetworkX node_link_data format
@classmethod
def from_json(cls, data: dict) -> "CharacterGraph"
    # Raises ValueError("character_graph.json format incompatible: missing 'directed' key")
    # if "directed" not in data
```

---

## Résumé des changements par composant

| Composant | Changement |
|---|---|
| `wiki_creator/character_graph.py` | Nouveau — CharacterGraph + IndirectRelationship |
| `wiki_creator/paths.py` | +2 propriétés (series_character_graph, book_graph_delta) |
| `scripts/build_character_graph.py` | Nouveau — script Studio stdin/stdout |
| `scripts/wiki_preparation.py` | Charge graphe depuis disk, enrichit bundle avec indirect_relationships |
| `scripts/generate_wiki_pages.py` | Section indirecte optionnelle dans le prompt |
| `.studio/pipelines/wiki-resolution.pipeline.yaml` | +1 stage build-character-graph |
| `pyproject.toml` | +`networkx>=3.0` |
| Tests | ~20 nouveaux tests + fixtures |
