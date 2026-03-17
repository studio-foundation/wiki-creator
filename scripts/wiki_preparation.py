#!/usr/bin/env python3
"""
Stage: wiki-preparation (script executor, no LLM)

Reads entity-classification output + *_full.json files on disk.
Pre-extracts per-entity context sentences and builds batch input files
for child wiki-page pipeline runs.

Input (Studio stdin):
  previous_outputs["entity-classification"]:
    { "entities": [...with importance field], "relationships": [...], "narrator": ..., "stats": ... }
  Files on disk: persons_full.json, places_full.json, orgs_full.json, events_full.json

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
import re
import sys
from pathlib import Path

import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wiki_creator.paths import book_paths_from_epub, BookPaths


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)

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
MAX_RELATED_ENTITIES = 5
MAX_RELATED_SNIPPETS = 2
DEFAULT_CHAPTER_SUMMARY_MAX = 8


def load_registry(path: str, key: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(key, {})
    return {}


def _registry_chain_for_entity(entity: dict, persons: dict, places: dict, orgs: dict, events: dict) -> list[dict]:
    """Return registries in lookup order: preferred by current type, then fallbacks."""
    by_type = {
        "PERSON": persons,
        "PLACE": places,
        "ORG": orgs,
        "EVENT": events,
    }
    primary = by_type.get(entity.get("type", ""), {})
    ordered = [primary] if primary else []
    for reg in (persons, places, orgs, events):
        if reg and reg is not primary:
            ordered.append(reg)
    return ordered


def _find_entry_for_source_id(entity: dict, source_id: str, persons: dict, places: dict, orgs: dict, events: dict) -> dict:
    """Find source_id entry, preferring the entity's current type registry."""
    for registry in _registry_chain_for_entity(entity, persons, places, orgs, events):
        entry = registry.get(source_id, {})
        if entry:
            return entry
    return {}


def extract_context(entity: dict, persons: dict, places: dict, orgs: dict, events: dict) -> dict:
    """Extract context_by_chapter, with cross-registry fallback for retagged entities."""
    combined: dict[str, list[str]] = {}
    for sid in entity.get("source_ids", []):
        entry = _find_entry_for_source_id(entity, sid, persons, places, orgs, events)
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


def get_first_seen(entity: dict, persons: dict, places: dict, orgs: dict, events: dict) -> str:
    """Return the first chapter where this entity appears, with registry fallback."""
    first_seen = ""
    for sid in entity.get("source_ids", []):
        entry = _find_entry_for_source_id(entity, sid, persons, places, orgs, events)
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


def _entity_context_char_count(entity_bundle: dict) -> int:
    """Estimate context size for batching from direct + related context."""
    direct_ctx = sum(
        sum(len(m) for m in mentions)
        for mentions in entity_bundle.get("context_by_chapter", {}).values()
    )
    related_ctx = 0
    for rel in entity_bundle.get("related_context", []):
        related_ctx += len(rel.get("related_name", ""))
        related_ctx += len(str(rel.get("cooccurrence_count", "")))
        related_ctx += len(rel.get("related_type", "") or "")
        related_ctx += len(rel.get("related_importance", "") or "")
        related_ctx += sum(len(s) for s in rel.get("support_snippets", []))
    chapter_summary_ctx = 0
    for chapter in entity_bundle.get("chapter_summary_context", []):
        chapter_summary_ctx += len(chapter.get("chapter_key", ""))
        chapter_summary_ctx += sum(len(s) for s in chapter.get("summary_bullets", []))
    return direct_ctx + related_ctx + chapter_summary_ctx


def load_book_config_from_payload(payload: dict) -> dict:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        return {}
    epub_path = Path(file_path)
    yaml_path = epub_path.with_suffix(".yaml")
    if not yaml_path.exists():
        return {}
    try:
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def chapter_summary_limit_from_config(book_cfg: dict) -> int:
    generation_cfg = book_cfg.get("generation", {})
    value = generation_cfg.get("chapter_summary_max_chapters_per_entity", DEFAULT_CHAPTER_SUMMARY_MAX)
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_CHAPTER_SUMMARY_MAX
    if limit < 1:
        return 1
    return limit


