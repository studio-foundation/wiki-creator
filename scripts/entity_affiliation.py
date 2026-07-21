#!/usr/bin/env python3
"""entity-affiliation — which faction does each character belong to?

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Post-step of the entity-affiliation split (STU-457). The LLM verdict arrives
from the `call: entity-affiliation-verdict` stage (native invocation, no
subprocess); this stage parses it, caches it to `entity_affiliation.json`,
which wiki-preparation then stamps onto the batch entity so
`generate_wiki_pages.py` can render the `affiliation` infobox slot.

It sits in wiki-preparation and not wiki-resolution, for STU-488's reasons: it
changes no identity, and resolution is chained by `make golden`, which stays
LLM-free by construction.

Never fails a run: a book whose verdict cannot be obtained renders no slot at
all, loudly.

Input:  { "additional_context": "<book yaml>",
          "all_stage_outputs": {"entity-affiliation-verdict": {...}} }
Output: { "decided", "roster" }
"""
import sys
from pathlib import Path

import yaml

from scripts.entity_status import contexts_by_entity, verdict_from_payload
from wiki_creator import studio_io
from wiki_creator.entity_affiliation import (
    CACHE_VERSION,
    parse_affiliation_verdict,
    roster_rows,
)
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.registry import Registry
from wiki_creator.roster import load_cache, save_cache

VERDICT_STAGE = "entity-affiliation-verdict"


def resolve_affiliation(
    rows: list[dict], verdict_output: object | None, cache_path: Path
) -> dict[str, dict]:
    """Verified affiliation per character, from cache or the call stage's verdict.

    Never raises. Every failure path returns {} — every character then renders no
    `affiliation` slot, which is what an OPT slot with no value does.
    """
    cached = load_cache(cache_path, rows, CACHE_VERSION)
    if cached is not None:
        return cached
    if verdict_output is None:
        return _give_up("no verdict (call skipped or failed)", rows)

    verdicts = parse_affiliation_verdict(verdict_output, rows)
    save_cache(cache_path, rows, verdicts, CACHE_VERSION)
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-affiliation] WARNING: {error} — none of the {len(rows)} characters "
        "render an affiliation",
        file=sys.stderr,
    )
    return {}


def main() -> None:
    payload = studio_io.read_payload()
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    paths = studio_io.paths_from_payload(payload)
    cache_path = paths.processing / "entity_affiliation.json"

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-affiliation] registry.json not found in {paths.processing} — "
            "no character renders an affiliation",
            file=sys.stderr,
        )
        studio_io.write_output({"decided": 0, "roster": 0})
        return

    lang_cfg = load_lang_config(book_language(ctx))
    markers = list(lang_cfg.get("affiliation_markers", []))
    if not markers:
        print(
            "[entity-affiliation] no `affiliation_markers` in this language's cue_words — "
            "no snippet can be selected, so no character renders an affiliation",
            file=sys.stderr,
        )
        studio_io.write_output({"decided": 0, "roster": 0})
        return

    contexts = contexts_by_entity(registry)
    persons = [
        {"canonical_name": record.canonical_name, "aliases": record.aliases}
        for record in registry.entities
        if record.entity_type == "PERSON" and record.canonical_name in contexts
    ]
    if not persons:
        print(
            "[entity-affiliation] no PERSON entity with context — nothing to decide",
            file=sys.stderr,
        )
        studio_io.write_output({"decided": 0, "roster": 0})
        return

    rows = roster_rows(persons, contexts, markers)
    verdicts = resolve_affiliation(
        rows,
        verdict_output=verdict_from_payload(payload, VERDICT_STAGE),
        cache_path=cache_path,
    )

    print(
        f"[entity-affiliation] {len(verdicts)}/{len(rows)} characters have a faction; "
        "the rest render no slot",
        file=sys.stderr,
    )
    for name, verdict in sorted(verdicts.items()):
        print(f"[entity-affiliation]   {name}: {verdict['affiliation']}", file=sys.stderr)
    studio_io.write_output({"decided": len(verdicts), "roster": len(rows)})


if __name__ == "__main__":
    main()
