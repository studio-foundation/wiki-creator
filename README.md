# Wiki Creator

> Analyse EPUBs et PDFs pour générer des wikis structurés — propulsé par [Studio](https://github.com/studioag/studio).

**Use case :** Compléter le wiki de *A Dark and Hollow Star* avec les entités (personnages, lieux, organisations, événements) extraites des livres restants.

**Statut :** Planned (June–August 2026). Dépend de STU-114 (script executor) + STU-105 (studio-run).

---

## Ce que ça fait

1. **Parse l'EPUB** — Extrait les chapitres avec leur texte (stage système, pas de LLM)
2. **Extrait les entités** — Identifie personnages, lieux, organisations, événements par chapitre
3. **Résout les entités** — Déduplique et canonicalise (Rae d'Adrast = Rae = la petite meurtrière...)
4. **Génère les pages wiki** — Rédige le contenu Markdown de chaque page à partir des mentions

---

## Stack

- **Python 3.11+** — ebooklib, BeautifulSoup4, spacy, lxml
- **Studio** — Orchestration pipeline (`analysis/` template)
- **SQLite** via Prisma — Books, Entities, WikiPages
- **Anthropic Claude** — Extraction et génération (via `.studio/config.yaml`)

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

# 5. Base de données
DATABASE_URL="file:./dev.db" npx prisma migrate dev
```

---

## Usage

```bash
# Lancer le pipeline sur un EPUB
studio run wiki-pipeline --input '{"file_path": "books/dark-and-hollow-star-3.epub"}' --live

# Avec un fichier d'input
studio run wiki-pipeline --input-file .studio/inputs/book.input.yaml --live

# Vérifier le résultat
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
│   ├── pipelines/       # wiki-pipeline.pipeline.yaml
│   ├── agents/          # extractor.agent.yaml, resolver.agent.yaml, writer.agent.yaml
│   ├── contracts/       # entity-extraction.contract.yaml, etc.
│   ├── tools/           # git, repo-manager, search, shell
│   └── inputs/          # book.input.yaml (exemples)
├── wiki_creator/
│   └── types.py         # Types Python (EpubChapter, ExtractedEntity, WikiPageDraft...)
├── scripts/
│   └── parse_epub.py    # Stage 1 : parser EPUB (stdin → stdout JSON)
├── prisma/
│   └── schema.prisma    # Book, Entity, WikiPage
└── pyproject.toml
```

---

## Pipeline

```
[EPUB file]
    │
    ▼ parse_epub (script executor — Python, sans LLM)
[ParsedBook: title, author, chapters[]]
    │
    ▼ entity-extraction (agent LLM — par chapitre)
[ExtractedEntity[]: name, type, mentions, context]
    │
    ▼ entity-resolution (agent LLM — group avec retry si doublons)
[ResolvedEntity[]: canonical_name, aliases[]]
    │
    ▼ wiki-generation (agent LLM — une page par entité)
[WikiPageDraft[]: title, content (Markdown)]
    │
    ▼ DB
[Book → Entity → WikiPage (SQLite)]
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
