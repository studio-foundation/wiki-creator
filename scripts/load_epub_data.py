#!/usr/bin/env python3
"""
Loader stage for wiki-generation pipeline.
Reads processing_output/epub_data.json and re-emits it as stage output.
Named 'epub-parse' in the pipeline so wiki_export.py finds it in previous_outputs.
"""
import json
import os
import sys


def main() -> None:
    json.load(sys.stdin)
    path = "processing_output/epub_data.json"
    if not os.path.exists(path):
        print(
            f"[ERROR] {path} not found. Run wiki-extraction first:\n"
            "  studio run wiki-extraction --input-file <book.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    json.dump(data, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
