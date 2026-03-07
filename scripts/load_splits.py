#!/usr/bin/env python3
"""
Loader stage for wiki-resolution pipeline.
Reads processing_output/splits.json and re-emits it as stage output.
Named 'split-clusters' in the pipeline so entity-resolution group conditions work unchanged.
"""
import json
import sys


def main() -> None:
    json.load(sys.stdin)  # consume stdin (Studio requires it)
    with open("processing_output/splits.json", encoding="utf-8") as f:
        data = json.load(f)
    json.dump(data, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
