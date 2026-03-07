#!/usr/bin/env python3
"""
Loader stage for wiki-generation pipeline.
Reads processing_output/entities_classified.json and re-emits it as stage output.
Named 'entity-classification' in the pipeline so wiki_preparation.py finds it unchanged.
"""
import json
import os
import sys


def main() -> None:
    json.load(sys.stdin)
    path = "processing_output/entities_classified.json"
    if not os.path.exists(path):
        print(
            f"[ERROR] {path} not found. Run wiki-resolution first:\n"
            "  studio run wiki-resolution --input-file <book.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    json.dump(data, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
