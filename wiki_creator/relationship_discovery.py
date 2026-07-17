"""Schema-guided relation discovery — pure chunking and book-level fold (STU-556).

The discovery stage sends one `studio run` per chunk and gets back a list of
typed pairs per chunk. This module is the deterministic scaffolding around that
call: cut a chapter into paragraph-aligned chunks (STU-523 put the `\\n\\n`
breaks there for exactly this), clean each chunk's reply against the roster and
vocabulary, and fold every chunk's vote into one book-level pair.

Ported from `research/relation-eval` (`run_llm_schema.chunks_of`, `aggregate.py`,
`build_gold.valid_relations`) — the harness proved the fold on Eragon, so this is
the same logic, stripped of the benchmark-only `explicit`/`implicit` axis and
reshaped to the production `Relationship` dict.

`aggregate` orders a pair's types by how many chunks evidenced each — the primary
is the book's dominant reading. A relation moves inside one book (wary_alliance
for twenty chapters, friends by the end), and that arc is what the demoted
classifier writes as `evolution` prose; here it only decides the primary type.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from wiki_creator.relationship_eval import pair_key

SYMMETRIC = "symétrique"
DIRECTIONS = frozenset({SYMMETRIC, "A→B", "B→A"})
_FLIP = {"A→B": "B→A", "B→A": "A→B", SYMMETRIC: SYMMETRIC}

_MAX_EVIDENCE_CHARS = 200
_MAX_SAMPLE_CONTEXTS = 3


def flip(direction: str) -> str:
    """Restate a direction against the opposite entity order."""
    return _FLIP.get(direction, direction)


def chunk_chapters(chapters: list[dict], size: int) -> list[dict]:
    """Split ordered chapters into paragraph-aligned chunks under ``size`` chars.

    Packs whole paragraphs (split on ``\\n\\n``) into a chunk until the next one
    would overflow ``size``, then starts a new chunk. Never splits a paragraph.
    Chunk ids are ``{chapter_id}:{i}`` so a vote traces back to its chapter.
    """
    out: list[dict] = []
    for chapter in chapters:
        buf = ""
        parts: list[str] = []
        for para in chapter["text"].split("\n\n"):
            if buf and len(buf) + len(para) > size:
                parts.append(buf)
                buf = para
            else:
                buf = f"{buf}\n\n{para}" if buf else para
        if buf:
            parts.append(buf)
        for i, text in enumerate(parts):
            out.append({
                "id": f"{chapter['id']}:{i}",
                "chapter_id": chapter["id"],
                "title": chapter["title"],
                "text": text,
            })
    return out


def valid_relations(
    raw: object, roster_names: set[str], allowed_types: Iterable[str]
) -> tuple[list[dict], list[str]]:
    """Split a chunk's relations into (well-formed, rejected-with-reason).

    The studio contract enforces the object shape; this rejects what would crash
    or silently mistype the fold — an off-roster or self name, an off-vocabulary
    type or direction. The vocabulary is passed in because a book declares its own
    types (STU-472).
    """
    types = set(allowed_types)
    kept: list[dict] = []
    rejected: list[str] = []
    if not isinstance(raw, list):
        return [], [f"relations is {type(raw).__name__}, not a list"]

    for rel in raw:
        if not isinstance(rel, dict):
            rejected.append(f"relation is {type(rel).__name__}, not an object")
            continue
        missing = [
            k for k in ("entity_a", "entity_b", "relationship_type", "direction")
            if not isinstance(rel.get(k), str) or not rel[k].strip()
        ]
        if missing:
            rejected.append(f"missing/blank {missing}")
            continue
        a, b = rel["entity_a"].strip(), rel["entity_b"].strip()
        if a not in roster_names or b not in roster_names:
            rejected.append(f"off-roster: {a} / {b}")
            continue
        if a == b:
            rejected.append(f"self-pair: {a}")
            continue
        if rel["relationship_type"] not in types:
            rejected.append(f"type off-vocabulary: {rel['relationship_type']!r}")
            continue
        if rel["direction"] not in DIRECTIONS:
            rejected.append(f"direction off-vocabulary: {rel['direction']!r}")
            continue
        kept.append({
            "entity_a": a,
            "entity_b": b,
            "relationship_type": rel["relationship_type"],
            "direction": rel["direction"],
            "evidence": (rel.get("evidence") or "").strip()[:_MAX_EVIDENCE_CHARS],
        })
    return kept, rejected


def aggregate(votes: list[dict], roster_names: set[str]) -> list[dict]:
    """Fold per-chunk relation votes into book-level ``Relationship`` dicts.

    ``votes`` is ``[{"chapter_id", "relations": [clean rel]}]``. A pair's primary
    ``relationship_type`` is the type the most chunks evidenced; ``direction`` is
    stated against the sorted ``pair_key`` (a vote naming the pair the other way
    is flipped). ``cooccurrence_count`` is the number of chunks that evidenced the
    pair, and ``sample_contexts`` the first few evidence quotes.
    """
    acc: dict[tuple, dict] = {}
    for vote in votes:
        chapter_id = vote["chapter_id"]
        for rel in vote["relations"]:
            a, b = rel["entity_a"], rel["entity_b"]
            if a not in roster_names or b not in roster_names or a == b:
                continue
            key = pair_key(a, b)
            slot = acc.setdefault(key, {
                "types": Counter(), "directions": Counter(),
                "chapters": set(), "evidence": [], "votes": 0,
            })
            slot["types"][rel["relationship_type"]] += 1
            direction = rel["direction"] if (a, b) == key else flip(rel["direction"])
            slot["directions"][direction] += 1
            slot["chapters"].add(chapter_id)
            slot["votes"] += 1
            if rel.get("evidence"):
                slot["evidence"].append(rel["evidence"])

    pairs: list[dict] = []
    for key, slot in acc.items():
        pairs.append({
            "entity_a": key[0],
            "entity_b": key[1],
            "relationship_type": slot["types"].most_common(1)[0][0],
            "direction": slot["directions"].most_common(1)[0][0],
            "chapters": sorted(slot["chapters"]),
            "cooccurrence_count": slot["votes"],
            "sample_contexts": slot["evidence"][:_MAX_SAMPLE_CONTEXTS],
        })

    pairs.sort(key=lambda p: (-len(p["chapters"]), p["entity_a"], p["entity_b"]))
    return pairs
