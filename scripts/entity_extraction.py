#!/usr/bin/env python3
"""
Stage 2: spaCy Entity Extraction
Script executor interface: reads JSON from stdin, writes JSON to stdout.

Input (via Studio context):
  additional_context: YAML string with spacy_model
  previous_outputs.epub-parse: { title, author, chapters: [{id, title, content}] }

Output (stdout — passed to entity-resolution as previous_stage_output):
  {
    "entities_for_resolution": {
      "entity_001": { "type": "PERSON", "raw_mentions": ["David Martín"], "first_seen": "ch01" }
    }
  }

Side effect (file written to project root):
  entities_full.json — same registry with "mentions_by_chapter" included,
  read by wiki-generation via repo_manager-read_file.

Standalone test mode:
  python scripts/entity_extraction.py --test
  Runs on hardcoded English chapters, prints entity count + 3-entity sample.
  Does not write entities_full.json.
"""

import json
import sys
import yaml

# Entity labels to keep. Covers both French and English spaCy models.
# French (fr_core_news_*): PER, LOC, ORG
# English (en_core_web_*): PERSON, GPE, LOC, ORG, FAC, NORP
KEPT_LABELS = {"PER", "LOC", "ORG", "PERSON", "GPE", "FAC", "NORP"}

LABEL_TO_TYPE = {
    "PER": "PERSON",
    "PERSON": "PERSON",
    "LOC": "PLACE",
    "GPE": "PLACE",
    "FAC": "PLACE",
    "ORG": "ORG",
    "NORP": "ORG",
}

# Hardcoded chapters for --test mode (English, uses en_core_web_sm)
TEST_CHAPTERS = [
    {
        "id": "ch01",
        "title": "Chapter 1",
        "content": (
            "David Martin was a young writer who lived in Barcelona. "
            "He worked for a publisher named Vidal. "
            "The city of Barcelona was his home."
        ),
    },
    {
        "id": "ch02",
        "title": "Chapter 2",
        "content": (
            "David was walking through the old quarter when he met Pedro Vidal again. "
            "Barcelona was beautiful that evening. "
            "Martin stopped in front of the cathedral."
        ),
    },
    {
        "id": "ch03",
        "title": "Chapter 3",
        "content": (
            "The Vidal house was located on the main boulevard. "
            "David Martin knocked on the door. "
            "The Raval publishing house had closed its doors."
        ),
    },
]


def extract_context(doc, span) -> str:
    """
    Extract ~2-3 sentences of context around the entity span.
    Returns the sentence containing the entity plus one sentence on each side.
    """
    sentences = list(doc.sents)
    if not sentences:
        return span.text

    span_sent_start = span.sent.start
    try:
        sent_idx = next(
            i for i, s in enumerate(sentences) if s.start == span_sent_start
        )
    except StopIteration:
        return span.sent.text

    start = max(0, sent_idx - 1)
    end = min(len(sentences), sent_idx + 2)
    return " ".join(s.text.strip() for s in sentences[start:end])


def extract_entities(chapters: list[dict], nlp) -> dict:
    """
    Process all chapters in order and build the entity registry.

    Returns:
      {"entities": {entity_id: {type, raw_mentions, first_seen, mentions_by_chapter}}}

    Grouped by normalized mention text (lowercase + stripped).
    Same surface form in multiple chapters → one entry, multiple chapter keys.
    Alias resolution is left to the LLM stage.
    """
    registry: dict[str, dict] = {}
    entity_counter = 0

    for chapter in chapters:
        if "content" not in chapter or "id" not in chapter:
            raise ValueError(f"chapter missing required fields 'content' or 'id': {list(chapter.keys())}")
        doc = nlp(chapter["content"])
        for ent in doc.ents:
            if ent.label_ not in KEPT_LABELS:
                continue

            key = ent.text.lower().strip()
            if not key:
                continue

            context = extract_context(doc, ent)

            if key not in registry:
                entity_counter += 1
                registry[key] = {
                    "id": f"entity_{entity_counter:03d}",
                    "type": LABEL_TO_TYPE.get(ent.label_, "OTHER"),
                    "raw_mentions": [ent.text],
                    "first_seen": chapter["id"],
                    "mentions_by_chapter": {},
                }
            else:
                if ent.text not in registry[key]["raw_mentions"]:
                    registry[key]["raw_mentions"].append(ent.text)

            registry[key]["mentions_by_chapter"].setdefault(chapter["id"], [])
            if len(registry[key]["mentions_by_chapter"][chapter["id"]]) < 3:
                registry[key]["mentions_by_chapter"][chapter["id"]].append(context)

    return {
        "entities": {
            v["id"]: {k: v[k] for k in v if k != "id"}
            for v in registry.values()
        }
    }


