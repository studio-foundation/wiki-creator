# CLAUDE.md — Wiki Creator

Wiki Creator est un projet "Powered by Studio" qui analyse des EPUBs et PDFs pour générer des wikis structurés. Il valide le support multi-langage (Python) et les stages systèmes (script executor sans LLM) dans Studio.

**Use case concret :** Compléter le wiki incomplet de *A Dark and Hollow Star* avec les deux derniers livres.

**Prérequis Studio :** STU-114 (script executor) + STU-105 (studio-run pour runs-dans-runs).

---

## Commandes

```bash
# Setup Python
pip install -e ".[dev]"          # Installe les dépendances + outils dev
pip install -e .                 # Dépendances prod seulement

# DB
DATABASE_URL="file:./dev.db" npx prisma migrate dev   # Créer/migrer la DB
DATABASE_URL="file:./dev.db" npx prisma studio        # Inspecter la DB

# Tests
pytest                           # Lancer tous les tests
mypy wiki_creator/               # Type checking

# Run complet via orchestrateur
make run BOOK=books/mon-livre.yaml

# Pipelines individuels
make run-extraction              # wiki-extraction
make run-resolution              # wiki-resolution
make generate-pages              # Génération Ollama standalone
make pages-export                # Export wikitext via Studio

# Tests standalone (sans Studio, sans API)
make test-extraction             # NER sur le livre configuré
make test-clustering             # Clustering données hardcodées
make test-relationships          # Co-occurrence données hardcodées
make test                        # Enchainement complet (--live)
make test-coref                  # Avec enrichissement pronoms
make test-coref-parallel         # Avec fastcoref --workers N

# Script executor — test direct
echo '{"file_path": "book.epub"}' | python scripts/parse_epub.py

# Studio
studio status                    # Vérifier le dernier run
studio logs                      # Logs du dernier run
```

---

## Architecture

```
wiki-creator-by-studio/
├── .studio/                     # Studio vit ici
│   ├── config.yaml              # API keys (gitignored)
│   ├── pipelines/               # wiki-extraction, wiki-resolution, wiki-generation
│   ├── agents/                  # *.agent.yaml
│   ├── contracts/               # *.contract.yaml
│   ├── tools/                   # git, repo-manager, search, shell
│   └── inputs/                  # *.input.yaml
├── wiki_creator/
│   ├── __init__.py
│   └── types.py                 # EpubChapter, ParsedBook, ExtractedEntity, ResolvedEntity, WikiPageDraft
├── scripts/                     # Script executor stages + outils standalone (voir ci-dessous)
├── processing_output/           # Fichiers intermédiaires entre pipelines (gitignored)
│   ├── epub_data.json           # Sortie parse_epub
│   ├── splits.json              # Sortie split_clusters
│   ├── entities_classified.json # Sortie entity_classification
│   └── wiki_pages.json          # Pages générées par generate_wiki_pages
├── wiki_inputs/                 # Batch files par importance (gitignored)
├── output/wiki/                 # Fichiers wikitext exportés (gitignored)
├── prisma/
│   └── schema.prisma            # Book, Entity, WikiPage models
├── pyproject.toml               # Python package config (hatchling)
└── run_wiki.py                  # Orchestrateur des 3 pipelines
```

**3 pipelines Studio indépendants :**
1. **wiki-extraction** — Parse EPUB + NER spaCy + clustering déterministe
2. **wiki-resolution** — Résolution entités + co-occurrence + classification d'importance
3. **wiki-generation** — Préparation batches + génération Ollama + export wikitext

---

## Scripts Python — référence rapide

Tous lisent JSON via `stdin`, écrivent JSON via `stdout`. Les **loaders** relient les pipelines en relisant `processing_output/`.

### wiki-extraction

| Script | Stage | Rôle |
|--------|-------|------|
| `parse_epub.py` | `epub-parse` | Parse EPUB → chapitres + POV. Écrit `processing_output/epub_data.json` |
| `entity_extraction.py` | `entity-extraction` | NER spaCy (PERSON/PLACE/ORG). Écrit `*_full.json` + `chapters.json` |
| `entity_clustering.py` | `entity-clustering` | Clustering par token overlap + Jaro-Winkler + Union-Find |
| `split_clusters.py` | `split-clusters` | Sépare singles (pré-résolus) et multi-clusters par type. Écrit `processing_output/splits.json` |

### wiki-resolution

| Script | Stage | Rôle |
|--------|-------|------|
| `load_epub_data.py` | `epub-parse` | Loader — relit `processing_output/epub_data.json` |
| `load_splits.py` | `split-clusters` | Loader — relit `processing_output/splits.json` |
| `resolve_clusters.py` | `resolve-clusters` | Mappe clusters → entités résolues (sans LLM) |
| `merge_entities.py` | `merge-entities` | Pass-through `resolve-clusters` |
| `relationship_extraction.py` | `relationship-extraction` | Co-occurrence PERSON (fenêtre glissante). Optionnel : coref spaCy ou fastcoref |
| `entity_classification.py` | `entity-classification` | Tiers d'importance par percentile ou seuils. Écrit `processing_output/entities_classified.json` |

### wiki-generation

