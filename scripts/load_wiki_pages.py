#!/usr/bin/env python3
"""
Stage: wiki-generation (script executor, no LLM)

Loads pre-generated wiki pages from processing_output/wiki_pages.json.
Run scripts/generate_wiki_pages.py first to generate the pages.

Input (Studio stdin): consumed and ignored
Output (stdout): {"pages": [...]}
"""

import json
import os
import sys

OUTPUT_FILE = "processing_output/wiki_pages.json"


def main() -> None:
    json.load(sys.stdin)  # consume stdin (Studio requires it)

    if not os.path.exists(OUTPUT_FILE):
        print(
            f"[ERROR] {OUTPUT_FILE} not found.\n"
            "Run first: python scripts/generate_wiki_pages.py",
            file=sys.stderr,
        )
        sys.exit(1)

    with open(OUTPUT_FILE, encoding="utf-8") as f:
        data = json.load(f)

    pages = data.get("pages", [])
    print(f"[load-wiki-pages] Loaded {len(pages)} pages from {OUTPUT_FILE}", file=sys.stderr)
    json.dump({"pages": pages}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