def stage_outputs_from_payload(payload: dict) -> tuple[dict, dict]:
    prev_outputs = payload.get("previous_outputs", {})
    all_outputs = payload.get("all_stage_outputs", {})
    prev_stage_output = payload.get("previous_stage_output", {})
    classification_output = {}
    chapter_summary_output = {}

    if isinstance(all_outputs, dict):
        classification_output = all_outputs.get("entity-classification", {}) or {}
        chapter_summary_output = all_outputs.get("chapter-summary", {}) or {}
    if not classification_output and isinstance(prev_outputs, dict):
        classification_output = prev_outputs.get("entity-classification", {}) or {}
    if not chapter_summary_output and isinstance(prev_outputs, dict):
        chapter_summary_output = prev_outputs.get("chapter-summary", {}) or {}
    if not classification_output and isinstance(prev_stage_output, dict) and prev_stage_output.get("entities"):
        classification_output = prev_stage_output
    if not chapter_summary_output and isinstance(prev_stage_output, dict) and prev_stage_output.get("chapter_summaries") is not None:
        chapter_summary_output = prev_stage_output

    return classification_output, chapter_summary_output


def _support_snippets_for_entity(
    entity: dict,
    persons: dict,
    places: dict,
    orgs: dict,
    events: dict,
) -> list[str]:
    ctx = extract_context(entity, persons, places, orgs, events)
    snippets: list[str] = []
    for chapter in sorted(ctx.keys()):
        for mention in ctx[chapter]:
            snippets.append(mention)
            if len(snippets) >= MAX_RELATED_SNIPPETS:
                return snippets
    return snippets


def build_related_context(
    canonical_name: str,
    relationships: list[dict],
    entities_by_name: dict[str, dict],
    persons: dict,
    places: dict,
    orgs: dict,
    events: dict,
) -> list[dict]:
    related_rows = []
    for rel in filter_relationships(canonical_name, relationships):
        a = rel.get("entity_a")
        b = rel.get("entity_b")
        related_name = b if a == canonical_name else a
        if not related_name or not isinstance(related_name, str):
            continue
        related_name = related_name.strip()
        if not related_name:
            continue

        related_entity = entities_by_name.get(related_name, {})
        support_snippets = []
        if related_entity:
            support_snippets = _support_snippets_for_entity(related_entity, persons, places, orgs, events)

        related_rows.append({
            "related_name": related_name,
            "cooccurrence_count": int(rel.get("cooccurrence_count", 0) or 0),
            "related_type": related_entity.get("type") if related_entity else None,
            "related_importance": related_entity.get("importance") if related_entity else None,
            "support_snippets": support_snippets,
        })

    related_rows.sort(key=lambda r: r.get("cooccurrence_count", 0), reverse=True)
    return related_rows[:MAX_RELATED_ENTITIES]


def _epub_key_to_chapter_label(key: str) -> str | None:
    """Convert 'C25.xhtml' -> 'Chapter 25'. Returns None if key doesn't match pattern."""
    m = re.match(r'^[Cc](\d+)\.xhtml$', key)
    return f"Chapter {int(m.group(1))}" if m else None


def build_chapter_summary_context(
    entity: dict,
    chapter_summaries: dict[str, dict],
    chapter_summary_max: int,
    context_by_chapter: dict[str, list[str]],
) -> list[dict]:
    if entity.get("type") != "PERSON":
        return []
    summaries_by_id = {
        str(summary.get("chapter_id", "")).strip(): summary
        for summary in chapter_summaries.values()
        if isinstance(summary, dict) and str(summary.get("chapter_id", "")).strip()
    }
    chapter_keys = sorted(context_by_chapter.keys())[:chapter_summary_max]
    result = []
    for chapter_key in chapter_keys:
        label = _epub_key_to_chapter_label(chapter_key)
        summary = (
            chapter_summaries.get(chapter_key)
            or summaries_by_id.get(chapter_key)
            or (chapter_summaries.get(label) if label else None)
        )
        if not summary:
            continue
        bullets = [
            b for b in summary.get("summary_bullets", [])
            if isinstance(b, str) and b.strip()
        ][:3]
        if not bullets:
            continue
        result.append({
            "chapter_key": chapter_key,
            "summary_bullets": bullets,
            "temporal_context": summary.get("temporal_context", "unknown"),
        })
    return result


