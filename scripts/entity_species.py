#!/usr/bin/env python3
"""entity-species — which species/race is each character? (STU-574)

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Post-step of the entity-species split (STU-457/753). The `call:
entity-species-verdict` stage that precedes this one fans out one agentic
search-and-decide call per PERSON entity over the engine map (STU-589/605);
this stage folds the per-entity results, verifies each against the book's own
text, and writes `entity_species.json`, which `wiki_preparation.py` then
stamps onto the batch entity so `generate_wiki_pages.py` can render the
`species` infobox slot.

It sits in wiki-preparation and not wiki-resolution, for STU-488's reasons: it
changes no identity, and resolution is chained by `make golden`, which stays
LLM-free by construction.

Genre-gated (the slot is `genre_gated: true`): only a book whose world has
invented species has a species to attribute. A real-world-cast book skips the
stage entirely — the gate is `ner.invented_names`, the same signal that already
distinguishes those worlds, not a new key (STU-537: the property is the book's,
not the pipeline's). The gate lives in the pre stage (`needs_verdict: false`)
and is re-checked here.

Never fails a run: a book whose verdicts cannot be obtained renders no slot at
all, loudly.

Input:  { "additional_context": "<book yaml>",
          "all_stage_outputs": {"entity-species-verdict": {<map output>}} }
Output: { "decided", "roster" }
"""
import json
import sys
from pathlib import Path

import yaml

from scripts.entity_status import contexts_by_entity, verdict_from_payload
from wiki_creator import studio_io
from wiki_creator.book_search import full_text, load_chapters
from wiki_creator.entity_species import ARTIFACT_VERSION, entity_rows, parse_species_verdict
from wiki_creator.ner import ner_config
from wiki_creator.registry import Registry

VERDICT_STAGE = "entity-species-verdict"


def resolve_verdicts(rows: list[dict], map_output: object | None, book_text: str) -> dict[str, dict]:
    """Verified species per character, from the map fan-out's per-item results.

    Never raises. A missing map output, a missing per-item result, and a
    per-item verdict that fails grounding all fall through the same way: that
    one character renders no slot, which is what an OPT slot with no value does.
    """
    if map_output is None:
        return _give_up("no verdict (call skipped or failed)", rows)

    results_by_index: dict[int, dict] = {}
    if isinstance(map_output, dict):
        for result in map_output.get("results") or []:
            if isinstance(result, dict) and isinstance(result.get("index"), int):
                results_by_index[result["index"]] = result

    verdicts: dict[str, dict] = {}
    for i, row in enumerate(rows):
        result = results_by_index.get(i)
        if not result or result.get("status") != "success":
            continue
        verdict = parse_species_verdict(
            result.get("output"), row["name"], row["aliases"], book_text
        )
        if verdict is not None:
            verdicts[row["name"]] = verdict
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-species] WARNING: {error} — none of the {len(rows)} characters "
        "render a species",
        file=sys.stderr,
    )
    return {}


def _write_artifact(path: Path, verdicts: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": ARTIFACT_VERSION, "verdicts": verdicts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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

    rows = entity_rows(persons)
    book_text = full_text(load_chapters(paths.processing))
    verdicts = resolve_verdicts(rows, verdict_from_payload(payload, VERDICT_STAGE), book_text)
    _write_artifact(cache_path, verdicts)

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
