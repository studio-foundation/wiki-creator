# Wiki Creator

Pipeline Python + Studio pour extraire des entites depuis un EPUB, construire un graphe de relations, puis generer des pages wiki Markdown et les exporter en wikitext.

Statut actuel au 2026-03-09:
- `pytest -q` passe (`288 passed`)
- le workflow principal passe par `wiki-extraction` -> `wiki-resolution` -> `wiki-preparation` -> `generate_wiki_pages.py` -> `pages-export`
- les sorties sont stockees par livre sous `library/<author>/<series>/...`

## Objectif

Le projet prend un fichier YAML de livre, derive automatiquement les chemins du livre associe, puis produit:
- des artefacts intermediaires par etape (`processing_output/<book-slug>/`)
- des batches de generation (`wiki_inputs/<book-slug>/`)
- des pages wiki exportees (`output/<book-slug>/`)

Le cas d'usage actif visible dans le repo est `Throne of Glass`:
- [01-throne-of-glass.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml)

## Stack

- Python 3.11+
- Studio pour l'orchestration des pipelines
- spaCy pour le NER
- fastcoref optionnel pour enrichir les relations
- Ollama pour la generation locale des pages
- Prisma/SQLite en option

## Installation

```bash
pip install -e ".[dev]"
```

Optionnel:

```bash
npm install -g @studio/cli
DATABASE_URL="file:./dev.db" npx prisma migrate dev
```

## Commandes utiles

Le `Makefile` est la source de verite des commandes de travail:

```bash
# Livre par defaut:
# library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml

make run
make run BOOK=library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml

make run-extraction
make run-resolution
make run-preparation
make generate-pages
make generate-pages-dry
make pages-export
make run-generation

make run-from-resolution
make run-from-generation
make run-status

make test-extraction
make test-clustering
make test-relationships
make test
make test-coref
make test-coref-parallel

pytest -q
mypy wiki_creator/
```

## Pipeline reel

### 1. `wiki-extraction`

- `parse_epub.py`
- `entity_extraction.py`
- `entity_clustering.py`
- `verify_entity_types.py`
- `split_clusters.py`

Sorties principales:
- `processing_output/<slug>/epub_data.json`
- `processing_output/<slug>/splits.json`
- `processing_output/<slug>/persons_full.json`
- `processing_output/<slug>/places_full.json`
- `processing_output/<slug>/orgs_full.json`
- `processing_output/<slug>/chapters.json`

### 2. `wiki-resolution`

- `load_splits.py`
- `resolve_clusters.py`
- `merge_entities.py`
- `relationship_extraction.py`
- `entity_classification.py`

Sortie principale:
- `processing_output/<slug>/entities_classified.json`

### 3. `wiki-preparation`

- `load_epub_data.py`
- `load_classified_entities.py`
- `chapter_summary.py`
- `wiki_preparation.py`

Sorties principales:
- `processing_output/<slug>/chapter_summaries.json`
- `wiki_inputs/<slug>/batch_*.json`

### 4. Generation standalone

- `scripts/generate_wiki_pages.py --book <book.yaml>`

Sortie principale:
- `processing_output/<slug>/wiki_pages.json`

### 5. `pages-export`

- `load_wiki_pages.py`
- `copyright_check.py`
- `wiki_export.py`

Sortie principale:
- `output/<slug>/**/*.wiki`

Note:
- `.studio/pipelines/wiki-generation.pipeline.yaml` existe encore comme pipeline combine, mais le workflow utilise par `Makefile` et `run_wiki.py` est le split `wiki-preparation` + generation standalone + `pages-export`.

## Arborescence

```text
wiki-creator-by-studio/
├── .studio/
│   ├── pipelines/
│   ├── contracts/
│   ├── agents/
│   ├── tools/
│   └── inputs/
├── library/
│   └── <author>/<series>/
│       ├── books/<slug>.yaml
│       ├── books/<slug>.epub
│       ├── processing_output/<slug>/
│       ├── wiki_inputs/<slug>/
│       └── output/<slug>/
├── scripts/
├── tests/
├── wiki_creator/
├── Makefile
└── run_wiki.py
```

## Fichiers importants

- [Makefile](/home/arianeguay/dev/src/wiki-creator-by-studio/Makefile): commandes de travail
- [run_wiki.py](/home/arianeguay/dev/src/wiki-creator-by-studio/run_wiki.py): orchestrateur local
- [wiki_creator/paths.py](/home/arianeguay/dev/src/wiki-creator-by-studio/wiki_creator/paths.py): derive les chemins a partir du YAML/EPUB
- [.studio/pipelines/wiki-extraction.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/wiki-extraction.pipeline.yaml)
- [.studio/pipelines/wiki-resolution.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/wiki-resolution.pipeline.yaml)
- [.studio/pipelines/wiki-preparation.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/wiki-preparation.pipeline.yaml)
- [.studio/pipelines/pages-export.pipeline.yaml](/home/arianeguay/dev/src/wiki-creator-by-studio/.studio/pipelines/pages-export.pipeline.yaml)

## Gotchas

- Les chemins ne sont plus globaux au repo: ils sont derives par livre via `wiki_creator.paths`.
- `entity_extraction.py` utilise les IDs de chapitre pour `first_seen` et `mentions_by_chapter`, pas les titres.
- `generate_wiki_pages.py` n'est pas un stage Studio; il faut lancer `wiki-preparation` avant.
- `relationship_extraction.py --live` attend normalement `--book`.
- `workers` pour fastcoref augmentent vite l'usage memoire.
- `CLAUDE.md` et `AGENTS.md` contiennent les consignes operatoires pour les agents, pas une doc produit.
