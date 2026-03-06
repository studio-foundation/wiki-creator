.PHONY: run test-extraction test-clustering test-relationships test test-coref test-coref-parallel

run:
	studio run wiki-pipeline --input-file .studio/inputs/book.input.yaml --live

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
	python scripts/relationship_extraction.py --live --coref --workers 4
