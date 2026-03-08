#!/usr/bin/env python3
"""
Standalone test: run entity extraction on the full book and print a summary.

Usage:
    python scripts/test_extraction.py --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml

Output JSONL format (one line per entity):
  {"id": "entity_001", "type": "PERSON", "raw_mentions": [...], "first_seen": "ch01",
   "mentions_by_chapter": {"ch01": ["sentence..."]}}
"""

import argparse
import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.parse_epub import parse_epub
from scripts.entity_extraction import extract_entities, split_entities, split_by_type
from wiki_creator.paths import book_paths_from_yaml

SPACY_MODEL = "fr_core_news_lg"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run entity extraction on a full book")
    parser.add_argument(
        "--book", required=True,
        help="Path to book yaml, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
    )
    parser.add_argument("--spacy-model", default=SPACY_MODEL, help="spaCy model to use")
    args = parser.parse_args()

    paths = book_paths_from_yaml(args.book)
    paths.processing.mkdir(parents=True, exist_ok=True)

    book_path = str(paths.epub)
    spacy_model = args.spacy_model

    print(f"Parsing {book_path}...", file=sys.stderr)
    book = parse_epub(book_path)
    print(f"  → {book['title']} — {len(book['chapters'])} chapters", file=sys.stderr)

    import spacy
    print(f"Loading {spacy_model}...", file=sys.stderr)
    nlp = spacy.load(spacy_model)

    print("Extracting entities (this may take a few minutes)...", file=sys.stderr)
    result = extract_entities(book["chapters"], nlp)
    entities = result["entities"]
    entities_for_resolution, entities_full = split_entities(entities)

    type_counts: dict[str, int] = {}
    for entity in entities.values():
        t = entity["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"\n=== Extraction Results: {book['title']} ===")
    print(f"Total entities: {len(entities)}")
    for t, count in sorted(type_counts.items()):
        print(f"  {t}: {count}")

    print(f"\nSample (first 3):")
    for entity_id, entity in list(entities.items())[:3]:
        print(f"  [{entity_id}] {entity['raw_mentions']} ({entity['type']}, {entity['first_seen']})")

    full_size = len(json.dumps(entities_full, ensure_ascii=False))
    slim_size = len(json.dumps(entities_for_resolution, ensure_ascii=False))
    print(
        f"\nContext size:"
        f"\n  entities_full        = {full_size:>10,} chars  (→ wiki-generation)"
        f"\n  entities_for_resolution = {slim_size:>7,} chars  (→ entity-resolution)"
        f"\n  reduction: {100 * slim_size // full_size}% of full"
    )

    by_type = split_by_type(entities_full)
    print("\nPer-type file sizes:")
    for type_key, (filename, json_key) in [
        ("PERSON", ("persons_full.json", "persons_full")),
        ("PLACE", ("places_full.json", "places_full")),
        ("ORG", ("orgs_full.json", "orgs_full")),
    ]:
        size = len(json.dumps({json_key: by_type[type_key]}, ensure_ascii=False))
        print(f"  {filename}: {size:>10,} chars  ({len(by_type[type_key])} entities)")

    # Write per-type full JSON files to processing dir
    type_files = {
        "PERSON": ("persons_full.json", "persons_full"),
        "PLACE": ("places_full.json", "places_full"),
        "ORG": ("orgs_full.json", "orgs_full"),
    }
    for type_key, (filename, json_key) in type_files.items():
        out_path = paths.processing / filename
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({json_key: by_type[type_key]}, f, ensure_ascii=False)
        print(f"  Written: {out_path}", file=sys.stderr)

    ts = datetime.now().strftime("%Y-%m-%dT%Hh%Mm")
    output_path = paths.processing / f"extraction-{ts}.jsonl"

    with open(output_path, "w", encoding="utf-8") as f:
        for entity_id, entity in entities_full.items():
            f.write(json.dumps({"id": entity_id, **entity}, ensure_ascii=False) + "\n")

    print(f"\nOutput: {output_path} ({len(entities)} lines)")


if __name__ == "__main__":
    main()
