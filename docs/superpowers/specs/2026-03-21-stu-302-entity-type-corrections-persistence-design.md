# STU-302 — Persistence des corrections verify-entity-types

**Date :** 2026-03-21
**Ticket :** [STU-302](https://linear.app/studioag/issue/STU-302)
**Statut :** Design approuvé

---

## Problème

`verify-entity-types` tourne dans `wiki-extraction` et produit des corrections de types LLM
(ex. `Arobynn` retypé PLACE → PERSON). Ces corrections transitent en mémoire dans le flux du
pipeline mais ne sont jamais persistées sur disque.

Sur `--restart wiki-resolution` ou au-delà, `wiki-extraction` ne tourne pas — les corrections
sont perdues. `entity_classification.py` repart des clusters bruts et peut reclasser les mêmes
entités incorrectement.

---

## Solution retenue — Approche A : Persist-then-apply

### Principe

- `verify_entity_types.py` écrit les corrections dans `processing_output/<slug>/entity_type_corrections.json`
- `entity_classification.py` lit ce fichier s'il existe et applique les corrections avant les overrides manuels

Séparation claire : chaque script reste responsable de son propre périmètre.

---

## Changements par fichier

### `scripts/verify_entity_types.py`

**Dans `main()`** — ordre d'exécution inchangé :

1. Vérifier `enabled` en premier — si `False`, retour anticipé, aucun fichier écrit (comportement actuel inchangé).
2. Dans le bloc `enabled=True`, après `apply_corrections`, avant `json.dump` :
   - Si `paths` est résolu (`file_path` présent dans le payload) : écrire `paths.processing / "entity_type_corrections.json"` avec la liste des corrections (éventuellement vide `[]`). Créer le répertoire si nécessaire (`mkdir(parents=True, exist_ok=True)`).
   - Si `paths` est `None` (pas de `file_path`) : ne pas écrire de fichier — logger les corrections sur stderr uniquement (comportement actuel conservé).

Le `context_snippet` de chaque correction est passé tel quel depuis la sortie de `verify_clusters` — champ informatif, non lu par `entity_classification.py`.

**Note d'implémentation :** dans l'implémentation actuelle, `verify_clusters` n'émet des corrections que vers `PERSON` (condition `if new_type == "PERSON"`). Le format JSON accepte n'importe quel type cible, mais aucun autre cas n'est produit aujourd'hui. Si le champ `to` était étendu à d'autres types, `_load_type_corrections` les lirait sans modification.

**Si Ollama échoue pour tous les candidats :** `corrections=[]`, le fichier est quand même écrit avec `[]`. Ce comportement est correct — un fichier vide est préférable à l'absence de fichier (évite que `entity_classification.py` ignore silencieusement un run précédent).

**Format du fichier :**
```json
[
  {
    "cluster_id": "cluster_042",
    "name": "Arobynn",
    "from": "PLACE",
    "to": "PERSON",
    "context_snippet": "Arobynn lui sourit depuis le trône..."
  }
]
```

### `scripts/entity_classification.py`

**Nouvelle fonction `_load_type_corrections(processing_dir: Path) -> dict[str, str]`**

Lit `entity_type_corrections.json` si le fichier existe. Retourne un dict
`{ lowercase_name: "PERSON" | "PLACE" | ... }`. Si le fichier est absent, retourne `{}` — aucune
erreur levée, classification procède normalement.

```python
def _load_type_corrections(processing_dir: Path) -> dict[str, str]:
    p = processing_dir / "entity_type_corrections.json"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        corrections = json.load(f)
    return {c["name"].lower(): c["to"] for c in corrections if "name" in c and "to" in c}
```

Appelé dans `run_studio_mode()` avec `paths.processing` — attribut `Path` sur `BookPaths` (voir
`wiki_creator/paths.py`), déjà résolu par l'appel existant à `_paths_from_payload` en ligne ~638.
En mode Studio, `file_path` est toujours présent dans le payload — `_paths_from_payload` ne retourne
pas `None` ici (contrairement à la version dans `verify_entity_types.py`). Aucun guard `None`
supplémentaire requis.

**Collision de noms :** si deux corrections ont des `name` distincts par la casse seulement, la
dernière dans la liste écrase la première (last-write-wins). Ce cas n'existe pas en pratique pour
des noms de personnages de roman.

**Nouvelle fonction `_apply_llm_type_corrections(entities, corrections_map)`**

Pour chaque entité, cherche `canonical_name.lower()` puis chaque alias dans `corrections_map`.
Si trouvé, force le type et logue sur stderr.

```python
def _apply_llm_type_corrections(
    entities: list[dict],
    corrections_map: dict[str, str],
) -> None:
    for entity in entities:
        name = (entity.get("canonical_name") or "").lower()
        match = corrections_map.get(name)
        if match is None:
            for alias in entity.get("aliases", []):
                match = corrections_map.get((alias or "").lower())
                if match is not None:
                    break
        if match is not None and entity.get("type") != match:
            print(
                f"[CORRECTIONS] {entity['canonical_name']}: {entity['type']} → {match} (from entity_type_corrections.json)",
                file=sys.stderr,
            )
            entity["type"] = match
```

**Dans `run_studio_mode()`**, ordre d'application :

```
1. _normalize_entity_type       # heuristique déterministe
2. _apply_llm_type_corrections  # corrections LLM persistées (NOUVEAU)
3. _canonicalize_role_entities  # fusion rôles/titres
4. _apply_entity_overrides      # overrides manuels book YAML (priorité max)
```

Les overrides manuels gardent la priorité absolue — ils peuvent écraser une correction LLM.

**Edge case — entité fusionnée par `_canonicalize_role_entities` :** deux sous-cas distincts :
- L'entité corrigée est fusionnée *dans* une autre et disparaît (`relevant=False`) : la correction est appliquée à l'entité source avant fusion, mais n'a aucun impact sur la sortie finale. Acceptable.
- L'entité corrigée est la *cible* d'une fusion (son `canonical_name` absorbe un alias) : elle reste dans la sortie avec le type corrigé. La correction survit correctement.

---

## Matching strategy

Matching par `name` (champ `canonical_candidate` du cluster dans `verify_entity_types`) contre
`canonical_name` et `aliases` de l'entité dans `entity_classification`, en lowercase.

Justification : `source_ids` contient les `entity_ids` membres du cluster (`split_clusters.py:61`),
jamais le `cluster_id` lui-même — le matching par cluster_id est impossible sans changer le modèle
de données de `merge-entities`.

Le matching par alias couvre le cas où `alias-resolution` a fusionné deux entités et que le nom
corrigé est devenu un alias.

**Limitation connue :** si `alias-resolution` a supprimé entièrement le `canonical_candidate`
d'origine (ex. doublon partiel écarté), ni `canonical_name` ni `aliases` ne matcheront — la
correction est silencieusement ignorée. Ce cas est rare et acceptable : il implique qu'une entité
suffisamment ambiguë pour être supprimée par `alias-resolution` n'a pas besoin d'une correction de type.

---

## Nettoyage

`entity_type_corrections.json` est dans `processing_output/<slug>/`.
`--clean wiki-extraction` supprime ce répertoire — le fichier est recalculé au prochain run complet.
Aucun changement requis dans la logique de clean.

---

## Tests

### `tests/test_verify_entity_types.py`

| Test | Description |
|------|-------------|
| `test_main_writes_corrections_file` | payload avec `file_path` + `verify_entity_types: true` + clusters PLACE candidats PERSON → vérifie présence et contenu de `entity_type_corrections.json` dans `tmp_path/processing_output/<slug>/` |
| `test_main_writes_empty_file_when_no_corrections` | clusters sans candidats PERSON → fichier écrit avec `[]` |
| `test_main_no_file_when_disabled` | `verify_entity_types: false` → fichier absent |
| `test_main_no_file_when_no_paths` | payload sans `file_path` → fichier absent |

### `tests/test_entity_classification.py`

| Test | Description |
|------|-------------|
| `test_load_type_corrections_returns_empty_when_no_file` | fichier absent → dict vide, pas d'erreur |
| `test_load_type_corrections_reads_file` | fichier présent → dict correctement construit en lowercase |
| `test_apply_llm_corrections_by_canonical_name` | correction trouvée par canonical_name → type modifié |
| `test_apply_llm_corrections_by_alias` | canonical_name absent du dict, alias présent → type modifié |
| `test_apply_llm_corrections_no_match` | aucun match → type inchangé |
| `test_corrections_lower_priority_than_entity_overrides` | correction LLM PLACE→PERSON + override manuel `force_type: PLACE` → type final PLACE |
| `test_run_studio_mode_applies_corrections_file` | intégration : créer `tmp_path / "books" / "testbook.epub"` (le fichier peut être vide — seul le chemin compte), passer `file_path = str(tmp_path / "books" / "testbook.epub")` dans le payload YAML. `book_paths_from_epub` résoudra `paths.processing = tmp_path / "processing_output" / "testbook"`. Écrire `entity_type_corrections.json` dans ce répertoire. Passer le payload à `run_studio_mode` → type corrigé dans la sortie JSON. |

---

## Critères d'acceptation

- `--restart wiki-resolution` sur un livre où `entity_type_corrections.json` existe → corrections appliquées sans relancer `wiki-extraction`
- `--restart wiki-resolution` quand le fichier est absent → classification procède normalement, aucune erreur
- `--clean --restart wiki-extraction` → supprime `entity_type_corrections.json` et le recalcule
- `verify_entity_types.py` sans `file_path` dans le payload → pas de fichier écrit
- `--restart wiki-extraction` (sans `--clean`) → `entity_type_corrections.json` est écrasé par le nouveau run (overwrite silencieux)
- `pytest -q` passe
