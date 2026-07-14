.PHONY: run run-coref run-extraction run-resolution run-preparation run-generation pages-export run-all \
        test-extraction test-clustering test-relationships classify-relationships classify-relationships-dry \
        run-events generate-synopsis generate-synopsis-dry \
        generate-event-pages generate-event-pages-dry \
        generate-pages generate-pages-dry generate-pages-primary generate-pages-entity \
        test test-coref test-coref-parallel \
        smoke golden golden-update \
        clean

#BOOK ?= library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.yaml
BOOK ?= library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
SERIES ?= library/christopher_paolini/inheritance
CLEAN ?=--clean
#BOOK ?= library/brandon_sanderson/the_stormlight_archives/books/01-the_way_of_kings.yaml
#BOOK ?= library/c_w_lewis/narnia/books/01-the_lion_the_witch_and_the_wardrobe.yaml
#BOOK ?= library/j_r_r_tolkien/lord_of_the_rings/books/00-the_hobbit.yaml

# Subset test runs (STU-497): cap extraction to the first N chapters so any
# feature can be exercised end-to-end in seconds. `make run BOOK=... MAX_CHAPTERS=3`.
# Exported here once so EVERY target (run, run-from-*, run-extraction, …) honors it —
# parse_epub reads WIKI_MAX_CHAPTERS and truncates; all downstream stages just
# consume the shrunk artifacts. Pair with the entity subset (ENTITY=..., below) to
# also slice the generation axis. Unset = full run, no behavior change.
ifdef MAX_CHAPTERS
export WIKI_MAX_CHAPTERS := $(MAX_CHAPTERS)
endif

# Full run via orchestrator
run:
	python run_wiki.py --book $(BOOK)

# Full series run: every tome under SERIES/books/ in order (STU-487)
run-series:
	python run_wiki.py --series $(SERIES)

# Relationship extraction with coreference on real book data.
# device auto-detects CUDA (STU-466); on GPU workers is forced to 1.
# Override device with: make run-coref COREF_DEVICE=cpu
COREF_DEVICE ?=
run-coref: test-extraction
	python scripts/relationship_extraction.py --live --book $(BOOK) --coref \
		$(if $(COREF_DEVICE),--coref-device $(COREF_DEVICE),)

run-angel-game:
	python run_wiki.py --book library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.yaml

run-tog:
	python run_wiki.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml

# Individual pipeline stages
run-extraction:
	studio run wiki-extraction --input-file $(BOOK) --live --verbose

run-resolution:
	studio run wiki-resolution --input-file $(BOOK) --live --verbose

generate-pages:
	python scripts/generate_wiki_pages.py --book $(BOOK)

generate-pages-dry:
	python scripts/generate_wiki_pages.py --book $(BOOK) --dry-run

# Subset re-run (STU-497): regenerate only a slice, preserve every other page.
generate-pages-primary:
	python scripts/generate_wiki_pages.py --book $(BOOK) --importance principal --force

# ENTITY required, e.g. make generate-pages-entity ENTITY="Celaena Sardothien"
generate-pages-entity:
	python scripts/generate_wiki_pages.py --book $(BOOK) --entities "$(ENTITY)" --force

generate-synopsis:
	python scripts/generate_book_synopsis.py --book $(BOOK)

generate-synopsis-dry:
	python scripts/generate_book_synopsis.py --book $(BOOK) --dry-run

generate-event-pages:
	python scripts/generate_event_pages.py --book $(BOOK)

generate-event-pages-dry:
	python scripts/generate_event_pages.py --book $(BOOK) --dry-run

run-preparation:
	studio run wiki-preparation --input-file $(BOOK) --live --verbose

pages-export:
	studio run pages-export --input-file $(BOOK) --live --verbose

run-generation: run-preparation generate-pages generate-synopsis generate-event-pages pages-export

# Orchestrator shortcuts
run-from-extraction:
	python run_wiki.py --book $(BOOK) --restart wiki-extraction $(CLEAN)

run-from-resolution:
	python run_wiki.py --book $(BOOK) --restart wiki-resolution $(CLEAN)

run-from-preparation:
	python run_wiki.py --book $(BOOK) --restart wiki-preparation $(CLEAN)

run-from-generation:
	python run_wiki.py --book $(BOOK) --restart wiki-generation $(CLEAN)

run-status:
	python run_wiki.py --book $(BOOK) --status

test-extraction:
	python scripts/test_extraction.py --book $(BOOK)

test-clustering:
	python scripts/entity_clustering.py --test

test-relationships:
	python scripts/relationship_extraction.py --test

classify-relationships:
	python scripts/classify_relationships.py --book $(BOOK)

classify-relationships-dry:
	python scripts/classify_relationships.py --book $(BOOK) --dry-run

run-events:
	python scripts/build_event_layer.py --book $(BOOK)

test: test-extraction
	python scripts/entity_clustering.py --live --book $(BOOK)
	python scripts/relationship_extraction.py --live --book $(BOOK)

test-coref: test-extraction
	python scripts/entity_clustering.py --live --book $(BOOK)
	python scripts/relationship_extraction.py --live --book $(BOOK) --coref

test-coref-parallel: test-extraction
	python scripts/entity_clustering.py --live --book $(BOOK)
	python scripts/relationship_extraction.py --live --book $(BOOK) --coref --workers 8

smoke:  ## End-to-end smoke test on the committed fixture novella (no real EPUB needed)
	python -m pytest tests/test_e2e_smoke.py -q

golden:  ## Golden regression run: chained resolution stages vs committed goldens (fast, no spaCy/LLM)
	python -m pytest tests/test_e2e_golden.py -q

golden-update:  ## Regenerate goldens after an INTENTIONAL behavior change, then review the diff
	UPDATE_GOLDENS=1 python -m pytest tests/test_e2e_golden.py -q

clean:  ## Remove generated files (keeps .gitkeep sentinels)
	@SERIES_DIR=$$(python -c "from wiki_creator.paths import book_paths_from_yaml; p = book_paths_from_yaml('$(BOOK)'); print(p.processing.parent.parent)"); \
	find $$SERIES_DIR/processing_output $$SERIES_DIR/wiki_inputs $$SERIES_DIR/output \
	     -not -name '.gitkeep' -delete 2>/dev/null || true
