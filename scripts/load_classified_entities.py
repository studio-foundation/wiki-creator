#!/usr/bin/env python3
"""
Loader stage for wiki-generation pipeline.
Reads processing_output/entities_classified.json and re-emits it as stage output.
Named 'entity-classification' in the pipeline so wiki_preparation.py finds it unchanged.
"""
import json
import sys


def main() -> None:
    json.load(sys.stdin)  # consume stdin
    with open("processing_output/entities_classified.json", encoding="utf-8") as f:
        data = json.load(f)
    json.dump(data, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
