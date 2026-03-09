.PHONY: run run-extraction run-resolution run-preparation run-generation pages-export run-all \
        test-extraction test-clustering test-relationships test test-coref test-coref-parallel \
        clean

#BOOK ?= library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.yaml
BOOK ?= library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
# Full run via orchestrator
run:
	python run_wiki.py --book $(BOOK)

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

run-preparation:
	studio run wiki-preparation --input-file $(BOOK) --live --verbose

pages-export:
	studio run pages-export --input-file $(BOOK) --live --verbose

run-generation: run-preparation generate-pages pages-export

# Orchestrator shortcuts
run-from-resolution:
	python run_wiki.py --book $(BOOK) --restart wiki-resolution

run-from-generation:
	python run_wiki.py --book $(BOOK) --restart wiki-generation

run-status:
	python run_wiki.py --book $(BOOK) --status

test-extraction:
	python scripts/test_extraction.py --book $(BOOK)

test-clustering:
	python scripts/entity_clustering.py --test

test-relationships:
	python scripts/relationship_extraction.py --test

test: test-extraction
	python scripts/entity_clustering.py --live --book $(BOOK)
	python scripts/relationship_extraction.py --live --book $(BOOK)

test-coref: test-extraction
	python scripts/entity_clustering.py --live --book $(BOOK)
	python scripts/relationship_extraction.py --live --book $(BOOK) --coref

test-coref-parallel: test-extraction
	python scripts/entity_clustering.py --live --book $(BOOK)
	python scripts/relationship_extraction.py --live --book $(BOOK) --coref --workers 8

clean:  ## Remove generated files (keeps .gitkeep sentinels)
	@SERIES_DIR=$$(python -c "from wiki_creator.paths import book_paths_from_yaml; p = book_paths_from_yaml('$(BOOK)'); print(p.processing.parent.parent)"); \
	find $$SERIES_DIR/processing_output $$SERIES_DIR/wiki_inputs $$SERIES_DIR/output \
	     -not -name '.gitkeep' -delete 2>/dev/null || true
