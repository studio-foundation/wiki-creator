#!/usr/bin/env python3
"""
Stage 2: spaCy Entity Extraction
Script executor interface: reads JSON from stdin, writes JSON to stdout.

Input:
  {
    "title": "...",
    "author": "...",
    "chapters": [{"id": "...", "title": "...", "content": "..."}],
    "spacy_model": "fr_core_news_lg"
  }

Output:
  {
    "entities": {
      "entity_001": {
        "raw_mentions": ["David Martín"],
        "first_seen": "ch01",
        "mentions_by_chapter": {
          "ch01": ["David Martín ouvrit la porte et aperçut..."]
        }
      }
    }
  }
"""

import json
import sys

# Entity labels to keep. Covers both French and English spaCy models.
# French (fr_core_news_*): PER, LOC, ORG
# English (en_core_web_*): PERSON, GPE, LOC, ORG, FAC, NORP
KEPT_LABELS = {"PER", "LOC", "ORG", "PERSON", "GPE", "FAC", "NORP"}


def extract_context(doc, span) -> str:
    """
    Extract ~2-3 sentences of context around the entity span.
    Returns the sentence containing the entity plus one sentence on each side.
    """
    sentences = list(doc.sents)
    if not sentences:
        return span.text

    span_sent_start = span.sent.start
    sent_idx = next(
        (i for i, s in enumerate(sentences) if s.start == span_sent_start),
        0,
    )

    start = max(0, sent_idx - 1)
    end = min(len(sentences), sent_idx + 2)
    return " ".join(s.text.strip() for s in sentences[start:end])


def extract_entities(chapters: list[dict], nlp) -> dict:
    """
    Process all chapters in order and build the entity registry.

    Grouped by normalized mention text (lowercase + stripped).
    Same surface form in multiple chapters → one entry, multiple chapter keys.
    Alias resolution is left to the LLM stage.
    """
    registry: dict[str, dict] = {}
    entity_counter = 0

    for chapter in chapters:
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
                    "raw_mentions": [ent.text],
                    "first_seen": chapter["id"],
                    "mentions_by_chapter": {},
                }
            else:
                if ent.text not in registry[key]["raw_mentions"]:
                    registry[key]["raw_mentions"].append(ent.text)

            registry[key]["mentions_by_chapter"].setdefault(chapter["id"], [])
            registry[key]["mentions_by_chapter"][chapter["id"]].append(context)

    return {
        "entities": {
            v["id"]: {k: v[k] for k in v if k != "id"}
            for v in registry.values()
        }
    }


def main():
    payload = json.load(sys.stdin)

    chapters = payload.get("chapters", [])
    spacy_model = payload.get("spacy_model", "en_core_web_sm")

    if not chapters:
        json.dump({"error": "missing field: chapters"}, sys.stdout)
        sys.exit(1)

    import spacy
    nlp = spacy.load(spacy_model)

    result = extract_entities(chapters, nlp)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
