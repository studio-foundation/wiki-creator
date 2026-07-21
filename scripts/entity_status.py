#!/usr/bin/env python3
"""entity-status — is each character alive at the end of this book?

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Post-step of the entity-status split (STU-457). The LLM verdict arrives from
the `call: entity-status-verdict` stage (native invocation, no subprocess);
this stage parses it, caches it to `entity_status.json`, which wiki-preparation
then stamps onto the batch entity so `generate_wiki_pages.py` can render the
`status` infobox slot.

It sits in wiki-preparation and not wiki-resolution on purpose.
`alias-adjudication` sits inside resolution because it changes identity —
entity-classification reads its output. This changes no identity; it only
decorates the batch entity. And resolution is chained by `make golden`, which
stays LLM-free by construction.

Never fails a run: a book whose verdict cannot be obtained renders `unknown`
for every character, loudly.

Input:  { "additional_context": "<book yaml>",
          "all_stage_outputs": {"entity-status-verdict": {...}} }
Output: { "decided", "roster" }
"""
import sys
from pathlib import Path

import yaml

from wiki_creator import studio_io
from wiki_creator.entity_status import (
    build_name_index,
    load_cached_status,
    parse_status_verdict,
    roster_rows,
    save_status_cache,
)
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.registry import Registry

VERDICT_STAGE = "entity-status-verdict"


def contexts_by_entity(registry: Registry) -> dict[str, list[dict]]:
    """Per-PERSON context sentences with the chapter each came from.

    The chapter rides along because `select_status_snippets` sorts by it.
    """
    contexts: dict[str, list[dict]] = {}
    for record in registry.entities:
        if record.entity_type != "PERSON":
            continue
        snippets = [
            {"text": mention.context.strip(), "chapter_id": mention.chapter_id}
            for mention in record.mentions
            if mention.context and mention.context.strip()
        ]
        if snippets:
            contexts[record.canonical_name] = snippets
    return contexts


def verdict_from_payload(payload: dict, stage_name: str) -> object | None:
    verdict = payload.get("all_stage_outputs", {}).get(stage_name)
    if verdict is None:
        verdict = payload.get("previous_outputs", {}).get(stage_name)
    return verdict


def resolve_status(
    rows: list[dict],
    verdict_output: object | None,
    cache_path: Path,
    name_index: dict[str, dict[str, str]],
) -> dict[str, dict]:
    """Verified status per character, from cache or the call stage's verdict.

    Never raises. Every failure path returns {} — every character then renders
    the slot's declared fallback, `unknown`.
    """
    cached = load_cached_status(cache_path, rows)
    if cached is not None:
        return cached
    if verdict_output is None:
        return _give_up("no verdict (call skipped or failed)", rows)

    verdicts = parse_status_verdict(verdict_output, rows, name_index)
    save_status_cache(cache_path, rows, verdicts)
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-status] WARNING: {error} — all {len(rows)} characters stay `unknown`",
        file=sys.stderr,
    )
    return {}


def main() -> None:
    payload = studio_io.read_payload()
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    paths = studio_io.paths_from_payload(payload)
    cache_path = paths.processing / "entity_status.json"

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-status] registry.json not found in {paths.processing} — "
            "every character stays `unknown`",
            file=sys.stderr,
        )
        studio_io.write_output({"decided": 0, "roster": 0})
        return

    lang_cfg = load_lang_config(book_language(ctx))
    status_markers = list(lang_cfg.get("status_markers", []))

    contexts = contexts_by_entity(registry)
    persons = [
        {"canonical_name": record.canonical_name, "aliases": record.aliases}
        for record in registry.entities
        if record.entity_type == "PERSON" and record.canonical_name in contexts
    ]
    if not persons:
        print("[entity-status] no PERSON entity with context — nothing to decide", file=sys.stderr)
        studio_io.write_output({"decided": 0, "roster": 0})
        return

    rows = roster_rows(persons, contexts, status_markers)
    name_index = build_name_index(
        [
            {
                "entity_type": record.entity_type,
                "canonical_name": record.canonical_name,
                "aliases": record.aliases,
            }
            for record in registry.entities
        ]
    )
    verdicts = resolve_status(
        rows,
        verdict_output=verdict_from_payload(payload, VERDICT_STAGE),
        cache_path=cache_path,
        name_index=name_index,
    )

    decided = {name: v["status"] for name, v in verdicts.items()}
    print(
        f"[entity-status] {len(decided)}/{len(rows)} characters decided "
        f"({sum(1 for s in decided.values() if s == 'deceased')} deceased); "
        f"the rest render `unknown`",
        file=sys.stderr,
    )
    for name, verdict in sorted(verdicts.items()):
        print(f"[entity-status]   {name}: {verdict['status']}", file=sys.stderr)
    studio_io.write_output({"decided": len(decided), "roster": len(rows)})


if __name__ == "__main__":
    main()
