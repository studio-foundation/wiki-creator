#!/usr/bin/env python3
"""
Stage: wiki-preparation (script executor, no LLM)

Reads entity-classification output + *_full.json files on disk.
Pre-extracts per-entity context sentences and builds batch input files
for child wiki-page pipeline runs.

Input (Studio stdin):
  previous_outputs["entity-classification"]:
    { "entities": [...with importance field], "relationships": [...], "narrator": ..., "stats": ... }
  Files on disk: persons_full.json, places_full.json, orgs_full.json

Output (stdout):
  {
    "batches": [{"batch_id": "batch_000", "file": "wiki_inputs/batch_000.json", "entity_count": N}],
    "total_entities": N,
    "narrator": {...} | null
  }

Side effects:
  Creates wiki_inputs/ directory and writes wiki_inputs/batch_*.json files.
"""

import json
import os
import sys

BATCH_SIZE_BY_IMPORTANCE = {
    "principal": 3,   # full template ~1500 tokens × 3 = 4500 tokens — safe under 8192
    "secondary": 10,  # short template ~400 tokens × 10 = 4000 tokens — safe
    "figurant": 20,   # infobox only ~150 tokens × 20 = 3000 tokens — safe
}
# Hard cap on total context chars per batch — prevents long batches even within size limits
MAX_BATCH_CONTEXT_CHARS = 20000
MAX_MENTIONS_PER_CHAPTER = 5
MAX_CHAPTERS = 25
# Cap total context chars per entity
MAX_CONTEXT_CHARS_PER_ENTITY = 8000


