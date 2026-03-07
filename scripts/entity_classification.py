#!/usr/bin/env python3
"""
Stage: Entity Classification (STU-231)
Computes total_mentions + chapters_present per entity, then assigns importance tiers.

Pipeline position:
  ... → relationship-extraction → **entity-classification** → wiki-generation

Input (via Studio context):
  previous_outputs.relationship-extraction:
    { "entities": [{canonical_name, type, aliases, source_ids, relevant}],
      "relationships": [...], "stats": {...}, "narrator": ... }
  additional_context: YAML string (book.input.yaml) with "thresholds" key
  Files: persons_full.json, places_full.json, orgs_full.json (project root)

Output (stdout):
  {
    "entities": [{ ...same fields..., "total_mentions": int, "chapters_present": int, "importance": str }],
    "relationships": [...passthrough...],
    "stats": { "principal": int, "secondary": int, "figurant": int, "ignored": int, "thresholds_used": str },
    "narrator": ...passthrough...
  }

importance values: "principal" | "secondary" | "figurant" | "ignored"

Standalone test:
  python scripts/entity_classification.py --test
"""

import json
import os
import sys
from collections import defaultdict


# --- Pure functions (testable) ---

def get_total_mentions(
    entity: dict,
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
) -> tuple[int, int]:
    """Return (total_mentions, chapters_present) for a resolved entity.

    Aggregates mentions across all source_ids from the matching type registry.
    """
    type_to_registry = {
        "PERSON": persons_full,
        "PLACE": places_full,
        "ORG": orgs_full,
    }
    registry = type_to_registry.get(entity.get("type", ""), {})
    if not registry:
        return 0, 0

    total = 0
    chapters: set[str] = set()
    for sid in entity.get("source_ids", []):
        entry = registry.get(sid, {})
        for ch, mentions in entry.get("mentions_by_chapter", {}).items():
            total += len(mentions)
            if mentions:
                chapters.add(ch)
    return total, len(chapters)


def compute_auto_thresholds(
    mention_counts: list[tuple[str, str, int]],
) -> dict[str, dict[str, int]]:
    """Compute percentile-based importance thresholds per entity type.

    Args:
        mention_counts: list of (canonical_name, type, total_mentions)

    Returns:
        { "PERSON": { "principal": N, "secondary": M, "figurant": K }, ... }
        An entity is "principal" if mentions >= principal threshold, etc.
    """
    by_type: dict[str, list[int]] = defaultdict(list)
    for _, etype, count in mention_counts:
        by_type[etype].append(count)

    thresholds: dict[str, dict[str, int]] = {}
    for etype, counts in by_type.items():
        sorted_counts = sorted(counts)
        n = len(sorted_counts)

        def percentile(p: float, _sorted=sorted_counts, _n=n) -> int:
            if _n == 0:
                return 0
            idx = max(0, int(_n * p) - 1)
            return _sorted[min(idx, _n - 1)]

        thresholds[etype] = {
            "principal": percentile(0.90),   # top 10%
            "secondary": percentile(0.60),   # 10-40%
            "figurant": percentile(0.10),    # 40-90%
            # below p10 → ignored
        }
    return thresholds


def assign_importance(
    entity_type: str,
    total_mentions: int,
    chapters_present: int,  # available for future min_chapters threshold support
    thresholds: dict[str, dict[str, int]],
) -> str:
    """Assign importance tier based on thresholds dict.

    thresholds shape: { "PERSON": { "principal": N, "secondary": M, "figurant": K } }
    Falls back to "figurant" for unknown types (conservative: generate a short page).
    """
    t = thresholds.get(entity_type)
    if not t:
        return "figurant"

    if total_mentions >= t["principal"]:
        return "principal"
    elif total_mentions >= t["secondary"]:
        return "secondary"
    elif total_mentions >= t["figurant"]:
        return "figurant"
    else:
        return "ignored"


def classify_entities(
    entities: list[dict],
    persons_full: dict,
    places_full: dict,
    orgs_full: dict,
    thresholds_config: str | dict,
) -> list[dict]:
    """Enrich entities with total_mentions, chapters_present, and importance.

    Args:
        entities: resolved entities from entity-resolution / relationship-extraction
        persons_full / places_full / orgs_full: raw entity registries
        thresholds_config: "auto" or explicit dict from book.input.yaml

    Returns:
        Same list with 3 new fields per entity.
    """
    # Step 1: compute mention counts for all entities
    mention_data: list[tuple[str, str, int, int]] = []
    for entity in entities:
        if not entity.get("relevant", True):
            mention_data.append((entity["canonical_name"], entity.get("type", "OTHER"), 0, 0))
            continue
        total, chapters = get_total_mentions(entity, persons_full, places_full, orgs_full)
        mention_data.append((entity["canonical_name"], entity.get("type", "OTHER"), total, chapters))

    # Step 2: compute thresholds
    if thresholds_config == "auto":
        threshold_input = [(name, etype, total) for name, etype, total, _ in mention_data]
        thresholds = compute_auto_thresholds(threshold_input)
    else:
        thresholds = _parse_explicit_thresholds(thresholds_config)

    # Step 3: assign importance
    result = []
    for entity, (name, etype, total, chapters) in zip(entities, mention_data):
        if entity.get("relevant", True):
            importance = assign_importance(etype, total, chapters, thresholds)
        else:
            importance = "ignored"
        enriched = {**entity, "total_mentions": total, "chapters_present": chapters, "importance": importance}
        result.append(enriched)
    return result


