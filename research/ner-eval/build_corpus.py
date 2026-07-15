#!/usr/bin/env python3
"""Sample an eval corpus from a parsed EPUB. Deterministic given --seed.

The book must be absent from ner_dataset/ — wiki-ner-en is trained on those, and
scoring it on its own training distribution measures nothing.

Usage:
    python build_corpus.py \\
        --epub-data ../../library/christopher_paolini/inheritance/processing_output/01_eragon/epub_data.json \\
        --first-chapter id_7 --last-chapter id_66 --chunks 120 --seed 42
"""
import argparse
import json
import random
import sys

from chunking import chunk_text


def narrative_chapters(chapters: list[dict], first: str, last: str, min_chars: int) -> list[dict]:
    """Chapters between first and last inclusive, in book order, above min_chars.

    Front/back matter (copyright, glossary, next-book preview) carries real
    entities that are not this book's fiction, so it is cut by id range rather
    than by length. The length floor cuts filler the EPUB interleaves.
    """
    ids = [c["id"] for c in chapters]
    try:
        lo, hi = ids.index(first), ids.index(last)
    except ValueError as e:
        sys.exit(f"chapter id not found in epub_data: {e}")
    if lo > hi:
        sys.exit(f"--first-chapter {first} comes after --last-chapter {last}")
    return [c for c in chapters[lo:hi + 1] if len(c["content"]) >= min_chars]


def build(chapters: list[dict], n_chunks: int, seed: int) -> list[dict]:
    pool = [
        {"id": f"{c['id']}:{i}", "text": chunk,
         "chapter_id": c["id"], "chapter_title": c["title"], "chunk_index": i}
        for c in chapters
        for i, chunk in enumerate(chunk_text(c["content"]))
    ]
    if n_chunks >= len(pool):
        return pool
    picked = random.Random(seed).sample(range(len(pool)), n_chunks)
    return [pool[i] for i in sorted(picked)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epub-data", required=True)
    ap.add_argument("--first-chapter", required=True)
    ap.add_argument("--last-chapter", required=True)
    ap.add_argument("--chunks", type=int, default=120)
    ap.add_argument("--min-chars", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="corpus.jsonl")
    args = ap.parse_args()

    with open(args.epub_data, encoding="utf-8") as f:
        chapters = json.load(f)["chapters"]

    kept = narrative_chapters(chapters, args.first_chapter, args.last_chapter, args.min_chars)
    corpus = build(kept, args.chunks, args.seed)

    with open(args.out, "w", encoding="utf-8") as f:
        for rec in corpus:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    chars = sum(len(r["text"]) for r in corpus)
    print(f"{len(kept)} narrative chapters -> {len(corpus)} chunks, {chars} chars -> {args.out}")


if __name__ == "__main__":
    main()