| Script | Stage | Rôle |
|--------|-------|------|
| `load_classified_entities.py` | `entity-classification` | Loader — relit `processing_output/entities_classified.json` |
| `wiki_preparation.py` | `wiki-preparation` | Batch files par entité (`wiki_inputs/batch_*.json`) |
| `generate_wiki_pages.py` | (standalone) | Génère pages via Ollama. Supporte reprise sur interruption |
| `load_wiki_pages.py` | `wiki-generation` | Loader — relit `processing_output/wiki_pages.json` |
| `copyright_check.py` | `copyright-check` | Détecte séquences verbatim ≥15 mots (n-gram index) |
| `wiki_export.py` | `wiki-export` | Convertit Markdown → wikitext + templates MediaWiki |

### Standalone / test

| Script | Rôle |
|--------|------|
| `test_extraction.py` | NER sur le livre complet → `extraction-*.jsonl` |

**Flags communs :** `--test` (données hardcodées) et `--live` (données réelles depuis `*_full.json`) disponibles sur la plupart des scripts.

---

## DB Schema (Prisma / SQLite)

| Model | Champs clés |
|-------|------------|
| `Book` | id, title, author, filePath |
| `Entity` | id, name, type (PERSON/PLACE/ORG/EVENT/OTHER), aliases (JSON), bookId |
| `WikiPage` | id, title, content (Markdown), entityId (unique), bookId |

`DATABASE_URL` doit être défini dans l'environnement. Valeur dev : `file:./dev.db`.

---

## Interface Script Executor

Format Studio script executor : lit JSON depuis stdin, écrit JSON sur stdout.

```bash
# Input direct (test)
echo '{"file_path": "/path/to/book.epub"}' | python scripts/parse_epub.py
```

Tout nouveau script suit ce même pattern :
```python
payload = json.load(sys.stdin)
# ...
json.dump(result, sys.stdout, ensure_ascii=False)
```

Le contexte envoyé par Studio a ce format :
```json
{
  "additional_context": "<yaml string de l'input>",
  "previous_outputs": {"epub-parse": {...}, ...}
}
```
Lire `yaml.safe_load(payload["additional_context"])` pour l'input, et `payload["previous_outputs"]["<stage-name>"]` pour le stage précédent.

---

## Studio — Concepts clés pour ce projet

**3 pipelines découplés** — Les pipelines s'enchaînent via `processing_output/` : chaque pipeline suivant commence par un loader qui relit le fichier produit par le précédent.

**Script executor** — Stages sans LLM. Configuré dans le pipeline YAML via `executor: script` + `runtime: python` + `script: scripts/mon_script.py`. Le champ `script` est le chemin du fichier seulement (sans le runtime). Le `runtime` est requis explicitement.

**Context propagation** — Chaque stage déclare `context.include: [input, previous_stage_output]`. Sans ça, le stage n'a accès à rien.

**Fichiers intermédiaires** — Les scripts qui lisent des fichiers du projet root (`persons_full.json`, `chapters.json`, etc.) le font via `open()` direct. Studio set le CWD au project root.

**Groups** — Si entity-resolution rejette (doublons non résolus), le group peut itérer. Le dernier stage du group doit avoir `post_validation.rejection_detection` dans son contract.

---

## Git Workflow

**Tout ticket Linear = worktree.** C'est la première étape, avant tout.

```bash
git worktree add .worktrees/<branch-name> -b <type>/stu-xxx-description
```

**Jamais de push sur `main`.** Toujours branche + PR.

```bash
git checkout -b feat/stu-xxx-description
git commit -m "feat(wiki-creator): ..."
git push -u origin <branch>
gh pr create --title "..." --body "..." --base main
```

`.worktrees/` est dans `.gitignore`.

---

## Gotchas

- **`parse_epub.py` sort du HTML brut si BeautifulSoup échoue.** Toujours vérifier que le contenu est du texte propre avant de passer au LLM.
- **Les entités EPUB n'ont pas d'ID stable.** `item.get_id()` retourne l'ID interne ebooklib, pas le titre humain.
- **`entity_extraction.py` écrit `*_full.json` à la racine du projet** — ces fichiers sont lus directement par `relationship_extraction.py`, `entity_classification.py`, et `wiki_preparation.py`.
- **`generate_wiki_pages.py` est standalone** — il n'est pas un script executor Studio. Il lit `wiki_inputs/` et écrit `processing_output/wiki_pages.json`. `load_wiki_pages.py` est le loader qui injecte ce résultat dans le pipeline.
- **fastcoref (LingMessCoref) est optionnel** — ~590 MB RAM par worker. Sans lui, `relationship_extraction.py` utilise une heuristique spaCy pour les pronoms. Flag : `coref: true` dans le YAML d'input, ou `--coref` en CLI.
- **Prisma + Python** : Prisma génère un client JS. Pour accéder à la DB depuis Python, utiliser `prisma-client-py` ou requêtes SQLite directes.
- **`.studio/config.yaml` est gitignored** — contient les API keys. Ne jamais commiter ce fichier.
- **`.studio/runs/`** est gitignored — données runtime, ne pas commiter.
- **Commité dans git** : `.studio/pipelines/`, `.studio/agents/`, `.studio/contracts/`, `.studio/tools/`, `.studio/registry.lock.json`.
