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

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

from wiki_creator.relationship_eval import pair_key

SYMMETRIC = "symétrique"
DIRECTIONS = frozenset({SYMMETRIC, "A→B", "B→A"})
_FLIP = {"A→B": "B→A", "B→A": "A→B", SYMMETRIC: SYMMETRIC}

_MAX_EVIDENCE_CHARS = 200
_MAX_SAMPLE_CONTEXTS = 3

# A chunk can only exceed ``size`` when a single paragraph does — packing flushes
# ``buf`` before it overflows. Past this factor the paragraph is not a long passage
# but a whole chapter with no ``\\n\\n`` to split on (a pre-STU-523 epub_data.json),
# where ``size`` is silently a no-op. Warn, don't fail: a real single-paragraph
# passage over the factor is possible.
_OVERSIZE_FACTOR = 2


def flip(direction: str) -> str:
    """Restate a direction against the opposite entity order."""
    return _FLIP.get(direction, direction)


def chunk_chapters(chapters: list[dict], size: int) -> list[dict]:
    """Split ordered chapters into paragraph-aligned chunks under ``size`` chars.

    Packs whole paragraphs (split on ``\\n\\n``) into a chunk until the next one
    would overflow ``size``, then starts a new chunk. Never splits a paragraph.
    Chunk ids are ``{chapter_id}:{i}`` so a vote traces back to its chapter.

    A chapter with no ``\\n\\n`` becomes one chunk whatever ``size`` is (STU-609): a
    stale ``epub_data.json`` predating STU-523 holds zero paragraph marks, so
    ``size`` degenerates to a no-op. Warn per chunk over ``size * _OVERSIZE_FACTOR``
    so the operator re-extracts instead of silently buying a worse discovery stage.
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
            if len(text) > size * _OVERSIZE_FACTOR:
                print(
                    f"[WARN] chunk {chapter['id']}:{i} is {len(text)} chars "
                    f"(target {size}) — chapter has no paragraph break to split on; "
                    f"re-extract if epub_data.json predates STU-523",
                    file=sys.stderr,
                )
            out.append({
                "id": f"{chapter['id']}:{i}",
                "chapter_id": chapter["id"],
                "title": chapter["title"],
                "text": text,
            })
    return out


def build_roster(entities: list[dict]) -> tuple[set[str], dict[str, str], list[str]]:
    """Build the PERSON roster the discovery prompt reads.

    Only interpersonal relations are discovered, so only PERSON entities enter the
    roster. Returns ``(canonical_names, alias_to_canonical, prompt_lines)``:
    ``alias_to_canonical`` maps every surface form (and the canonical name itself)
    back to the canonical name so a reply naming a known alias resolves; each
    ``prompt_line`` is ``"Name (also called: a, b)"`` or bare ``"Name"``.
    """
    names: set[str] = set()
    alias_to_canonical: dict[str, str] = {}
    lines: list[str] = []
    for entity in entities:
        if entity.get("entity_type") != "PERSON":
            continue
        canonical = entity["canonical_name"]
        names.add(canonical)
        alias_to_canonical[canonical] = canonical
        extra = [a for a in entity.get("aliases") or [] if a and a != canonical]
        for alias in extra:
            alias_to_canonical[alias] = canonical
        line = canonical
        if extra:
            line += f" (also called: {', '.join(extra)})"
        lines.append(line)
    return names, alias_to_canonical, lines


def canonicalize_relations(raw: object, alias_to_canonical: dict[str, str]) -> list[dict]:
    """Rewrite each relation's entity names through the alias→canonical map.

    A name the model returned as a known surface form becomes its canonical name;
    an unknown name is left untouched (``valid_relations`` drops it against the
    roster). Non-dict / non-string entries pass through for ``valid_relations`` to
    reject with a reason.
    """
    if not isinstance(raw, list):
        return raw  # type: ignore[return-value]
    out: list[dict] = []
    for rel in raw:
        if not isinstance(rel, dict):
            out.append(rel)
            continue
        resolved = dict(rel)
        for key in ("entity_a", "entity_b"):
            name = rel.get(key)
            if isinstance(name, str):
                resolved[key] = alias_to_canonical.get(name.strip(), name.strip())
        out.append(resolved)
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


def fold_chunk_result(
    raw: object,
    alias_to_canonical: dict[str, str],
    roster_names: set[str],
    allowed_types: Iterable[str],
) -> list[dict] | None:
    """Canonicalize + validate a chunk's raw relations, or ``None`` on failure.

    ``None`` in (a subprocess timeout / missing CLI / unparseable output) yields
    ``None`` out — the caller must NOT cache it, so a re-run retries the chunk
    instead of replaying an empty vote read as a genuine 0 (STU-562 shape). A
    successful call with no relations returns ``[]``, which IS cached.
    """
    if raw is None:
        return None
    resolved = canonicalize_relations(raw, alias_to_canonical)
    kept, _ = valid_relations(resolved, roster_names, allowed_types)
    return kept


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


def load_votes_cache(
    path: Path | str, roster_lines: list[str], prompt_key: str
) -> dict[str, list[dict]]:
    """Cached per-chunk votes for exactly this roster and this prompt, or empty.

    Keyed on the two inputs the model actually reads, not the chunk id alone:
    - ``roster_lines`` — an alias merge changes the roster without changing chunk
      text (same ids), and a vote made for a different roster must not be replayed
      (STU-529/539 pattern — ``roster.load_cache`` does the same for whole-roster
      verdicts).
    - ``prompt_key`` — a fingerprint of the discovery prompt and type vocabulary, so
      editing the agent prompt re-runs every chunk instead of silently replaying
      votes the old prompt produced (STU-560: a cache is keyed on the config that
      produced it). This is what makes prompt iteration on a chapter subset honest.

    Either mismatch ⇒ every chunk re-runs.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("roster") != roster_lines or data.get("prompt") != prompt_key:
        return {}
    votes = data.get("votes")
    return votes if isinstance(votes, dict) else {}


def save_votes_cache(
    path: Path | str, roster_lines: list[str], prompt_key: str, votes: dict[str, list[dict]]
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"roster": roster_lines, "prompt": prompt_key, "votes": votes},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
