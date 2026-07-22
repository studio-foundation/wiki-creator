"""Live rendering of a fan-out's map items as they land (STU-626).

The four fan-outs run as native `call` stages inside `wiki-full` (STU-621), so a
`studio run wiki-full` settles hundreds of map items (chunks, pairs, chapters,
pages) with no per-unit visibility — only the end-of-stage aggregate. With
`studio run --stream-items` the engine emits one NDJSON line per settled item on
stderr; the `wiki` front door (STU-597) tails it and prints each unit's discovery
in reader vocabulary (`Alice <=> Dodo — allies`), so a run shows what it is
finding as it finds it — the way the old script-side subprocess loops did.

Domain rendering lives here, not in the engine: the engine is domain-agnostic and
only ships the item's raw output on the wire.
"""

from __future__ import annotations

import json
import subprocess
import sys
from functools import lru_cache
from typing import Any, TextIO

# Must match cli/src/commands/run.ts MAP_ITEM_STREAM_TAG in the Studio engine.
MAP_ITEM_STREAM_TAG = "@@studio:map_item@@"


def parse_item_line(line: str) -> dict | None:
    """Parse one tagged stderr line into its payload dict, or None if not tagged/malformed."""
    if not line.startswith(MAP_ITEM_STREAM_TAG):
        return None
    try:
        payload = json.loads(line[len(MAP_ITEM_STREAM_TAG):].strip())
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def render_map_item(payload: dict, out: TextIO | None = None) -> None:
    """Print one settled map item in the fan-out's own vocabulary.

    Dispatches on ``payload["map"]`` (the map-stage name: discover/classify/
    summarize/generate). Everything needed is on the payload — the item's label
    (its input identity) and the child run's output.
    """
    out = out or sys.stderr
    kind = payload.get("map")
    index = payload.get("index")
    status = payload.get("status")
    label = payload.get("label") or (f"#{index}" if index is not None else "?")
    raw_output = payload.get("output")
    output = raw_output if isinstance(raw_output, dict) else {}
    tick = "•" if payload.get("cached") else "→"

    if status == "failed":
        print(f"{tick} {label} — FAILED (will retry)", file=out)
        return

    if kind == "discover":
        relations = [r for r in (output.get("relations") or []) if isinstance(r, dict)]
        print(f"{tick} {label}", file=out)
        for rel in relations:
            a = rel.get("entity_a", "?")
            b = rel.get("entity_b", "?")
            rel_type = rel.get("relationship_type") or "—"
            print(f"    {a} <=> {b} — {rel_type}", file=out)
        if not relations:
            print("    (no relations)", file=out)
    elif kind == "classify":
        rel_type = output.get("relationship_type") or "—"
        confidence = output.get("confidence")
        suffix = f" ({confidence})" if confidence else ""
        print(f"{tick} {label} — {rel_type}{suffix}", file=out)
    elif kind == "summarize":
        bullets = output.get("summary_bullets") or []
        print(f"{tick} {label} — {len(bullets)} bullets", file=out)
    elif kind == "generate":
        print(f"{tick} {label} — page", file=out)
    else:
        print(f"{tick} {label} — {status}", file=out)


@lru_cache(maxsize=1)
def studio_supports_stream_items() -> bool:
    """Whether the installed ``studio`` CLI knows ``--stream-items``.

    A stale global CLI would abort on the unknown flag, so probe once and skip it
    — the stream is cosmetic, the run is not.
    """
    try:
        result = subprocess.run(
            ["studio", "run", "--help"], capture_output=True, text=True, timeout=30
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return "--stream-items" in (result.stdout or "")


def run_studio_with_stream(cmd: list[str]) -> int:
    """Run a `studio` command, rendering each map item live, and return its exit code.

    stdout is inherited so `--live` progress keeps its TTY (its spinners write to
    stdout); stderr is read line by line — a tagged line is rendered in reader
    vocabulary, every other line passes through unchanged so the stage's own logs
    still show.
    """
    proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, text=True)
    assert proc.stderr is not None
    for raw in proc.stderr:
        payload = parse_item_line(raw)
        if payload is not None:
            try:
                render_map_item(payload)
            except Exception:  # the stream is cosmetic, the run is not
                sys.stderr.write(raw)
        else:
            sys.stderr.write(raw)
    return proc.wait()
