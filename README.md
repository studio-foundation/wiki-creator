# Wiki Creator

> Analyse EPUBs et PDFs pour générer des wikis structurés — propulsé par [Studio](https://github.com/studioag/studio).

**Use case :** Compléter le wiki de *A Dark and Hollow Star* avec les entités (personnages, lieux, organisations, événements) extraites des livres restants.

**Statut :** Planned (June–August 2026). Dépend de STU-114 (script executor) + STU-105 (studio-run).

---

## Ce que ça fait

1. **Parse l'EPUB** — Extrait les chapitres + détection POV (stage système, sans LLM)
2. **Extrait les entités** — NER spaCy : PERSON, PLACE, ORG par chapitre
3. **Cluster les entités** — Regroupe les variantes de noms (Martín ↔ David Martín ↔ M. Martín) par token overlap + Jaro-Winkler
4. **Résout les clusters** — Canonicalise chaque groupe sans LLM
5. **Extrait les relations** — Graphe de co-occurrence pondéré entre personnages
6. **Classifie les entités** — Tiers d'importance (principal / secondary / figurant / ignored)
7. **Génère les pages wiki** — Contenu Markdown par entité via Ollama (LLM local)
8. **Exporte en wikitext** — Fichiers `.wiki` pour MediaWiki

---

## Stack

- **Python 3.11+** — ebooklib, BeautifulSoup4, spaCy, fastcoref (optionnel)
- **Studio** — Orchestration de 3 pipelines indépendants
- **Ollama** — Génération locale des pages wiki (qwen2.5 par défaut, sans API)
- **SQLite** via Prisma — Books, Entities, WikiPages (optionnel)

---

## Installation

```bash
# 1. Cloner le repo
git clone <repo-url>
cd wiki-creator-by-studio

# 2. Python
pip install -e ".[dev]"

# 3. Studio (si pas déjà installé)
npm install -g @studio/cli

# 4. Configurer les providers
studio config set provider anthropic --api-key $ANTHROPIC_API_KEY

# 5. Base de données (optionnel)
DATABASE_URL="file:./dev.db" npx prisma migrate dev
```

---

## Usage

```bash
# Run complet (extraction → résolution → génération)
make run BOOK=books/mon-livre.yaml

# Pipelines individuels
make run-extraction      # wiki-extraction (parse + NER + clustering)
make run-resolution      # wiki-resolution (résolution + relations + classification)
make generate-pages      # Génération pages via Ollama (standalone, sans Studio)
make pages-export        # Export wikitext via Studio

# Relancer depuis une étape (si extraction déjà faite)
make run-from-resolution
make run-from-generation

# Tests standalone (sans Studio, sans API)
make test-extraction     # NER sur le livre configuré → extraction-*.jsonl
make test-clustering     # Clustering sur données hardcodées
make test-relationships  # Co-occurrence sur données hardcodées
make test                # Enchainement test-extraction + clustering + relations (--live)
make test-coref          # Idem avec enrichissement par pronoms (spaCy heuristique)
make test-coref-parallel # Idem avec fastcoref (LingMessCoref, multi-workers)

# Vérifier le résultat Studio
studio status
studio logs

# Tester le parsing seul (sans LLM, sans Studio)
echo '{"file_path": "book.epub"}' | python scripts/parse_epub.py
```

---

## Structure

```
wiki-creator-by-studio/
├── .studio/
│   ├── pipelines/       # wiki-extraction, wiki-resolution, wiki-generation
│   ├── agents/          # writer-lite.agent.yaml, etc.
│   ├── contracts/       # entity-resolution.contract.yaml, etc.
│   ├── tools/           # git, repo-manager, search, shell
│   └── inputs/          # book.input.yaml (exemples)
├── wiki_creator/
│   └── types.py         # Types Python (EpubChapter, ExtractedEntity, WikiPageDraft...)
├── scripts/             # Voir section Scripts ci-dessous
├── processing_output/   # Fichiers intermédiaires entre pipelines (gitignored)
│   ├── epub_data.json
│   ├── splits.json
│   ├── entities_classified.json
│   └── wiki_pages.json
├── wiki_inputs/         # Batch files par importance (gitignored)
├── output/wiki/         # Fichiers .wiki exportés (gitignored)
├── prisma/
│   └── schema.prisma    # Book, Entity, WikiPage
└── pyproject.toml
```

---

## Scripts Python

Tous les scripts de pipeline lisent JSON depuis `stdin` et écrivent JSON sur `stdout` (pattern Studio script executor). Ceux marqués **loader** lisent depuis `processing_output/` pour relier des pipelines découplés.

### Pipeline `wiki-extraction`

| Script | Rôle | Fichiers produits |
|--------|------|-------------------|
| `parse_epub.py` | Parse l'EPUB : chapitres + détection POV (first_person / third_limited / omniscient) | `processing_output/epub_data.json` |
| `entity_extraction.py` | NER spaCy : extrait PERSON/PLACE/ORG, déduplique par mention normalisée | `persons_full.json`, `places_full.json`, `orgs_full.json`, `chapters.json` |
| `entity_clustering.py` | Clustering déterministe par token overlap + Jaro-Winkler + Union-Find (transitive closure) | — |
| `split_clusters.py` | Partitionne : singles pré-résolus + multi-clusters par type (PERSON/PLACE/ORG/EVENT/OTHER) | `processing_output/splits.json` |

### Pipeline `wiki-resolution`

| Script | Rôle | Fichiers produits |
|--------|------|-------------------|
| `load_epub_data.py` | **Loader** — relit `processing_output/epub_data.json` | — |
| `load_splits.py` | **Loader** — relit `processing_output/splits.json` | — |
| `resolve_clusters.py` | Mappe chaque cluster vers une entité résolue (sans LLM) | — |
| `merge_entities.py` | Passe-through : agrège la sortie de `resolve-clusters` | — |
| `relationship_extraction.py` | Graphe de co-occurrence pondéré (fenêtre glissante de N phrases). Option `coref: true` pour enrichissement par pronoms (spaCy heuristique ou fastcoref/LingMessCoref avec `--workers N`) | — |
| `entity_classification.py` | Calcule `total_mentions` + `chapters_present`, assigne `importance` par percentile ou seuils explicites | `processing_output/entities_classified.json` |

### Pipeline `wiki-generation`

| Script | Rôle | Fichiers produits |
|--------|------|-------------------|
| `load_classified_entities.py` | **Loader** — relit `processing_output/entities_classified.json` | — |
| `wiki_preparation.py` | Pré-extrait le contexte par entité, découpe en batch files selon l'importance | `wiki_inputs/batch_*.json` |
| `load_wiki_pages.py` | **Loader** — relit `processing_output/wiki_pages.json` | — |
| `copyright_check.py` | Détecte les séquences verbatim ≥15 mots entre wiki et EPUB source (n-gram index) | — |
| `wiki_export.py` | Convertit les pages Markdown en fichiers wikitext MediaWiki + infobox templates | `output/wiki/**/*.wiki` |

### Standalone (hors Studio)

| Script | Rôle | Usage |
|--------|------|-------|
| `generate_wiki_pages.py` | Génère les pages wiki via Ollama. Supporte la reprise sur interruption (`--importance`, `--dry-run`) | `python scripts/generate_wiki_pages.py [--model qwen2.5] [--importance principal]` |
| `test_extraction.py` | NER sur le livre complet → JSONL + résumé par type | `python scripts/test_extraction.py [book_path] [model] [output.jsonl]` |

### Flags de test communs

La plupart des scripts exposent `--test` (données hardcodées) et/ou `--live` (données réelles) :

```bash
python scripts/entity_extraction.py --test
python scripts/entity_clustering.py --test
python scripts/entity_clustering.py --live
python scripts/relationship_extraction.py --test
python scripts/relationship_extraction.py --live --coref --workers 4
python scripts/entity_classification.py --test
python scripts/copyright_check.py --test
```

---

## Pipeline complet

```
[EPUB file]
    │
    ▼ parse_epub            (script — sans LLM)
[ParsedBook: title, author, chapters[], pov_detection]
    │
    ▼ entity_extraction     (script — spaCy NER)
[entities_for_resolution] + persons/places/orgs_full.json + chapters.json
    │
    ▼ entity_clustering     (script — Jaro-Winkler + Union-Find)
[clusters[]: canonical_candidate, all_mentions, entity_ids]
    │
    ▼ split_clusters        (script)
[singles_resolved[] + multi-clusters by type]  →  processing_output/splits.json
    │
━━━━━━━━━ FIN wiki-extraction | DÉBUT wiki-resolution ━━━━━━━━━
    │
    ▼ resolve_clusters      (script — sans LLM)
[entities[]: canonical_name, aliases[], source_ids]
    │
    ▼ merge_entities        (pass-through)
    │
    ▼ relationship_extraction (script — co-occurrence)
[relationships[]: entity_a ↔ entity_b, cooccurrence_count, chapters]
    │
    ▼ entity_classification  (script — tiers d'importance)
[entities[] avec importance]  →  processing_output/entities_classified.json
    │
━━━━━━━━━ FIN wiki-resolution | DÉBUT wiki-generation ━━━━━━━━━
    │
    ▼ wiki_preparation      (script — batch files)
[wiki_inputs/batch_*.json par importance]
    │
    ▼ generate_wiki_pages   (standalone — Ollama local LLM)
[processing_output/wiki_pages.json]
    │
    ▼ copyright_check       (script — hook Studio)
[pages[] filtrées des violations verbatim]
    │
    ▼ wiki_export           (script — wikitext)
[output/wiki/**/*.wiki]
```

---

## DB Schema

```prisma
model Book     { id, title, author, filePath, entities[], wikiPages[] }
model Entity   { id, name, type, aliases (JSON), bookId, wikiPage? }
model WikiPage { id, title, content, entityId (unique), bookId }
```

---

## Développement

```bash
pytest              # Tests
mypy wiki_creator/  # Type checking

# Inspecter la DB
DATABASE_URL="file:./dev.db" npx prisma studio
```

---

## Liens

- [Linear Project](https://linear.app/studioag/project/wiki-creator-5b60befb7be0/overview)
- [Studio](https://github.com/studioag/studio) — le kernel d'orchestration
