.PHONY: run test-extraction

run:
	studio run wiki-pipeline --input-file .studio/inputs/book.input.yaml --live

test-extraction:
	python scripts/test_extraction.py
