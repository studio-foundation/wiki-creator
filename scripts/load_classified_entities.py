#!/usr/bin/env python3
"""
Loader stage for wiki-generation pipeline.
Reads processing_output/entities_classified.json and re-emits it as stage output.
Named 'entity-classification' in the pipeline so wiki_preparation.py finds it unchanged.
"""
import json
import os
import sys
from pathlib import Path
import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_epub, BookPaths


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)


def main() -> None:
    payload = json.load(sys.stdin)
    paths = _paths_from_payload(payload)
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
