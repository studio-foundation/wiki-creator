.PHONY: run test-extraction test-clustering test

run:
	studio run wiki-pipeline --input-file .studio/inputs/book.input.yaml --live

test-extraction:
	python scripts/test_extraction.py

test-clustering:
	python scripts/entity_clustering.py --test

test: test-extraction
	python scripts/entity_clustering.py --live
