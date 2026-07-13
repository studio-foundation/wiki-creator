#!/usr/bin/env python3
"""
Loader stage for wiki-resolution pipeline.
Reads <series_dir>/processing_output/splits.json and re-emits it as stage output.
Named 'split-clusters' in the pipeline so entity-resolution group conditions work unchanged.
"""
import json
import os
import sys
from pathlib import Path

from wiki_creator import studio_io


def main() -> None:
    payload = studio_io.read_payload()
    paths = studio_io.paths_from_payload(payload)
    path = str(paths.processing / "splits.json")
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
