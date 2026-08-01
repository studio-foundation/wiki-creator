#!/usr/bin/env python3
"""relation-reconciliation — a completeness pass over discover-relationships (STU-754).

Script executor interface: reads JSON from stdin, writes JSON to stdout.

The schema-guided discovery sweep (`discover-relationships`) reads every
passage once, but its aggregate is not guaranteed complete for every roster
entry: a PERSON can end the stage with zero typed relations even though the
NER roster proves it matters, and a pair with strong co-occurrence signal in
`relationships.json` can still be absent from the typed graph. This stage
diffs the roster against the typed graph to find those gaps, fires one
agentic point-query per gap — same tooling as the STU-753 entity trio (search
the book, `tool_calls.minimum: 1`) — and folds any recovered relation through
the exact `valid_relations`/`aggregate` validation `discover-relationships`
itself uses. It never overwrites a pair discovery already typed: a recall
safety net, not a second discovery stage.

It sits in wiki-preparation right after `discover-relationships`, before
`classify-relationships-pre`, so a recovered pair reaches the classifier (and
therefore `build-character-graph`) exactly like a discovered one.

Never fails a run: a book with nothing to reconcile against (no discovered
graph yet, no roster, no chapters) writes nothing and the run proceeds
(STU-539 fail-safe).

Input:  { "additional_context": "<book yaml>",
          "all_stage_outputs": {"relation-reconciliation-verdict": {<map output>}} }
Output: { "gaps_found", "gaps_recovered" }
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from wiki_creator import studio_io
from wiki_creator.book_search import load_chapters
from wiki_creator.entity_status import entity_rows
from wiki_creator.page_templates import (
    relationship_definitions,
    relationship_tokens,
    sub_role_definitions,
    sub_role_tokens,
)
from wiki_creator.registry import Registry
from wiki_creator.relationship_discovery import (
    aggregate,
    build_roster,
    fold_chunk_result,
)
from wiki_creator.relationship_eval import pair_key
from wiki_creator.types import Relationship, RelationshipBundle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_AGENT_YAML = PROJECT_ROOT / ".studio" / "agents" / "relation-reconciliation.agent.yaml"

# STU-715's lesson: a single incidental co-occurrence must not become a hard
# relation. A pair below this many co-occurring chunks is not a "strong
# signal" the discovery sweep should be second-guessed over — it is left as a
# gap the reconciliation pass never queries, same as an ordinary weak pair.
_MIN_COOCCURRENCE_FOR_GAP = 2

VERDICT_STAGE = "relation-reconciliation-verdict"


def _map_output_from_payload(payload: dict) -> dict | None:
    verdict = payload.get("all_stage_outputs", {}).get(VERDICT_STAGE)
    if verdict is None:
        verdict = payload.get("previous_outputs", {}).get(VERDICT_STAGE)
    return verdict if isinstance(verdict, dict) else None


def prepare_reconciliation(book_cfg: dict, book_paths) -> tuple[dict | None, str | None]:
    """Build the reconciliation inputs shared by the pre and post steps.

    Returns `(prep, None)` with the roster/vocab discovery used, the typed
    graph to diff against, and the resulting gap rows — or `(None, reason)`
    when there is nothing to reconcile.
    """
    registry_path = book_paths.processing / "registry.json"
    discovered_path = book_paths.processing / "relationships_discovered.json"
    cooccurrence_path = book_paths.processing / "relationships.json"

    if not registry_path.exists():
        print(
            f"[relation-reconciliation] registry.json not found in {book_paths.processing} — "
            "nothing to reconcile",
            file=sys.stderr,
        )
        return None, "missing_registry"

    if not discovered_path.exists():
        print(
            "[relation-reconciliation] relationships_discovered.json not found — "
            "discover-relationships wrote nothing this run, nothing to reconcile against",
            file=sys.stderr,
        )
        return None, "missing_discovered_graph"

    registry = Registry.load(registry_path)
    entities = [
        {
            "canonical_name": r.canonical_name,
            "entity_type": r.entity_type,
            "aliases": r.aliases,
            "offstage": r.offstage,
        }
        for r in registry.entities
    ]
    roster_names, alias_to_canonical, roster_lines = build_roster(entities)
    if not roster_names:
        print("[relation-reconciliation] empty PERSON roster — nothing to reconcile", file=sys.stderr)
        return None, "empty_roster"

    chapters = load_chapters(book_paths.processing)
    if not chapters:
        print(
            f"[relation-reconciliation] chapters.json not found in {book_paths.processing} — "
            "nothing for the agent to search",
            file=sys.stderr,
        )
        return None, "no_chapters"

    type_defs = relationship_definitions(book_config=book_cfg)
    allowed_types = set(relationship_tokens(book_config=book_cfg))
    sub_role_defs = sub_role_definitions()
    allowed_sub_roles = set(sub_role_tokens())

    discovered = studio_io.load_artifact(discovered_path, RelationshipBundle)
    typed_pairs = {pair_key(r.entity_a, r.entity_b) for r in discovered.relationships}

    orphans = roster_names - {name for pair in typed_pairs for name in pair}

    cooccurrence_gap_entities: set[str] = set()
    if cooccurrence_path.exists():
        cooccurrence = studio_io.load_artifact(cooccurrence_path, RelationshipBundle)
        for rel in cooccurrence.relationships:
            a, b = rel.entity_a, rel.entity_b
            if a not in roster_names or b not in roster_names or a == b:
                continue
            if rel.cooccurrence_count < _MIN_COOCCURRENCE_FOR_GAP:
                continue
            key = pair_key(a, b)
            if key in typed_pairs:
                continue
            # One endpoint is enough — its point-query re-surveys this pair
            # along with everything else it relates to (STU-754: "a handful of
            # queries per book", not one query per gap pair).
            cooccurrence_gap_entities.add(key[0])

    gap_names = orphans | cooccurrence_gap_entities
    persons = [e for e in entities if e["canonical_name"] in gap_names]
    rows = entity_rows(persons)

    fingerprint = studio_io.prompt_fingerprint(
        [_AGENT_YAML, book_paths.processing / "chapters.json"],
        {"relationship_types": type_defs, "sub_roles": sub_role_defs, "roster": roster_lines},
    )

    return {
        "rows": rows,
        "book_dir": str(book_paths.processing),
        "roster_lines": roster_lines,
        "roster_names": roster_names,
        "alias_to_canonical": alias_to_canonical,
        "type_defs": type_defs,
        "allowed_types": allowed_types,
        "sub_role_defs": sub_role_defs,
        "allowed_sub_roles": allowed_sub_roles,
        "fingerprint": fingerprint,
        "discovered": discovered,
        "discovered_path": discovered_path,
        "typed_pairs": typed_pairs,
        "orphans": len(orphans),
        "cooccurrence_gaps": len(cooccurrence_gap_entities),
    }, None


def _recovered_pairs(prep: dict, map_output: dict) -> list[dict]:
    """Kept, off-roster/off-vocabulary-filtered relations from the map's per-item
    results, folded to pairs via the same `aggregate` discover-relationships uses.

    A pair discovery already typed is dropped even if a query re-proves it —
    the safety net fills gaps, it never overwrites a discovered verdict.
    """
    rows = prep["rows"]
    results_by_index: dict[int, dict] = {}
    for result in map_output.get("results") or []:
        if isinstance(result, dict) and isinstance(result.get("index"), int):
            results_by_index[result["index"]] = result

    votes: list[dict] = []
    for i, row in enumerate(rows):
        result = results_by_index.get(i)
        raw = None
        if result and result.get("status") == "success" and isinstance(result.get("output"), dict):
            raw = result["output"].get("relations")
        kept = fold_chunk_result(
            raw, prep["alias_to_canonical"], prep["roster_names"],
            prep["allowed_types"], prep["allowed_sub_roles"],
        )
        if kept:
            votes.append({"chapter_id": f"reconciliation:{row['name']}", "relations": kept})

    aggregated = aggregate(votes, prep["roster_names"])
    return [p for p in aggregated if pair_key(p["entity_a"], p["entity_b"]) not in prep["typed_pairs"]]


def collect_and_save(prep: dict, map_output: dict | None) -> dict:
    gaps_found = len(prep["rows"])
    if not prep["rows"]:
        print("[relation-reconciliation] no roster gaps — graph is already complete", file=sys.stderr)
        return {"gaps_found": 0, "gaps_recovered": 0}

    if map_output is None:
        print(
            f"[relation-reconciliation] WARNING: no verdict (call skipped or failed) — "
            f"{gaps_found} gap(s) stay unresolved this run",
            file=sys.stderr,
        )
        return {"gaps_found": gaps_found, "gaps_recovered": 0}

    new_pairs = _recovered_pairs(prep, map_output)
    if new_pairs:
        discovered = prep["discovered"]
        combined = list(discovered.relationships) + [Relationship(**p) for p in new_pairs]
        combined.sort(key=lambda r: (-len(r.chapters), r.entity_a, r.entity_b))
        stats = dict(discovered.stats)
        stats["reconciliation"] = {
            "gaps_found": gaps_found,
            "gaps_recovered": len(new_pairs),
        }
        bundle = RelationshipBundle(
            entities=discovered.entities,
            relationships=combined,
            stats=stats,
            narrator=discovered.narrator,
        )
        studio_io.save_artifact(prep["discovered_path"], bundle, RelationshipBundle)

    print(
        f"[relation-reconciliation] {gaps_found} gap(s) "
        f"({prep['orphans']} orphan, {prep['cooccurrence_gaps']} cooccurrence) → "
        f"{len(new_pairs)} pair(s) recovered",
        file=sys.stderr,
    )
    return {"gaps_found": gaps_found, "gaps_recovered": len(new_pairs)}


def main() -> None:
    payload = studio_io.read_payload()
    book_cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    prep, skip = prepare_reconciliation(book_cfg, studio_io.paths_from_payload(payload))
    if skip:
        studio_io.write_output({"gaps_found": 0, "gaps_recovered": 0})
        return
    summary = collect_and_save(prep, _map_output_from_payload(payload))
    studio_io.write_output(summary)


if __name__ == "__main__":
    main()
