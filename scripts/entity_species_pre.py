#!/usr/bin/env python3
"""Pre-step of the entity-species split (STU-457/753/2018): build the fan-out items.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Emits one item per PERSON entity: the `call: entity-species-verdict` stage
that follows fans out one single-shot verdict call per character via the
engine map (STU-589/605-style per-item resume). The genre gate (STU-574) is
emitted as `needs_verdict: false`: a real-world-cast book
(`ner.invented_names` false) has no species to attribute, so the call is
condition-skipped. Each item carries identity (name, aliases) and the passages
`book_search.select_passages` picked for it (STU-2018): code chooses the
evidence, within a fixed token budget, and the model judges it in one call
with no tools. The passages ride in the item, so the engine's per-item resume
re-runs a character whose evidence changed. `prompt_fingerprint` still covers
the agent's system prompt and the book's own text.

Input:  { "additional_context": "<book yaml>" }
Output: { "book_title", "entities", "prompt_fingerprint", "needs_verdict" }
"""

import json
import sys
from pathlib import Path

import yaml

from scripts.entity_status import contexts_by_entity
from wiki_creator import studio_io
from wiki_creator.book_search import load_chapters, with_passages
from wiki_creator.entity_species import entity_rows
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.ner import ner_config
from wiki_creator.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_AGENT_YAML = PROJECT_ROOT / ".studio" / "agents" / "entity-species.agent.yaml"


def _emit(
    book_title: str = "",
    entities: list[dict] | None = None,
    prompt_fingerprint: str = "",
    needs_verdict: bool = False,
) -> None:
    json.dump(
        {
            "book_title": book_title,
            "entities": entities or [],
            "prompt_fingerprint": prompt_fingerprint,
            "needs_verdict": needs_verdict,
        },
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

    chapters = load_chapters(paths.processing)
    if not chapters:
        print(
            f"[entity-species] chapters.json not found in {paths.processing} — "
            "no passage to judge",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        _emit()
        return

    rows = entity_rows(persons)
    markers = load_lang_config(book_language(ctx), allow_en_fallback=True).get("species_markers", [])
    fingerprint = studio_io.prompt_fingerprint(
        [_AGENT_YAML, paths.processing / "chapters.json"], {}
    )

    _emit(
        book_title=str(ctx.get("title") or paths.processing.name),
        entities=with_passages(rows, paths.processing, markers),
        prompt_fingerprint=fingerprint,
        needs_verdict=True,
    )


if __name__ == "__main__":
    main()