def build_entity_bundle(
    entity: dict,
    relationships: list[dict],
    persons: dict,
    places: dict,
    orgs: dict,
    events: dict,
    entities_by_name: dict[str, dict],
    chapter_summaries: dict[str, dict] | None = None,
    chapter_summary_max: int = DEFAULT_CHAPTER_SUMMARY_MAX,
) -> dict:
    canonical_name = entity["canonical_name"]
    context_by_chapter = extract_context(entity, persons, places, orgs, events)
    return {
        "canonical_name": canonical_name,
        "type": entity.get("type", "OTHER"),
        "importance": entity.get("importance", "figurant"),
        "aliases": entity.get("aliases", []),
        "total_mentions": entity.get("total_mentions", 0),
        "chapters_present": entity.get("chapters_present", 0),
        "first_seen": get_first_seen(entity, persons, places, orgs, events),
        "context_by_chapter": context_by_chapter,
        "relationships": filter_relationships(canonical_name, relationships),
        "related_context": build_related_context(
            canonical_name,
            relationships,
            entities_by_name,
            persons,
            places,
            orgs,
            events,
        ),
        "chapter_summary_context": build_chapter_summary_context(
            entity=entity,
            chapter_summaries=chapter_summaries or {},
            chapter_summary_max=chapter_summary_max,
            context_by_chapter=context_by_chapter,
        ),
    }


def _flush_batch(
    entities: list[dict],
    narrator: object,
    batch_index: int,
    importance: str,
    ctx_chars: int,
    batches: list[dict],
    wiki_inputs_dir: "Path",
) -> None:
    from pathlib import Path
    batch_id = f"batch_{batch_index:03d}"
    file_path = str(wiki_inputs_dir / f"{batch_id}.json")
    # Narrator only affects PERSON pages — pass null for non-PERSON batches
    batch_types = {e.get("type") for e in entities}
    batch_narrator = narrator if "PERSON" in batch_types else None
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump({"batch_id": batch_id, "narrator": batch_narrator, "entities": entities}, f, ensure_ascii=False, indent=2)
    batches.append({"batch_id": batch_id, "file": file_path, "entity_count": len(entities), "importance": importance})
    print(f"  Wrote {file_path} ({len(entities)} {importance} entities, {ctx_chars} chars)", file=sys.stderr)


def write_batches(entity_bundles: list[dict], narrator: object, paths: "BookPaths") -> list[dict]:
    """Split entity bundles into batch files.

    Splits by BOTH entity count (importance-dependent) AND total context chars per batch
    to stay within haiku-4-5's 8192 output token limit.
    """
    wiki_inputs_dir = paths.wiki_inputs
    wiki_inputs_dir.mkdir(parents=True, exist_ok=True)

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
            entity_ctx = _entity_context_char_count(entity)
            if current_batch and (
                len(current_batch) >= batch_size
                or current_ctx + entity_ctx > MAX_BATCH_CONTEXT_CHARS
            ):
                _flush_batch(current_batch, narrator, batch_index, importance, current_ctx, batches, wiki_inputs_dir)
                batch_index += 1
                current_batch = []
                current_ctx = 0
            current_batch.append(entity)
            current_ctx += entity_ctx

        if current_batch:
            _flush_batch(current_batch, narrator, batch_index, importance, current_ctx, batches, wiki_inputs_dir)
            batch_index += 1

    return batches


def main() -> None:
    payload = json.load(sys.stdin)
    classification_output, chapter_summary_output = stage_outputs_from_payload(payload)

    entities = classification_output.get("entities", [])
    relationships = classification_output.get("relationships", [])
    narrator = classification_output.get("narrator", None)

    if not entities:
        print("Warning: no entities in entity-classification output", file=sys.stderr)
        json.dump({"batches": [], "total_entities": 0, "narrator": None}, sys.stdout)
        return

    paths = _paths_from_payload(payload)
    book_cfg = load_book_config_from_payload(payload)
    chapter_summary_max = chapter_summary_limit_from_config(book_cfg)
    persons = load_registry(str(paths.processing / "persons_full.json"), "persons_full")
    places = load_registry(str(paths.processing / "places_full.json"), "places_full")
    orgs = load_registry(str(paths.processing / "orgs_full.json"), "orgs_full")
    events = load_registry(str(paths.processing / "events_full.json"), "events_full")

    # Only process entities that will have a wiki page
    relevant_entities = [
        e for e in entities
        if e.get("relevant", True) and e.get("importance", "figurant") != "ignored"
    ]
    print(
        f"wiki-preparation: {len(relevant_entities)}/{len(entities)} entities to process",
        file=sys.stderr,
    )

    entities_by_name = {
        e.get("canonical_name", ""): e
        for e in relevant_entities
        if e.get("canonical_name")
    }
    chapter_summaries = chapter_summary_output.get("chapter_summaries", {})
    entity_bundles = [
        build_entity_bundle(
            e,
            relationships,
            persons,
            places,
            orgs,
            events,
            entities_by_name,
            chapter_summaries=chapter_summaries,
            chapter_summary_max=chapter_summary_max,
        )
        for e in relevant_entities
    ]

    batches = write_batches(entity_bundles, narrator, paths)

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
