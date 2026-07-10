# Wiki Creator

**Powered by [Studio](https://github.com/studio-foundation/studio)** -- agentic pipeline orchestrator with structural validation.

> **Status: Active development.** This project is a work in progress and is not feature-complete. Expect rough edges and breaking changes.

Wiki Creator takes EPUB books and automatically extracts characters, locations, organizations, and their relationships, then generates complete wiki pages with infoboxes and wikitext export. It combines Python NLP (spaCy NER, coreference resolution) with LLM-powered agents orchestrated by Studio pipelines that validate every output against contracts.

---

## How it works

The workflow is split into four Studio pipelines, each with structurally validated stages:

1. **wiki-extraction** -- Parses the EPUB, runs spaCy NER to extract entities, clusters them, verifies entity types, and splits by category (persons, places, organizations).

2. **wiki-resolution** -- Resolves entity clusters (alias detection, merge), extracts inter-entity relationships from chapter text, and classifies entities using an LLM agent with a RALPH validation loop.

3. **wiki-preparation** -- Loads classified entities and EPUB data, generates chapter summaries (LLM agent with retry/validation), then batches everything into wiki input files.

4. **wiki-page-item** -- Generates individual wiki pages using an LLM agent inside a generation-validation group (max 3 iterations). A validator agent checks each page; rejected pages trigger a group retry with accumulated feedback.

5. **pages-export** -- Loads generated wiki pages, runs a copyright check (no verbatim passages from the source), and exports to wikitext format.

## Getting started

### Prerequisites

- Python 3.11+
- [Studio CLI](https://github.com/studio-foundation/studio) installed from source
- A spaCy model matching your book's language:
  - French books: `python -m spacy download fr_core_news_lg`
  - English books: `python -m spacy download en_core_web_sm`

> **Language support:** the pipeline is French-first — page generation and
> validation target French output by default. Set a top-level `language:` key
> in your book YAML (e.g. `language: en`) to disable French-only validation
> for books in other languages. POV detection and cue words currently support
> `fr` and `en`.

### Setup

```bash
git clone https://github.com/studio-foundation/wiki-creator.git
cd wiki-creator
pip install -e .
# Optional: coreference resolution support (pulls torch, large download)
pip install -e ".[coref]"
studio config set provider anthropic --api-key $ANTHROPIC_API_KEY
```

### Run

Place a book YAML config in `library/<author>/<series>/books/` with the corresponding EPUB, then:

```bash
# Full pipeline (extraction through export)
make run BOOK=library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml

# Or run individual stages
make run-extraction
make run-resolution
make run-preparation
make generate-pages
make pages-export

# Check status
make run-status

# Run tests
pytest -q

# End-to-end smoke test — runs the EPUB parse + NER extraction stages on a
# small committed fixture novella, no real book or LLM required
make smoke
```

## Project structure

```
wiki-creator/
├── .studio/              # Studio configs (pipelines, agents, contracts, tools)
├── library/              # Book configs (.yaml) and EPUBs, per author/series
├── wiki_creator/         # Python package (NER, clustering, export logic)
├── scripts/              # Pipeline stage scripts (called by Studio)
├── tests/                # Test suite (pytest)
├── Makefile              # Developer commands
└── run_wiki.py           # Local orchestrator script
```

## License

MIT -- see [LICENSE](./LICENSE)
