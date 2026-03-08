.PHONY: run run-extraction run-resolution run-generation run-all \
        test-extraction test-clustering test-relationships test test-coref test-coref-parallel \
        clean

BOOK ?= books/carlos-ruiz-zafon/le-jeu-de-lange.yaml

# Full run via orchestrator
run:
	python run_wiki.py --book $(BOOK)

# Individual pipeline stages
run-extraction:
	studio run wiki-extraction --input-file $(BOOK) --live --verbose

run-resolution:
	studio run wiki-resolution --input-file $(BOOK) --live --verbose

generate-pages:
	python scripts/generate_wiki_pages.py

generate-pages-dry:
	python scripts/generate_wiki_pages.py --dry-run

pages-export:
	studio run wiki-generation --input-file $(BOOK) --live --verbose

run-generation: generate-pages && pages-export

# Orchestrator shortcuts
run-from-resolution:
	python run_wiki.py --book $(BOOK) --restart wiki-resolution

run-from-generation:
	python run_wiki.py --book $(BOOK) --restart wiki-generation

run-status:
	python run_wiki.py --book $(BOOK) --status

test-extraction:
	python scripts/test_extraction.py

test-clustering:
	python scripts/entity_clustering.py --test

test-relationships:
	python scripts/relationship_extraction.py --test

test: test-extraction
	python scripts/entity_clustering.py --live
	python scripts/relationship_extraction.py --live

test-coref: test-extraction
	python scripts/entity_clustering.py --live
	python scripts/relationship_extraction.py --live --coref

test-coref-parallel: test-extraction
	python scripts/entity_clustering.py --live
	python scripts/relationship_extraction.py --live --coref --workers 8

clean:
	rm -rf processing_output/ wiki_inputs/ output/wiki/
	rm -f persons_full.json places_full.json orgs_full.json chapters.json
