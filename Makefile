.PHONY: run run-extraction run-resolution run-generation run-all \
        test-extraction test-clustering test-relationships test test-coref test-coref-parallel

BOOK ?= books/carlos-ruiz-zafon/le-jeu-de-lange.yaml

# Full run via orchestrator
run:
	python run_wiki.py --book $(BOOK)

# Individual pipeline stages
run-extraction:
	studio run wiki-extraction --input-file $(BOOK) --live --verbose

run-resolution:
	studio run wiki-resolution --input-file $(BOOK) --live --verbose

run-generation:
	studio run wiki-generation --input-file $(BOOK) --live --verbose

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
