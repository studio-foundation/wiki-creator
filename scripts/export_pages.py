#!/usr/bin/env python3
"""Re-export the wikitext (`.wiki`) files from artifacts already on disk.

The `pages` slice (`generate_wiki_pages.py --entities/--force`) rewrites
`wiki_pages.json` only; the `.wiki` files are produced by the pages-export tail
(`assemble` -> `copyright-check` -> `wiki-export`), which reads its input from
the Studio context, not from disk. This driver chains those three stages from
disk so a slice can refresh its `.wiki` without a full pipeline run.

    python scripts/export_pages.py --book <book.yaml>

Deterministic and LLM-free — it re-renders every page currently in
`wiki_pages.json` (plus synopsis/event/collation artifacts) to wikitext.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run_stage(script: str, payload: dict, *, capture: bool) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, script],
        input=json.dumps(payload),
        text=True,
        cwd=PROJECT_ROOT,
        capture_output=capture,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--book", required=True, help="Path to the book YAML")
    args = parser.parse_args()

    ctx = Path(args.book).read_text(encoding="utf-8")

    assemble = _run_stage(
        "scripts/assemble_wiki_pages.py",
        {"additional_context": ctx, "previous_outputs": {}, "all_stage_outputs": {}},
        capture=True,
    )
    if assemble.returncode != 0:
        sys.stderr.write(assemble.stderr)
        return assemble.returncode
    sys.stderr.write(assemble.stderr)

    copyright = _run_stage(
        "scripts/copyright_check.py",
        {"additional_context": ctx, "previous_outputs": {"wiki-generation": json.loads(assemble.stdout)}},
        capture=True,
    )
    if copyright.returncode != 0:
        sys.stderr.write(copyright.stderr)
        return copyright.returncode
    sys.stderr.write(copyright.stderr)

    export = _run_stage(
        "scripts/wiki_export.py",
        {"additional_context": ctx, "previous_outputs": {"copyright-check": json.loads(copyright.stdout)}},
        capture=False,
    )
    return export.returncode


if __name__ == "__main__":
    raise SystemExit(main())