def load_registry(path: str, key: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(key, {})
    return {}


def extract_context(entity: dict, persons: dict, places: dict, orgs: dict) -> dict:
    """Extract context_by_chapter for an entity from the appropriate registry."""
    type_to_registry = {
        "PERSON": persons,
        "PLACE": places,
        "ORG": orgs,
    }
    registry = type_to_registry.get(entity.get("type", ""), {})
    if not registry:
        return {}

    combined: dict[str, list[str]] = {}
    for sid in entity.get("source_ids", []):
        entry = registry.get(sid, {})
        for chapter, mentions in entry.get("mentions_by_chapter", {}).items():
            if chapter not in combined:
                combined[chapter] = []
            combined[chapter].extend(mentions)

    # Cap per chapter and total chapters to limit bundle size
    result = {}
    total_chars = 0
    for chapter in sorted(combined.keys())[:MAX_CHAPTERS]:
        mentions = combined[chapter][:MAX_MENTIONS_PER_CHAPTER]
        chapter_chars = sum(len(m) for m in mentions)
        if total_chars + chapter_chars > MAX_CONTEXT_CHARS_PER_ENTITY:
            break
        result[chapter] = mentions
        total_chars += chapter_chars

    return result


def get_first_seen(entity: dict, persons: dict, places: dict, orgs: dict) -> str:
    """Return the first chapter where this entity appears."""
    type_to_registry = {
        "PERSON": persons,
        "PLACE": places,
        "ORG": orgs,
    }
    registry = type_to_registry.get(entity.get("type", ""), {})
    first_seen = ""
    for sid in entity.get("source_ids", []):
        entry = registry.get(sid, {})
        fs = entry.get("first_seen", "")
        if fs and (not first_seen or fs < first_seen):
            first_seen = fs
    return first_seen


def filter_relationships(canonical_name: str, relationships: list[dict]) -> list[dict]:
    """Return relationships involving this entity."""
    return [
        r for r in relationships
        if r.get("entity_a") == canonical_name or r.get("entity_b") == canonical_name
    ]


def build_entity_bundle(
    entity: dict,
    relationships: list[dict],
    persons: dict,
    places: dict,
    orgs: dict,
) -> dict:
    canonical_name = entity["canonical_name"]
    return {
        "canonical_name": canonical_name,
        "type": entity.get("type", "OTHER"),
        "importance": entity.get("importance", "figurant"),
        "aliases": entity.get("aliases", []),
        "total_mentions": entity.get("total_mentions", 0),
        "chapters_present": entity.get("chapters_present", 0),
        "first_seen": get_first_seen(entity, persons, places, orgs),
        "context_by_chapter": extract_context(entity, persons, places, orgs),
        "relationships": filter_relationships(canonical_name, relationships),
    }


def _flush_batch(
    entities: list[dict],
    narrator: object,
    batch_index: int,
    importance: str,
    ctx_chars: int,
    batches: list[dict],
) -> None:
    batch_id = f"batch_{batch_index:03d}"
    file_path = f"wiki_inputs/{batch_id}.json"
    # Narrator only affects PERSON pages — pass null for non-PERSON batches
    batch_types = {e.get("type") for e in entities}
    batch_narrator = narrator if "PERSON" in batch_types else None
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump({"batch_id": batch_id, "narrator": batch_narrator, "entities": entities}, f, ensure_ascii=False, indent=2)
    batches.append({"batch_id": batch_id, "file": file_path, "entity_count": len(entities), "importance": importance})
    print(f"  Wrote {file_path} ({len(entities)} {importance} entities, {ctx_chars} chars)", file=sys.stderr)


def write_batches(entity_bundles: list[dict], narrator: object) -> list[dict]:
    """Split entity bundles into batch files.

    Splits by BOTH entity count (importance-dependent) AND total context chars per batch
    to stay within haiku-4-5's 8192 output token limit.
    """
    os.makedirs("wiki_inputs", exist_ok=True)

    batches: list[dict] = []
    batch_index = 0

    for importance in ("principal", "secondary", "figurant"):
        group = [e for e in entity_bundles if e["importance"] == importance]
        if not group:
            continue
        batch_size = BATCH_SIZE_BY_IMPORTANCE[importance]

        current_batch: list[dict] = []
        current_ctx = 0
        for entity in group:
            entity_ctx = sum(
                sum(len(m) for m in mentions)
                for mentions in entity["context_by_chapter"].values()
            )
            if current_batch and (
                len(current_batch) >= batch_size
                or current_ctx + entity_ctx > MAX_BATCH_CONTEXT_CHARS
            ):
                _flush_batch(current_batch, narrator, batch_index, importance, current_ctx, batches)
                batch_index += 1
                current_batch = []
                current_ctx = 0
            current_batch.append(entity)
            current_ctx += entity_ctx

        if current_batch:
            _flush_batch(current_batch, narrator, batch_index, importance, current_ctx, batches)
            batch_index += 1

    return batches


def main() -> None:
    payload = json.load(sys.stdin)
    prev_outputs = payload.get("previous_outputs", {})
    classification_output = prev_outputs.get("entity-classification", {})

    entities = classification_output.get("entities", [])
    relationships = classification_output.get("relationships", [])
    narrator = classification_output.get("narrator", None)

    if not entities:
        print("Warning: no entities in entity-classification output", file=sys.stderr)
        json.dump({"batches": [], "total_entities": 0, "narrator": None}, sys.stdout)
        return

    persons = load_registry("persons_full.json", "persons_full")
    places = load_registry("places_full.json", "places_full")
    orgs = load_registry("orgs_full.json", "orgs_full")

    # Only process entities that will have a wiki page
    relevant_entities = [
        e for e in entities
        if e.get("relevant", True) and e.get("importance", "figurant") != "ignored"
    ]
    print(
        f"wiki-preparation: {len(relevant_entities)}/{len(entities)} entities to process",
        file=sys.stderr,
    )

    entity_bundles = [
        build_entity_bundle(e, relationships, persons, places, orgs)
        for e in relevant_entities
    ]

    batches = write_batches(entity_bundles, narrator)

    json.dump(
        {
            "batches": batches,
            "total_entities": len(entity_bundles),
            "narrator": narrator,
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
