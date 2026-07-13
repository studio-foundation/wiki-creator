#!/usr/bin/env python3
"""Regenerate the extraction *seed* fixtures for the golden resolution run.

The golden chain (tests/test_e2e_golden.py) starts downstream of NER: it needs
a frozen entity-extraction output for the smoke novella (tests/fixtures/e2e/).
Real extraction requires a spaCy model, which is not available everywhere the
suite runs, so the seed is committed. This script rebuilds it deterministically
from the novella text with a longest-match scanner over a fixed inventory of
the novella's proper nouns — mimicking the shapes documented in
scripts/entity_extraction.py (registry keyed by lowercased surface form,
mentions_by_chapter capped at 3 contexts of sentence ±1, uncapped
mention_spans_by_chapter offsets per occurrence, per-type full files).

Run from the repo root after editing the novella chapters:

    python tests/fixtures/e2e/golden/gen_seed.py

The @requires_en_sm shape-compatibility test in tests/test_e2e_golden.py keeps
this seed honest against real extraction output in CI.
"""
import json
import re
import sys
from pathlib import Path

SEED_DIR = Path(__file__).resolve().parent / "seed"
TESTS_DIR = Path(__file__).resolve().parents[3]

# The novella's proper nouns, longest-first so "Captain Elias Thorn" consumes
# its span before "Elias Thorn" can match inside it. This is fixture data tied
# to tests/fixtures/e2e/ch0*.txt, not pipeline vocabulary.
INVENTORY = [
    ("Captain Elias Thorn", "PERSON"),
    ("Elias Thorn", "PERSON"),
    ("Mira Vale", "PERSON"),
    ("Warehouse Nine", "PLACE"),
    ("Warehouse nine", "PLACE"),
    ("Port Saffron", "PLACE"),
    ("Salt Guild", "ORG"),
    ("Heron", "OTHER"),
]

TYPE_FILES = {
    "PERSON": ("persons_full.json", "persons_full"),
    "PLACE": ("places_full.json", "places_full"),
    "ORG": ("orgs_full.json", "orgs_full"),
    "EVENT": ("events_full.json", "events_full"),
}


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=\.)\s+", text) if s.strip()]


def _context(sentences: list[str], char_pos: int, text: str) -> str:
    """Sentence containing char_pos plus one sentence on each side."""
    offset = 0
    idx = len(sentences) - 1
    for i, sent in enumerate(sentences):
        start = text.index(sent, offset)
        end = start + len(sent)
        offset = end
        if start <= char_pos < end:
            idx = i
            break
    lo, hi = max(0, idx - 1), min(len(sentences), idx + 2)
    return " ".join(sentences[lo:hi])


def _scan_chapter(text: str) -> list[tuple[int, str, str]]:
    """Longest-match scan: returns [(char_pos, surface, type)] in text order."""
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, str, str]] = []
    for surface, etype in INVENTORY:
        for m in re.finditer(re.escape(surface), text):
            span = (m.start(), m.end())
            if any(s < span[1] and span[0] < e for s, e in taken):
                continue
            taken.append(span)
            found.append((m.start(), surface, etype))
    found.sort()
    return found


def build_seed(chapters: list[dict]) -> dict:
    """Replicates extract_entities() registry semantics on the inventory."""
    registry: dict[str, dict] = {}
    counter = 0
    for chapter in chapters:
        chapter_id = chapter["id"]
        text = chapter["content"]
        sentences = _sentences(text)
        for pos, surface, etype in _scan_chapter(text):
            key = surface.lower().strip()
            if key not in registry:
                counter += 1
                registry[key] = {
                    "id": f"entity_{counter:03d}",
                    "type": etype,
                    "raw_mentions": [surface],
                    "first_seen": chapter_id,
                    "mentions_by_chapter": {},
                    "mention_spans_by_chapter": {},
                    "mention_count": 1,
                }
            else:
                if surface not in registry[key]["raw_mentions"]:
                    registry[key]["raw_mentions"].append(surface)
                registry[key]["mention_count"] += 1
            per_chapter = registry[key]["mentions_by_chapter"].setdefault(chapter_id, [])
            if len(per_chapter) < 3:
                per_chapter.append(_context(sentences, pos, text))
            registry[key]["mention_spans_by_chapter"].setdefault(chapter_id, []).append(
                {"surface": surface, "start": pos, "end": pos + len(surface)}
            )
    return {
        entry["id"]: {k: v for k, v in entry.items() if k != "id"}
        for entry in registry.values()
    }


def main() -> None:
    sys.path.insert(0, str(TESTS_DIR))
    from test_e2e_smoke import CHAPTER_TITLES, FIXTURE_DIR

    # Same ids and content parse_epub derives from the smoke EPUB: ebooklib
    # item ids, and the chapter <h1> title prepended to the paragraph text.
    chapters = [
        {
            "id": f"chapter_{i}",
            "title": title,
            "content": title + " " + " ".join(
                (FIXTURE_DIR / f"ch{i + 1:02d}.txt")
                .read_text(encoding="utf-8")
                .strip()
                .split("\n\n")
            ),
        }
        for i, title in enumerate(CHAPTER_TITLES)
    ]

    entities_full = build_seed(chapters)
    full_only = {"mentions_by_chapter", "mention_spans_by_chapter"}
    entities_for_resolution = {
        eid: {k: v for k, v in e.items() if k not in full_only}
        for eid, e in entities_full.items()
    }

    SEED_DIR.mkdir(parents=True, exist_ok=True)
    (SEED_DIR / "extraction_output.json").write_text(
        json.dumps({"entities_for_resolution": entities_for_resolution},
                   ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    for etype, (filename, json_key) in TYPE_FILES.items():
        by_type = {
            eid: e for eid, e in entities_full.items() if e["type"] == etype
        }
        (SEED_DIR / filename).write_text(
            json.dumps({json_key: by_type}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    print(f"seed written to {SEED_DIR} ({len(entities_full)} entities)")


if __name__ == "__main__":
    main()