def _parse_explicit_thresholds(config: dict) -> dict[str, dict[str, int]]:
    """Convert book.input.yaml explicit thresholds to internal format."""
    thresholds: dict[str, dict[str, int]] = {}

    char_cfg = config.get("characters", {})
    if char_cfg:
        thresholds["PERSON"] = {
            "principal": char_cfg.get("principal", {}).get("min_mentions", 50),
            "secondary": char_cfg.get("secondary", {}).get("min_mentions", 10),
            "figurant": char_cfg.get("figurant", {}).get("min_mentions", 3),
        }

    loc_cfg = config.get("locations", {})
    if loc_cfg:
        thresholds["PLACE"] = {
            "principal": loc_cfg.get("major", {}).get("min_mentions", 20),
            "secondary": loc_cfg.get("minor", {}).get("min_mentions", 3),
            "figurant": 1,
        }

    org_cfg = config.get("organizations", {})
    if org_cfg:
        thresholds["ORG"] = {
            "principal": org_cfg.get("major", {}).get("min_mentions", 10),
            "secondary": org_cfg.get("minor", {}).get("min_mentions", 3),
            "figurant": 1,
        }

    return thresholds


# --- Studio entrypoint ---

def _load_entity_files() -> tuple[dict, dict, dict]:
    """Read *_full.json files from project root. Return empty dicts if missing."""
    def load(path: str, key: str) -> dict:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f).get(key, {})
        return {}

    return (
        load("persons_full.json", "persons_full"),
        load("places_full.json", "places_full"),
        load("orgs_full.json", "orgs_full"),
    )


def run_studio_mode() -> None:
    import yaml

    payload = json.load(sys.stdin)
    prev_outputs = payload.get("previous_outputs", {})
    rel_output = prev_outputs.get("relationship-extraction", {})
    entities = rel_output.get("entities", [])
    # Strip sample_contexts and chapters from relationships — not needed by wiki-generation
    # (reduces context size from ~800k to manageable for the writer LLM)
    relationships = [
        {k: v for k, v in r.items() if k not in ("sample_contexts", "chapters")}
        for r in rel_output.get("relationships", [])
    ]
    narrator = rel_output.get("narrator", None)

    if not entities:
        json.dump({"error": "missing relationship-extraction output"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    additional_ctx = payload.get("additional_context", "")
    book_input = yaml.safe_load(additional_ctx) if additional_ctx else {}
    thresholds_config = book_input.get("thresholds", "auto")

    persons_full, places_full, orgs_full = _load_entity_files()

    enriched = classify_entities(entities, persons_full, places_full, orgs_full, thresholds_config)

    from collections import Counter
    importance_counts = Counter(e["importance"] for e in enriched)

    output = {
        "entities": enriched,
        "relationships": relationships,
        "stats": {
            "principal": importance_counts.get("principal", 0),
            "secondary": importance_counts.get("secondary", 0),
            "figurant": importance_counts.get("figurant", 0),
            "ignored": importance_counts.get("ignored", 0),
            "thresholds_used": "auto" if thresholds_config == "auto" else "explicit",
        },
        "narrator": narrator,
    }

    os.makedirs("processing_output", exist_ok=True)
    with open("processing_output/entities_classified.json", "w", encoding="utf-8") as _f:
        json.dump(output, _f, ensure_ascii=False)

    json.dump(output, sys.stdout, ensure_ascii=False)


def run_test_mode() -> None:
    """Hardcoded Le Jeu de l'Ange data for local testing."""
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "source_ids": ["entity_001"],
         "aliases": ["Martín", "David"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "source_ids": ["entity_002"],
         "aliases": ["Vidal"], "relevant": True},
        {"canonical_name": "le libraire", "type": "PERSON", "source_ids": ["entity_003"],
         "aliases": [], "relevant": True},
    ]
    persons_full = {
        "entity_001": {"type": "PERSON", "raw_mentions": ["David Martín"],
                       "first_seen": "ch01",
                       "mentions_by_chapter": {"ch01": ["m1", "m2", "m3"], "ch02": ["m4", "m5"],
                                               "ch03": ["m6", "m7"], "ch04": ["m8"]}},
        "entity_002": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"],
                       "first_seen": "ch02",
                       "mentions_by_chapter": {"ch02": ["v1", "v2"], "ch03": ["v3"]}},
        "entity_003": {"type": "PERSON", "raw_mentions": ["le libraire"],
                       "first_seen": "ch05",
                       "mentions_by_chapter": {"ch05": ["l1"]}},
    }
    enriched = classify_entities(entities, persons_full, {}, {}, thresholds_config="auto")
    for e in enriched:
        print(f"{e['canonical_name']:30s}  mentions={e['total_mentions']:3d}  chapters={e['chapters_present']}  importance={e['importance']}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_test_mode()
    else:
        run_studio_mode()
