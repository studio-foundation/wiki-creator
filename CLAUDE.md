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

# Studio
studio run wiki-pipeline --input-file .studio/inputs/book.input.yaml --live
studio status                    # Vérifier le dernier run
studio logs                      # Logs du dernier run
studio run wiki-pipeline --provider mock   # Sans API keys

# Script executor (Stage 1 — sans LLM)
echo '{"file_path": "book.epub"}' | python scripts/parse_epub.py
```

---

## Architecture

```
wiki-creator-by-studio/
├── .studio/                     # Studio vit ici
│   ├── config.yaml              # API keys (gitignored)
│   ├── pipelines/               # *.pipeline.yaml
│   ├── agents/                  # *.agent.yaml
│   ├── contracts/               # *.contract.yaml
│   ├── tools/                   # git, repo-manager, search, shell
│   └── inputs/                  # *.input.yaml
├── wiki_creator/
│   ├── __init__.py
│   └── types.py                 # EpubChapter, ParsedBook, ExtractedEntity, ResolvedEntity, WikiPageDraft
├── scripts/
│   └── parse_epub.py            # Stage 1 : script executor (stdin JSON → stdout JSON)
├── prisma/
│   └── schema.prisma            # Book, Entity, WikiPage models
├── pyproject.toml               # Python package config (hatchling)
└── requirements.txt
```

**Pipeline de traitement :**
1. **parse_epub** — Script executor (Python, sans LLM). Lit l'EPUB, retourne titre/auteur/chapitres.
2. **entity-extraction** — Agent LLM. Extrait les entités (PERSON, PLACE, ORG, EVENT) par chapitre.
3. **entity-resolution** — Agent LLM. Déduplique et canonicalise les entités (aliases).
4. **wiki-generation** — Agent LLM. Génère le contenu Markdown de chaque page wiki.

---

## DB Schema (Prisma / SQLite)

| Model | Champs clés |
|-------|------------|
| `Book` | id, title, author, filePath |
| `Entity` | id, name, type (PERSON/PLACE/ORG/EVENT/OTHER), aliases (JSON), bookId |
| `WikiPage` | id, title, content (Markdown), entityId (unique), bookId |

`DATABASE_URL` doit être défini dans l'environnement. Valeur dev : `file:./dev.db`.

---

## Types Python (`wiki_creator/types.py`)

- `EpubChapter` — id, title, content
- `ParsedBook` — title, chapters, author
- `ExtractedEntity` — name, type, mentions, context[]
- `ResolvedEntity` — extends ExtractedEntity + canonical_name, aliases[]
- `WikiPageDraft` — title, content, entity

---

## Interface Script Executor (`scripts/parse_epub.py`)

Format Studio script executor : lit JSON depuis stdin, écrit JSON sur stdout.

```bash
# Input
echo '{"file_path": "/path/to/book.epub"}' | python scripts/parse_epub.py

# Output
{ "title": "...", "author": "...", "chapters": [{ "id": "...", "title": "...", "content": "..." }] }
```

Tout nouveau script suit ce même pattern : `payload = json.load(sys.stdin)` / `json.dump(result, sys.stdout)`.

---

## Studio — Concepts clés pour ce projet

**Template `analysis/`** — Ce projet suit le pattern analysis : content-extraction → entity-recognition → structuring.

**Script executor** — Stages sans LLM. Le stage appelle un script shell/Python au lieu d'un agent. Configuré dans le pipeline YAML via `executor: script` + `command: python scripts/parse_epub.py`.

**Context propagation** — Chaque stage déclare `context.include: [input, previous_stage_output]`. Sans ça, le stage n'a accès à rien.

**Groups** — Si entity-resolution rejette (doublons non résolus), le group peut itérer. Le dernier stage du group doit avoir `post_validation.rejection_detection` dans son contract.

**studio-run** — Permet de spawner un sous-pipeline (ex: lancer wiki-generation une fois par entité). Nécessite STU-105.

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
- **Prisma + Python** : Prisma génère un client JS. Si tu veux accéder à la DB depuis Python, utilise `prisma-client-py` ou requêtes SQLite directes.
- **`.studio/config.yaml` est gitignored** — contient les API keys. Ne jamais commiter ce fichier.
- **`.studio/runs/`** est gitignored — données runtime, ne pas commiter.
- **Commité dans git** : `.studio/pipelines/`, `.studio/agents/`, `.studio/contracts/`, `.studio/tools/`, `.studio/registry.lock.json`.
