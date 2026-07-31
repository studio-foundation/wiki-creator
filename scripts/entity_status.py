#!/usr/bin/env python3
"""entity-status — is each character alive at the end of this book?

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Post-step of the entity-status split (STU-457/753). The `call:
entity-status-verdict` stage that precedes this one fans out one agentic
search-and-decide call per PERSON entity over the engine map (STU-589/605);
this stage folds the per-entity results, verifies each against the book's own
text, and writes `entity_status.json`, which `wiki_preparation.py` then stamps
onto the batch entity so `generate_wiki_pages.py` can render the `status`
infobox slot.

It sits in wiki-preparation and not wiki-resolution on purpose.
`alias-adjudication` sits inside resolution because it changes identity —
entity-classification reads its output. This changes no identity; it only
decorates the batch entity. And resolution is chained by `make golden`, which
stays LLM-free by construction.

Never fails a run: a book whose verdicts cannot be obtained renders `unknown`
for every character, loudly.

Input:  { "additional_context": "<book yaml>",
          "all_stage_outputs": {"entity-status-verdict": {<map output>}} }
Output: { "decided", "roster" }
"""
import json
import sys
from pathlib import Path

from wiki_creator import studio_io
from wiki_creator.book_search import full_text, load_chapters
from wiki_creator.entity_status import (
    ARTIFACT_VERSION,
    build_name_index,
    entity_rows,
    parse_status_verdict,
)
from wiki_creator.registry import Registry

VERDICT_STAGE = "entity-status-verdict"


def contexts_by_entity(registry: Registry) -> dict[str, list]:
    """PERSON entities that have at least one mention — the set with anything to
    decide. The mentions' text is not read here (STU-753: the agent searches the
    book directly); only presence matters, so callers just check membership."""
    contexts: dict[str, list] = {}
    for record in registry.entities:
        if record.entity_type != "PERSON":
            continue
        if any(mention.context and mention.context.strip() for mention in record.mentions):
            contexts[record.canonical_name] = []
    return contexts


def verdict_from_payload(payload: dict, stage_name: str) -> object | None:
    verdict = payload.get("all_stage_outputs", {}).get(stage_name)
    if verdict is None:
        verdict = payload.get("previous_outputs", {}).get(stage_name)
    return verdict


def resolve_verdicts(
    rows: list[dict], map_output: object | None, book_text: str, name_index: dict[str, dict[str, str]]
) -> dict[str, dict]:
    """Verified status per character, from the map fan-out's per-item results.

    Never raises. A missing map output, a missing per-item result, and a
    per-item verdict that fails grounding all fall through the same way: that
    one character stays out of the returned dict, which renders `unknown` — a
    per-unit failure fails that unit, never the run.
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
        verdict = parse_status_verdict(
            result.get("output"), row["name"], row["aliases"], book_text, name_index
        )
        if verdict is not None:
            verdicts[row["name"]] = verdict
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-status] WARNING: {error} — all {len(rows)} characters stay `unknown`",
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

    rows = entity_rows(persons)
    book_text = full_text(load_chapters(paths.processing))
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
    verdicts = resolve_verdicts(
        rows,
        verdict_from_payload(payload, VERDICT_STAGE),
        book_text,
        name_index,
    )
    _write_artifact(cache_path, verdicts)

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
