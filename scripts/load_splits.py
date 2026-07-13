#!/usr/bin/env python3
"""
Loader stage for wiki-resolution pipeline.
Reads <series_dir>/processing_output/splits.json and re-emits it as stage output.
Named 'split-clusters' in the pipeline so entity-resolution group conditions work unchanged.
"""
import os
import sys

from wiki_creator import studio_io
from wiki_creator.types import Splits


def main() -> None:
    payload = studio_io.read_payload()
    paths = studio_io.paths_from_payload(payload)
    path = paths.processing / "splits.json"
    if not os.path.exists(path):
        print(
            f"[ERROR] {path} not found. Run wiki-extraction first:\n"
            "  studio run wiki-extraction --input-file <book.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)
    splits = studio_io.load_artifact(path, Splits)
    studio_io.write_output(studio_io.to_dict(splits))


if __name__ == "__main__":
    main()
