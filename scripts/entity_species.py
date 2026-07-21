#!/usr/bin/env python3
"""entity-species — which species/race is each character? (STU-574)

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Post-step of the entity-species split (STU-457). The LLM verdict arrives from
the `call: entity-species-verdict` stage (native invocation, no subprocess);
this stage parses it, caches it to `entity_species.json`, which
wiki-preparation then stamps onto the batch entity so `generate_wiki_pages.py`
can render the `species` infobox slot.

It sits in wiki-preparation and not wiki-resolution, for STU-488's reasons: it
changes no identity, and resolution is chained by `make golden`, which stays
LLM-free by construction.

Genre-gated (the slot is `genre_gated: true`): only a book whose world has
invented species has a species to attribute. A real-world-cast book skips the
stage entirely — the gate is `ner.invented_names`, the same signal that already
distinguishes those worlds, not a new key (STU-537: the property is the book's,
not the pipeline's). The gate lives in the pre stage (`needs_verdict: false`)
and is re-checked here.

Never fails a run: a book whose verdict cannot be obtained renders no slot at
all, loudly.

Input:  { "additional_context": "<book yaml>",
          "all_stage_outputs": {"entity-species-verdict": {...}} }
Output: { "decided", "roster" }
"""
import sys
from pathlib import Path

import yaml

from scripts.entity_status import contexts_by_entity, verdict_from_payload
from wiki_creator import studio_io
from wiki_creator.entity_species import (
    CACHE_VERSION,
    parse_species_verdict,
    roster_rows,
)
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.ner import ner_config
from wiki_creator.registry import Registry
from wiki_creator.roster import load_cache, save_cache

VERDICT_STAGE = "entity-species-verdict"


def resolve_species(
    rows: list[dict], verdict_output: object | None, cache_path: Path
) -> dict[str, dict]:
    """Verified species per character, from cache or the call stage's verdict.

    Never raises. Every failure path returns {} — every character then renders no
    `species` slot, which is what an OPT slot with no value does.
    """
    cached = load_cache(cache_path, rows, CACHE_VERSION)
    if cached is not None:
        return cached
    if verdict_output is None:
        return _give_up("no verdict (call skipped or failed)", rows)

    verdicts = parse_species_verdict(verdict_output, rows)
    save_cache(cache_path, rows, verdicts, CACHE_VERSION)
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-species] WARNING: {error} — none of the {len(rows)} characters "
        "render a species",
        file=sys.stderr,
    )
    return {}


def main() -> None:
    payload = studio_io.read_payload()
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    paths = studio_io.paths_from_payload(payload)
    cache_path = paths.processing / "entity_species.json"

    if not ner_config(ctx).invented_names:
        print(
            "[entity-species] this book's world has no invented species "
            "(ner.invented_names is false) — no character renders a species",
            file=sys.stderr,
        )
        studio_io.write_output({"decided": 0, "roster": 0})
        return

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-species] registry.json not found in {paths.processing} — "
            "no character renders a species",
            file=sys.stderr,
        )
        studio_io.write_output({"decided": 0, "roster": 0})
        return

    lang_cfg = load_lang_config(book_language(ctx))
    markers = list(lang_cfg.get("species_markers", []))
    if not markers:
        print(
            "[entity-species] no `species_markers` in this language's cue_words — "
            "no snippet can be selected, so no character renders a species",
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
            "[entity-species] no PERSON entity with context — nothing to decide",
            file=sys.stderr,
        )
        studio_io.write_output({"decided": 0, "roster": 0})
        return

    rows = roster_rows(persons, contexts, markers)
    verdicts = resolve_species(
        rows,
        verdict_output=verdict_from_payload(payload, VERDICT_STAGE),
        cache_path=cache_path,
    )

    print(
        f"[entity-species] {len(verdicts)}/{len(rows)} characters have a species; "
        "the rest render no slot",
        file=sys.stderr,
    )
    for name, verdict in sorted(verdicts.items()):
        print(f"[entity-species]   {name}: {verdict['species']}", file=sys.stderr)
    studio_io.write_output({"decided": len(verdicts), "roster": len(rows)})


if __name__ == "__main__":
    main()
