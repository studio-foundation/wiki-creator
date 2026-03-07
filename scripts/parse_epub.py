#!/usr/bin/env python3
"""
Stage 1: EPUB Parsing
Script executor interface: reads JSON from stdin, writes JSON to stdout.

Input:  { "file_path": "/path/to/book.epub" }
Output: { "title": "...", "author": "...", "chapters": [{ "id": "...", "title": "...", "content": "..." }], "pov_detection": { "pov": "...", "first_person_count": int, "total_tokens": int, "confidence": "..." } }
"""

import html
import json
import os
import re
import sys
import yaml


def clean_chapter_text(text: str) -> str:
    """Normalize chapter text to remove noise before LLM processing."""
    # 1. Unescape HTML entities (&nbsp; → space, &mdash; → —, etc.)
    text = html.unescape(text)
    # 1b. Normaliser \xa0 (non-breaking space) en espace standard
    #     html.unescape() convertit &nbsp; → \xa0, donc ce replace vient après.
    text = text.replace('\xa0', ' ')

    # 2. Collapse runs of 2+ newlines into exactly \n\n (paragraph break)
    text = re.sub(r'\n{2,}', '\n\n', text)

    # 3. Replace remaining single \n with a space
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)

    # 3b. Joindre lettre majuscule isolée + mot suivant en minuscule
    #     Artefact lettrine HTML : <span>P</span>edro → "P\nedro" (via BS4) → après step 3 → "P edro" → "Pedro"
    #     Doit venir APRÈS step 3 pour que le \n ait déjà été converti en espace.
    #     Ne touche pas "M. Pedro" (suivi d'un point) ni les fins de phrase.
    text = re.sub(r'(?<!\w)([A-ZÀÂÇÉÈÊËÎÏÔÙÛÜ]) ([a-záàâçéèêëîïôùûü])', r'\1\2', text)

    # 4. Normalize runs of spaces/tabs to a single space
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 5. Strip each paragraph
    paragraphs = [p.strip() for p in text.split('\n\n')]
    text = '\n\n'.join(p for p in paragraphs if p)

    return text.strip()


# French first-person pronouns (word-boundary matched)
_FIRST_PERSON_RE = re.compile(
    r"\b(?:je|me|moi|mon|ma|mes)\b|\bm'|\bj'",
    re.IGNORECASE,
)


def detect_pov(text: str) -> dict:
    """Detect narrative point of view from raw chapter text."""
    tokens = text.split()
    total_tokens = len(tokens)
    if total_tokens == 0:
        return {"pov": "omniscient", "first_person_count": 0, "total_tokens": 0, "confidence": "low"}

    first_person_count = len(_FIRST_PERSON_RE.findall(text))
    ratio = first_person_count / total_tokens

    if ratio > 0.05:
        confidence = "high"
        pov = "first_person"
    elif ratio > 0.01:
        confidence = "medium"
        pov = "first_person"
    else:
        confidence = "low" if ratio > 0 else "high"
        has_thought_markers = bool(re.search(
            r"\b(il pensait|elle pensait|il savait|elle savait|il sentait|elle sentait)\b",
            text,
            re.IGNORECASE,
        ))
        pov = "third_limited" if has_thought_markers else "omniscient"

    return {
        "pov": pov,
        "first_person_count": first_person_count,
        "total_tokens": total_tokens,
        "confidence": confidence,
    }


MIN_CHAPTER_CHARS = 100


def parse_epub(file_path: str) -> dict:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(file_path)

    title = book.get_metadata("DC", "title")
    title = title[0][0] if title else "Unknown"

    author = book.get_metadata("DC", "creator")
    author = author[0][0] if author else None

    # Use EPUB spine order (the official reading order).
    spine_ids = [item_id for item_id, _ in book.spine]
    items_by_id = {
        item.get_id(): item
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT)
    }

    chapters = []
    for spine_id in spine_ids:
        item = items_by_id.get(spine_id)
        if item is None:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        raw_text = soup.get_text(separator="\n", strip=True)
        cleaned = clean_chapter_text(raw_text)
        if len(cleaned) < MIN_CHAPTER_CHARS:
            continue
        chapters.append({
            "id": item.get_id(),
            "title": item.get_name(),
            "content": cleaned,
        })

    # Compute POV per chapter, then take modal result for robustness
    # (avoids dilution in mixed-POV or frame-narrative books)
    if chapters:
        chapter_results = [detect_pov(ch["content"]) for ch in chapters]
        pov_counts: dict[str, int] = {}
        for r in chapter_results:
            pov_counts[r["pov"]] = pov_counts.get(r["pov"], 0) + 1
        modal_pov = max(pov_counts, key=lambda p: pov_counts[p])
        # Aggregate stats from all chapters
        total_fp = sum(r["first_person_count"] for r in chapter_results)
        total_tokens = sum(r["total_tokens"] for r in chapter_results)
        # Re-assess confidence from aggregate ratio
        agg_ratio = total_fp / total_tokens if total_tokens > 0 else 0
        if modal_pov == "first_person":
            confidence = "high" if agg_ratio > 0.05 else "medium" if agg_ratio > 0.01 else "low"
        else:
            confidence = "high"
        pov_detection = {
            "pov": modal_pov,
            "first_person_count": total_fp,
            "total_tokens": total_tokens,
            "confidence": confidence,
        }
    else:
        pov_detection = {"pov": "omniscient", "first_person_count": 0, "total_tokens": 0, "confidence": "low"}

    return {"title": title, "author": author, "chapters": chapters, "pov_detection": pov_detection}


def main():
    payload = json.load(sys.stdin)
    input_data = yaml.safe_load(payload.get("additional_context", "")) or {}
    file_path = input_data.get("file_path")

    if not file_path:
        json.dump({"error": "missing field: file_path"}, sys.stdout)
        sys.exit(1)

    result = parse_epub(file_path)
    os.makedirs("processing_output", exist_ok=True)
    with open("processing_output/epub_data.json", "w", encoding="utf-8") as _f:
        json.dump(result, _f, ensure_ascii=False)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
