#!/usr/bin/env python3
"""
Stage 1: EPUB Parsing
Script executor interface: reads JSON from stdin, writes JSON to stdout.

Input:  { "file_path": "/path/to/book.epub" }
Output: { "title": "...", "author": "...", "chapters": [{ "id": "...", "title": "...", "content": "..." }] }
"""

import html
import json
import re
import sys
import yaml


def clean_chapter_text(text: str) -> str:
    """Normalize chapter text to remove noise before LLM processing."""
    # 1. Unescape HTML entities (&nbsp; → space, &mdash; → —, etc.)
    text = html.unescape(text)

    # 2. Collapse runs of 2+ newlines into exactly \n\n (paragraph break)
    text = re.sub(r'\n{2,}', '\n\n', text)

    # 3. Replace remaining single \n with a space
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)

    # 4. Normalize runs of spaces/tabs to a single space
    text = re.sub(r'[ \t]{2,}', ' ', text)

    # 5. Strip each paragraph
    paragraphs = [p.strip() for p in text.split('\n\n')]
    text = '\n\n'.join(p for p in paragraphs if p)

    return text.strip()


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

    return {"title": title, "author": author, "chapters": chapters}


def main():
    payload = json.load(sys.stdin)
    input_data = yaml.safe_load(payload.get("additional_context", "")) or {}
    file_path = input_data.get("file_path")

    if not file_path:
        json.dump({"error": "missing field: file_path"}, sys.stdout)
        sys.exit(1)

    result = parse_epub(file_path)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
