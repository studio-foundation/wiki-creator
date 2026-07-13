#!/usr/bin/env python3
"""build-event-layer (script executor, no LLM).

Structures chapter_summaries.json + relationships_classified.json into
events.json (SP0 of the Plot Spine feature, STU-478). Runs after
classify_relationships.py, before wiki_preparation.py.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


import yaml

from wiki_creator import studio_io
from wiki_creator.event_layer import build_events
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry
from wiki_creator.types import ChapterSummary, RelationshipBundle

# Entity-classification importance tiers (scripts/entity_classification.py)
# -> salience participant-importance weight (STU-483). Tiers absent here
# (e.g. "ignored", or an entity missing from entities_classified.json)
# default to 0.0 via dict.get.
_IMPORTANCE_TIER_WEIGHTS = {"principal": 1.0, "secondaire": 0.6, "figurant": 0.3}


def _read_participant_importance(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entities = data.get("entities", []) if isinstance(data, dict) else []
    weights: dict[str, float] = {}
    for entity in entities:
        name = entity.get("canonical_name")
        tier = str(entity.get("importance", "")).strip().lower()
        if name and tier in _IMPORTANCE_TIER_WEIGHTS:
            weights[name] = _IMPORTANCE_TIER_WEIGHTS[tier]
    return weights


def run_for_processing(processing_dir: Path | str, language: str) -> list[dict]:
    """Build events.json from artifacts in ``processing_dir``. Returns events."""
    processing_dir = Path(processing_dir)
    summaries_path = processing_dir / "chapter_summaries.json"
    rels_path = processing_dir / "relationships_classified.json"

    summaries = _read_summaries(summaries_path)
    relationships = _read_relationships(rels_path)

    registry = Registry.load_from_processing(processing_dir)
    participant_importance = _read_participant_importance(processing_dir / "entities_classified.json")

    action_cues = load_lang_config(language).get("action_cues", [])
    events = build_events(summaries, relationships, registry, action_cues, participant_importance)

    (processing_dir / "events.json").write_text(
        json.dumps({"events": events}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        f"[events] wrote {len(events)} events to {processing_dir / 'events.json'}",
        file=sys.stderr,
    )
    return events


def _read_summaries(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    data = raw.get("chapter_summaries", raw) if isinstance(raw, dict) else {}
    summaries = studio_io.from_dict(dict[str, ChapterSummary], data)
    # dict-only boundary: build_events() (wiki_creator/event_layer.py) consumes
    # plain chapter-summary dicts — validated on load above.
    return studio_io.to_dict(summaries)


def _read_relationships(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        bundle = studio_io.load_artifact(path, RelationshipBundle)
    except json.JSONDecodeError:
        return []
    # dict-only boundary: build_events() (wiki_creator/event_layer.py) consumes
    # plain relationship dicts — validated on load above.
    return studio_io.to_dict(bundle.relationships)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the event layer (events.json)")
    parser.add_argument("--book", required=True, help="Path to book YAML config")
    args = parser.parse_args()

    with open(args.book, encoding="utf-8") as f:
        ctx = yaml.safe_load(f) or {}

    book_paths = book_paths_from_yaml(args.book)
    run_for_processing(book_paths.processing, book_language(ctx))


if __name__ == "__main__":
    main()
