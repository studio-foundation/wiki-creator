#!/usr/bin/env python3
"""Pre-step of the entity-species split (STU-457): build the roster input.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits the rendered PERSON roster and whether a verdict is still needed — the
`call: entity-species-verdict` stage that follows runs the LLM only when
`needs_verdict` is true (cache miss). The genre gate (STU-574) is emitted as
`needs_verdict: false`: a real-world-cast book (`ner.invented_names` false) has
no species to attribute, so the call is condition-skipped. The verdict cache
stays keyed on the roster rows themselves; on a cache miss the stale cache is
unlinked here — a failed call must not leave a verdict made for a different
roster on disk.

Input:  { "additional_context": "<book yaml>" }
Output: { "book_title", "roster", "needs_verdict" }
"""

import json
import sys
from pathlib import Path

import yaml

from scripts.entity_status import contexts_by_entity
from wiki_creator import studio_io
from wiki_creator.entity_species import CACHE_VERSION, roster_rows
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.ner import ner_config
from wiki_creator.registry import Registry
from wiki_creator.roster import load_cache, render_roster


def _emit(book_title: str = "", roster: str = "", needs_verdict: bool = False) -> None:
    json.dump(
        {"book_title": book_title, "roster": roster, "needs_verdict": needs_verdict},
        sys.stdout,
        ensure_ascii=False,
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
        Path(cache_path).unlink(missing_ok=True)
        _emit()
        return

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-species] registry.json not found in {paths.processing} — "
            "no character renders a species",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        _emit()
        return

    lang_cfg = load_lang_config(book_language(ctx))
    markers = list(lang_cfg.get("species_markers", []))
    if not markers:
        print(
            "[entity-species] no `species_markers` in this language's cue_words — "
            "no snippet can be selected, so no character renders a species",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        _emit()
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
        Path(cache_path).unlink(missing_ok=True)
        _emit()
        return

    rows = roster_rows(persons, contexts, markers)
    needs_verdict = load_cache(cache_path, rows, CACHE_VERSION) is None
    if needs_verdict:
        Path(cache_path).unlink(missing_ok=True)

    _emit(
        book_title=str(ctx.get("title") or paths.processing.name),
        roster=render_roster(rows),
        needs_verdict=needs_verdict,
    )


if __name__ == "__main__":
    main()