def split_entities(entities: dict) -> tuple[dict, dict]:
    """
    Split the full entity registry into two structures:
    - entities_for_resolution: lightweight (type, raw_mentions, first_seen only)
    - entities_full: complete (includes mentions_by_chapter)

    Returns (entities_for_resolution, entities_full).
    """
    entities_for_resolution = {
        entity_id: {k: v for k, v in entity.items() if k != "mentions_by_chapter"}
        for entity_id, entity in entities.items()
    }
    return entities_for_resolution, entities


def run_test_mode() -> None:
    """
    Standalone test mode: run entity extraction on hardcoded chapters.
    Prints entity count by type and a sample of 3 entities.
    Does not read stdin or write entities_full.json.
    """
    import spacy

    print("Loading en_core_web_sm...", file=sys.stderr)
    nlp = spacy.load("en_core_web_sm")

    print("Extracting entities from 3 hardcoded chapters...", file=sys.stderr)
    try:
        result = extract_entities(TEST_CHAPTERS, nlp)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    entities = result["entities"]
    entities_for_resolution, _ = split_entities(entities)

    type_counts: dict[str, int] = {}
    for entity in entities.values():
        t = entity["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print(f"\n=== Test Mode Results ===")
    print(f"Total entities extracted: {len(entities)}")
    for t, count in sorted(type_counts.items()):
        print(f"  {t}: {count}")

    print(f"\nSample (first 3 entities in entities_for_resolution):")
    for entity_id, entity in list(entities_for_resolution.items())[:3]:
        print(
            f"  [{entity_id}] mentions={entity['raw_mentions']} "
            f"type={entity['type']} first_seen={entity['first_seen']}"
        )

    full_size = len(json.dumps(entities, ensure_ascii=False))
    slim_size = len(json.dumps(entities_for_resolution, ensure_ascii=False))
    print(
        f"\nSize: entities_full={full_size} chars, entities_for_resolution={slim_size} chars "
        f"({100 * slim_size // full_size if full_size else 0}% of full)"
    )


def main() -> None:
    if "--test" in sys.argv:
        run_test_mode()
        return

    payload = json.load(sys.stdin)

    input_data = yaml.safe_load(payload.get("additional_context", "")) or {}
    prev_outputs = payload.get("previous_outputs", {})
    epub_output = next(iter(prev_outputs.values()), {}) if prev_outputs else {}
    chapters = epub_output.get("chapters", [])
    spacy_model = input_data.get("spacy_model", "en_core_web_sm")

    if not chapters:
        json.dump({"error": "missing field: chapters"}, sys.stdout)
        sys.exit(1)

    import spacy
    nlp = spacy.load(spacy_model)

    try:
        result = extract_entities(chapters, nlp)
    except ValueError as e:
        json.dump({"error": str(e)}, sys.stdout)
        sys.exit(1)

    entities_for_resolution, entities_full = split_entities(result["entities"])

    # Write full entities to disk for wiki-generation to read via repo_manager-read_file
    with open("entities_full.json", "w", encoding="utf-8") as f:
        json.dump({"entities_full": entities_full}, f, ensure_ascii=False)

    # Output lightweight entities to stdout → becomes entity-resolution's previous_stage_output
    json.dump({"entities_for_resolution": entities_for_resolution}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
