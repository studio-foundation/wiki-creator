.PHONY: run test-extraction test-clustering

run:
	studio run wiki-pipeline --input-file .studio/inputs/book.input.yaml --live

test-extraction:
	python scripts/test_extraction.py

test-clustering:
	python scripts/entity_clustering.py --test
