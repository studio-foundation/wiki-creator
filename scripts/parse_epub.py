#!/usr/bin/env python3
"""
Stage 1: EPUB Parsing
Script executor interface: reads JSON from stdin, writes JSON to stdout.

Input:  { "file_path": "/path/to/book.epub" }
Output: { "title": "...", "author": "...", "chapters": [{ "id": "...", "title": "...", "content": "..." }] }
"""

import json
import sys


def parse_epub(file_path: str) -> dict:
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(file_path)

    title = book.get_metadata("DC", "title")
    title = title[0][0] if title else "Unknown"

    author = book.get_metadata("DC", "creator")
    author = author[0][0] if author else None

    chapters = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        if text:
            chapters.append({
                "id": item.get_id(),
                "title": item.get_name(),
                "content": text,
            })

    return {"title": title, "author": author, "chapters": chapters}


def main():
    payload = json.load(sys.stdin)
    file_path = payload.get("file_path")

    if not file_path:
        json.dump({"error": "missing field: file_path"}, sys.stdout)
        sys.exit(1)

    result = parse_epub(file_path)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
