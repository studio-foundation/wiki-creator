#!/usr/bin/env python3
"""
Standalone test: run entity extraction on the full book and print a summary.
Usage: python scripts/test_extraction.py [book_path] [spacy_model] [output.jsonl]
Defaults to the book configured in .studio/inputs/book.input.yaml.

Output JSONL format (one line per entity):
  {"id": "entity_001", "type": "PERSON", "raw_mentions": [...], "first_seen": "ch01",
   "mentions_by_chapter": {"ch01": ["sentence..."]}}
"""

import json
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.parse_epub import parse_epub
from scripts.entity_extraction import extract_entities, split_entities

BOOK_PATH = "books/carlos-ruiz-zafon/le-jeu-de-lange.epub"
SPACY_MODEL = "fr_core_news_lg"


def main() -> None:
    book_path = sys.argv[1] if len(sys.argv) > 1 else BOOK_PATH
    spacy_model = sys.argv[2] if len(sys.argv) > 2 else SPACY_MODEL
    output_path = sys.argv[3] if len(sys.argv) > 3 else None

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

    if output_path is None:
        ts = datetime.now().strftime("%Y-%m-%dT%Hh%Mm")
        output_path = f"extraction-{ts}.jsonl"

    with open(output_path, "w", encoding="utf-8") as f:
        for entity_id, entity in entities_full.items():
            f.write(json.dumps({"id": entity_id, **entity}, ensure_ascii=False) + "\n")

    print(f"\nOutput: {output_path} ({len(entities)} lines)")


if __name__ == "__main__":
    main()
