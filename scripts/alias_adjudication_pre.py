#!/usr/bin/env python3
"""Pre-step of the alias-adjudication split (STU-589): build the roster input.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits the rendered PERSON roster and whether a verdict is still needed — the
`call: alias-adjudication-verdict` stage that follows runs the LLM only when
`needs_verdict` is true (cache miss, roster of at least two). The verdict cache
stays keyed on the roster rows themselves (STU-539), so this stage deciding
"no call needed" is exactly the old in-script cache hit.

Input:  { "all_stage_outputs": {"alias-resolution": {...}} }
Output: { "book_title", "roster", "needs_verdict" }
"""

import json
import sys

import yaml

from scripts.alias_resolution import _gather_contexts, _load_persons_full
from wiki_creator import studio_io
from wiki_creator.alias_adjudication import load_cached_merges, render_roster, roster_rows


def main() -> None:
    payload = studio_io.read_payload()
    all_stage_outputs = payload.get("all_stage_outputs", {})
    previous_outputs = payload.get("previous_outputs", {})
    source = (
        all_stage_outputs.get("alias-resolution")
        or previous_outputs.get("alias-resolution")
        or payload.get("previous_stage_output")
        or {}
    )
    entities = source.get("entities", [])
    persons = [
        entity for entity in entities
        if entity.get("type") == "PERSON" and entity.get("relevant", True)
    ]

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    paths = studio_io.paths_from_payload(payload)

    if len(persons) < 2:
        json.dump(
            {"book_title": "", "roster": "", "needs_verdict": False},
            sys.stdout,
            ensure_ascii=False,
        )
        return

    persons_full = _load_persons_full(paths.processing)
    contexts = {
        entity["canonical_name"]: _gather_contexts(entity, persons_full) for entity in persons
    }
    rows = roster_rows(persons, contexts)
    cached = load_cached_merges(paths.processing / "alias_adjudication.json", rows)

    json.dump(
        {
            "book_title": str(ctx.get("title") or paths.processing.name),
            "roster": render_roster(rows),
            "needs_verdict": cached is None,
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
