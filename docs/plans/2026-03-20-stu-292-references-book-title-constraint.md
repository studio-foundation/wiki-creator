# STU-292 — Contrainte du titre de livre dans la section Références

## Problème

Le LLM injecte des titres issus de son entraînement dans la section `## Références` plutôt que de se limiter au livre en cours. Exemples observés (Run 7) : *La Colonne de feu* (tome 6, non lu) pour Chaol, *La Fugitive du Roi* (titre inventé) pour Montagnes des Glacials.

## Cause

`build_prompt()` ne contraint pas explicitement la section Références au seul `book_title` injecté.

## Design

### 1. Contrainte dans le prompt (`scripts/generate_wiki_pages.py`)

Dans `build_prompt()`, section **WRITING RULES → Structure**, ajouter :

```
- The ## Références section must list ONLY "{book_title}". Do not add any other book, volume, or series title.
```

### 2. Nouveau check dans le validateur (`scripts/wiki_page_validator.py`)

Nouvelle fonction :

```python
def check_references_book_title(page: dict, allowed_book_titles: list[str]) -> list[str]:
```

Comportement :
1. Extraire le bloc `## Références` (jusqu'au prochain `##` ou fin de contenu)
2. Trouver tous les titres en italique (`*...*` ou `_..._`) dans ce bloc
3. Vérifier que chaque titre trouvé est dans `allowed_book_titles`
4. Retourner `["❌ Titre non autorisé dans Références : '{titre}'"]` si violation
5. Dégradation gracieuse si section absente ou aucun italique

**Chargement de `allowed_book_titles`** dans `validate_page()` :
- Lit `file_path` depuis `meta`
- Dérive `epub_data.json` via `BookPaths` (même logique que `load_book_title()` dans `generate_wiki_pages.py`)
- Construit `allowed_book_titles = [book_title]`
- Skip du check si `file_path` absent ou fichier illisible (dégradation gracieuse)

La signature `list[str]` prépare la migration multi-book (STU-233) sans changement d'interface.

### 3. Tests (`tests/test_wiki_page_validator.py`)

Appels directs à `check_references_book_title(page, allowed_book_titles)` — pas d'I/O disque.

| Cas | Résultat attendu |
|-----|-----------------|
| Références contient uniquement `*Throne of Glass*` | pass |
| Références contient `*La Colonne de feu*` | fail, message contient le titre |
| Pas de section Références | pass |
| Section Références sans italiques | pass |
| Multi-book : `["Tome 1", "Tome 2"]`, les deux présents | pass |

## Compatibilité future (STU-233)

Quand le multi-book arrive, `validate_page()` recevra une liste de tous les tomes traités et construira `allowed_book_titles` à partir d'eux. Aucun changement à la signature de `check_references_book_title`.

## Fichiers touchés

- `scripts/generate_wiki_pages.py` — `build_prompt()`
- `scripts/wiki_page_validator.py` — `check_references_book_title()`, `validate_page()`
- `tests/test_wiki_page_validator.py` — nouveaux tests
