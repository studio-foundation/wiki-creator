#!/usr/bin/env python3
"""
Loader stage for wiki-generation pipeline.
Reads <series_dir>/processing_output/entities_classified.json and re-emits it as stage output.
Named 'entity-classification' in the pipeline so wiki_preparation.py finds it unchanged.
"""
import json
import os
import sys
from pathlib import Path

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wiki_creator import studio_io


def main() -> None:
    payload = studio_io.read_payload()
    paths = studio_io.paths_from_payload(payload)
    path = str(paths.processing / "entities_classified.json")
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
