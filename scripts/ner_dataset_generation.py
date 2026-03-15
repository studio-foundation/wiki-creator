#!/usr/bin/env python3
"""
Generate NER dataset from chapters.json using Anthropic API.
Output: JSONL with one annotated example per line.
"""
import json
import re
import sys
import time
from pathlib import Path
import anthropic

NER_PROMPT = """You are a specialist NER annotator for fantasy literature.
Identify ALL named entities in the text below.
Valid types: PERSON, PLACE, ORG, FACTION, EVENT.
Return ONLY valid JSON, no markdown, no explanation:
{
  "text": "<exact original text, unchanged>",
  "entities": [
    {"start": <int>, "end": <int>, "label": "<TYPE>", "text": "<extracted span>"}
  ]
}
Rules:
- start/end are character offsets into "text" (0-indexed)
- entity text must match text[start:end] exactly
- Do not annotate pronouns or determiners
- FACTION = groups/orders/guilds that are not formal ORGs (e.g. Radiants, Parshendi)
- ORG = formal organizations, kingdoms, armies
- Preserve exact casing from source
- If no entities found, return {"text": "...", "entities": []}

Text to annotate:
"""

MIN_CHUNK_CHARS = 200
TARGET_CHUNK_CHARS = 1600  # ~400 tokens


def chunk_text(text: str, target: int = TARGET_CHUNK_CHARS) -> list[str]:
    """Split text into chunks at sentence boundaries."""
    # Split on sentence-ending punctuation
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    chunks = []
    current = ""
    for sent in sentences:
        if len(current) + len(sent) > target and len(current) >= MIN_CHUNK_CHARS:
            chunks.append(current.strip())
            current = sent
        else:
            current = (current + " " + sent).strip() if current else sent
    if current.strip():
        chunks.append(current.strip())
    return chunks


def validate(annotation: dict) -> tuple[bool, str]:
    """Validate offsets and entity text match."""
    if not isinstance(annotation, dict):
        return False, "not a dict"
    text = annotation.get("text", "")
    entities = annotation.get("entities", [])
    if not isinstance(text, str) or not text:
        return False, "missing text"
    if not isinstance(entities, list):
        return False, "entities not a list"
    for i, ent in enumerate(entities):
        start = ent.get("start")
        end = ent.get("end")
        label = ent.get("label", "")
        ent_text = ent.get("text", "")
        if not isinstance(start, int) or not isinstance(end, int):
            return False, f"entity {i}: non-int offsets"
        if start < 0 or end > len(text) or start >= end:
            return False, f"entity {i}: out-of-bounds [{start}:{end}] len={len(text)}"
        extracted = text[start:end]
        if extracted != ent_text:
            return False, f"entity {i}: mismatch '{extracted}' != '{ent_text}'"
        if label not in {"PERSON", "PLACE", "ORG", "FACTION", "EVENT"}:
            return False, f"entity {i}: invalid label '{label}'"
    return True, "ok"


def annotate_chunk(client: anthropic.Anthropic, chunk: str) -> dict | None:
    """Call API and parse response."""
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": NER_PROMPT + chunk}]
        )
        raw = response.content[0].text.strip()
        # Strip markdown fences if present
        raw = re.sub(r'^```json\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)
        return json.loads(raw)
    except Exception as e:
        return None


def main():
    input_path = Path("/mnt/user-data/uploads/the_way_of_kings_chapters.json")
    output_path = Path("/mnt/user-data/outputs/ner_dataset_way_of_kings.jsonl")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(input_path) as f:
        data = json.load(f)
    chapters = data.get("chapters", data)

    # Filter out very short chapters (maps, illustrations, etc.)
    usable = {k: v for k, v in chapters.items() if len(v) >= 1000}
    keys = list(usable.keys())[:30]  # Max 30 chapters for first batch
    
    print(f"Chapitres utilisables: {len(usable)} | On traite: {len(keys)}")

    client = anthropic.Anthropic()

    total_chunks = 0
    valid_count = 0
    invalid_count = 0
    chunks_per_chap = 5

    with open(output_path, "w") as out:
        for chap_idx, chap_id in enumerate(keys):
            text = usable[chap_id]
            chunks = chunk_text(text)[:chunks_per_chap]
            print(f"\n[{chap_idx+1}/{len(keys)}] {chap_id} ({len(text)} chars, {len(chunks)} chunks)")

            for i, chunk in enumerate(chunks):
                total_chunks += 1
                annotation = annotate_chunk(client, chunk)
                if annotation is None:
                    invalid_count += 1
                    print(f"  chunk {i+1}: API error")
                    continue

                ok, reason = validate(annotation)
                if ok:
                    record = {
                        "text": annotation["text"],
                        "entities": annotation["entities"],
                        "chapter_id": chap_id,
                        "chunk_index": i,
                        "source": "the_way_of_kings",
                        "language": "en"
                    }
                    out.write(json.dumps(record, ensure_ascii=False) + "\n")
                    valid_count += 1
                    ent_count = len(annotation["entities"])
                    ent_types = {}
                    for e in annotation["entities"]:
                        ent_types[e["label"]] = ent_types.get(e["label"], 0) + 1
                    print(f"  chunk {i+1}: {ent_count} entités {ent_types}")
                else:
                    invalid_count += 1
                    print(f"  chunk {i+1}: REJETÉ — {reason}")

                # Small delay to avoid rate limits
                time.sleep(0.2)

    print(f"\n{'='*50}")
    print(f"Total chunks: {total_chunks}")
    print(f"Valides: {valid_count}")
    print(f"Rejetés: {invalid_count}")
    print(f"Output: {output_path}")

    # Quick entity stats
    if valid_count > 0:
        type_counts = {}
        with open(output_path) as f:
            for line in f:
                rec = json.loads(line)
                for ent in rec["entities"]:
                    t = ent["label"]
                    type_counts[t] = type_counts.get(t, 0) + 1
        print(f"\nDistribution par type:")
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {t}: {c}")


if __name__ == "__main__":
    main()