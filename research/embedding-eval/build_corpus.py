#!/usr/bin/env python3
"""STU-576 step 1: build a labelled same/different-person corpus from cached runs.

STU-490 concluded there was no training set from the committed 8-pair fixture. The
real artifacts carry one: `*_full.json` persists `mention_spans_by_chapter` (STU-489),
one `{surface, start, end}` per occurrence into the chapter text saved to
`chapters.json`. Grouping those spans by their canonical entity IS the label — same
entity is a `same` pair, different entities a `different` one. No hand-labelling.

The window is **masked over the mention itself**. Leaving the name in makes the task
string-matching, not disambiguation: STU-490's `win±K` kept it, which is why its
`different` pairs still scored 0.949 cosine — the arm never tested the question.
Other characters' names inside the window are kept; co-occurrence is signal a
production judge would also have, and the eval splits by book so it cannot leak.

    python research/embedding-eval/build_corpus.py <processing_output/slug> [...]
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "corpus"
WINDOW = 160
MIN_MENTIONS = 8
MASK = "[NAME]"


def _raw_mentions(value: object) -> list[str]:
    """`raw_mentions` is a list on most records and its `repr` on some older ones."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return [value]
        return [str(v) for v in parsed] if isinstance(parsed, list) else [str(parsed)]
    return []


def _narrative_chapters(book: Path) -> set[str] | None:
    """Chapter ids the section filter kept, or None on a cache predating STU-529."""
    data = json.loads((book / "epub_data.json").read_text(encoding="utf-8"))
    chapters = data.get("chapters") or []
    if not any("frontmatter" in c for c in chapters):
        return None
    return {c["id"] for c in chapters if not c.get("frontmatter")}


def build(book: Path) -> list[dict]:
    text_by_chapter = json.loads((book / "chapters.json").read_text(encoding="utf-8"))["chapters"]
    keep = _narrative_chapters(book)
    rows: list[dict] = []
    for artifact in sorted(book.glob("*_full.json")):
        entities = next(iter(json.loads(artifact.read_text(encoding="utf-8")).values()))
        for entity_id, record in entities.items():
            spans = record.get("mention_spans_by_chapter") or {}
            names = _raw_mentions(record.get("raw_mentions"))
            windows = []
            for chapter_id, occurrences in spans.items():
                if keep is not None and chapter_id not in keep:
                    continue
                text = text_by_chapter.get(chapter_id)
                if text is None:
                    continue
                for occurrence in occurrences:
                    start, end = occurrence["start"], occurrence["end"]
                    if text[start:end] != occurrence["surface"]:
                        continue  # offsets do not match this chapter text; drop, never guess
                    left = text[max(0, start - WINDOW):start]
                    right = text[end:end + WINDOW]
                    windows.append({"chapter": chapter_id, "text": f"{left}{MASK}{right}"})
            if len(windows) >= MIN_MENTIONS:
                rows.append(
                    {
                        "entity": entity_id,
                        "type": record.get("type"),
                        "name": names[0] if names else entity_id,
                        "windows": windows,
                    }
                )
    return rows


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    OUT.mkdir(exist_ok=True)
    for arg in sys.argv[1:]:
        book = Path(arg)
        rows = build(book)
        target = OUT / f"{book.name}.json"
        target.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        total = sum(len(r["windows"]) for r in rows)
        print(f"{book.name:40s} entities={len(rows):4d} windows={total:6d} -> {target}")


if __name__ == "__main__":
    main()
