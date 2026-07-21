# Wiki Creator

**Powered by [Studio](https://github.com/studio-foundation/studio)** -- agentic pipeline orchestrator with structural validation.

> **Status: Active development.** This project is a work in progress and is not feature-complete. Expect rough edges and breaking changes.

Wiki Creator takes EPUB books and automatically extracts characters, locations, organizations, and their relationships, then generates complete wiki pages with infoboxes and wikitext export. It combines Python NLP (spaCy, GLiNER, coreference resolution) with LLM-powered agents orchestrated by Studio pipelines that validate every output against contracts.

---

## How it works

The workflow is split into five Studio pipelines, each with structurally validated stages. Every stage declares the files it writes (`expected_outputs.files` in its contract), so a missing artifact fails the stage that owns it.

1. **wiki-extraction** -- Parses the EPUB, classifies front/back matter out of the narrative, extracts entities, clusters them, and splits by category (persons, places, organizations, factions, events).

2. **wiki-resolution** -- Summarizes each chapter, resolves entity clusters, extracts the inter-entity co-occurrence graph, merges aliases (lexical rules, then a contextual LLM adjudication pass), classifies entities using an LLM agent with a RALPH validation loop, and accumulates the series registry across tomes. Every stage up to the adjudication one is deterministic and offline.

3. **wiki-preparation** -- Discovers and types the relationships, fills the per-book infobox facts (status, affiliation, species), builds the character graph and the event layer, then batches everything into wiki input files.

4. **wiki-pages** -- Fans out over the planned page/section/relation calls, dispatching one `wiki-page-item` child run each (an engine `map` stage; per-item resume replays already-generated calls). Each child generates a page using an LLM agent inside a generation-validation group (max 3 iterations). A validator checks each page; rejected pages trigger a group retry with accumulated feedback. Validation includes anti-hallucination grounding against the source excerpts: proper nouns that never appear in the excerpts are rejected outright, and an optional LLM check (`validation.grounding.llm: true` in the book YAML, Ollama-backed) verifies that factual claims are supported by the excerpts.

5. **pages-export** -- Assembles the generated pages, runs a copyright check (no verbatim passages from the source), and exports to wikitext format.

## Getting started

### Prerequisites

- Python 3.11+
- [Studio CLI](https://github.com/studio-foundation/studio) installed from source
- The spaCy models the books declare — installed by the `models` extra below
  (`en_core_web_lg`, `fr_core_news_lg`; ~1 GB). Skipping it does not fail the
  run: a missing model falls back to a smaller sibling of the same language and
  warns, so the book runs on a model it did not declare.
- [GLiNER](https://github.com/urchade/GLiNER) — only for books whose YAML sets
  `ner.invented_names: true`, i.e. novels whose proper nouns a stock model never
  memorized. There, GLiNER finds the entities by prompt and spaCy keeps doing the
  tokenizing, tagging and sentence splitting. Optional extra (pulls torch).

> **Language support:** page generation and validation follow the book's own
> language by default (`output_language` defaults to `book_language` — STU-607),
> so an English source yields an English wiki. Set a top-level `language:` key in
> your book YAML (e.g. `language: en`) to declare it, or override the output
> language alone with `generation.output_language`. POV detection and cue words
> currently support `fr` and `en`.

### Setup

```bash
git clone https://github.com/studio-foundation/wiki-creator.git
cd wiki-creator
pip install -e ".[models]"
# Optional, each pulls torch (large download):
pip install -e ".[gliner]"   # books with ner.invented_names: true
pip install -e ".[coref]"    # books with coref: true
cp .studio/config.example.yaml .studio/config.yaml
```

`defaults` in that file drives every LLM stage — no agent declares a model of
its own. It ships pointing at the provider the project's own runs use; the
example documents what swapping it costs.

### Run

Place a book YAML config in `library/<author>/<series>/books/` with the corresponding EPUB, then:

```bash
# Full pipeline (extraction through export)
make run BOOK=library/c_w_lewis/narnia/books/01-the_lion_the_witch_and_the_wardrobe.yaml

# Or run individual stages
make run-extraction
make run-resolution
make run-preparation
make generate-pages
make pages-export

# Run tests
pytest -q

# End-to-end smoke test — runs the EPUB parse + NER extraction stages on a
# small committed fixture novella, no real book or LLM required
make smoke

# Golden regression — chains the deterministic resolution stages on the same
# fixture and diffs every stage output against committed goldens
make golden
```

## Project structure

```
wiki-creator/
├── .studio/              # Studio configs (pipelines, agents, contracts, tools)
├── library/              # Book configs (.yaml) and EPUBs, per author/series
├── wiki_creator/         # Python package (NER, clustering, export logic)
├── scripts/              # Pipeline stage scripts (called by Studio)
├── tests/                # Test suite (pytest)
└── Makefile              # Developer commands
```

## License

GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later) -- see [LICENSE](./LICENSE).

Copyleft by conviction, matching [Studio](https://github.com/studio-foundation/studio): anyone may use, study, and modify Wiki Creator, but modified versions -- including those offered as a network service -- must share their source under the same terms. The AGPL applies to the *program*; the wiki pages it generates are your output, not covered by this license.
