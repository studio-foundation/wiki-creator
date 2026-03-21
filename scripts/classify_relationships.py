#!/usr/bin/env python3
"""Standalone relationship classifier: calls studio run relationship-classifier-item per pair.

Usage:
    python scripts/classify_relationships.py --book library/.../book.yaml
    python scripts/classify_relationships.py --book library/.../book.yaml --dry-run

Input:  processing_output/<slug>/relationships.json
Output: processing_output/<slug>/relationships_classified.json

Saves incrementally after each pair. Resumes if output file already exists.
Studio handles LLM calls, ralph retries, and validation.
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.paths import book_paths_from_yaml
from scripts.relationship_extraction import (
    _run_studio_classifier_item,
    _should_classify_pair,
)


def _load_done_keys(output_path: Path) -> tuple[set[tuple[str, str]], list[dict]]:
    """Load already-classified pairs from output file. Returns (done_keys, pairs).

    Malformed pairs (missing entity_a/entity_b) are skipped individually — they do NOT
    cause a full reset of resume state.
    """
    if not output_path.exists():
        return set(), []
    try:
        data = json.loads(output_path.read_text(encoding="utf-8"))
        pairs = data.get("relationships", [])
        keys = {
            (p["entity_a"], p["entity_b"])
            for p in pairs
            if "entity_a" in p and "entity_b" in p
        }
        return keys, pairs
    except json.JSONDecodeError:
        return set(), []


def _save(output_path: Path, base: dict, classified: list[dict]) -> None:
    out = {**base, "relationships": classified}
    output_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
