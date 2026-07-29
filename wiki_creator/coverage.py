"""Coverage / faithfulness harness (STU-723).

Pure logic over a run's already-persisted artifacts — no LLM, no network,
"disk is the bus" (STU-455). Reads ``chapters.json``, the ``*_full.json``
mention registries, ``entities_classified.json``, ``relationships_discovered.json``
and ``wiki_pages.json`` and produces three ledgers plus a drop log:

- **Ledger 1 — chapter coverage.** For each entity that reaches a page, the
  chapters it is mentioned in (source) vs the chapters actually represented in
  its page context. Flags an entity present in many chapters whose page is
  built from a small fraction of them (STU-711/713).
- **Ledger 2 — mention/alias coverage.** A high-frequency surface form that was
  extracted but never folded into any paged entity — a floating alias (STU-714),
  and the nickname that only ever appears inside quoted speech (STU-716).
- **Ledger 3 — relationship support.** Each relation that reaches an infobox
  slot must clear the co-occurrence gate (STU-715) and carry evidence (STU-700).

The harness never fails a run; the report is a dev tool (``make coverage``). The
*assertions* live in the test suite as thresholded invariants on the fixture.

``log_drop`` is the runtime half of the "No silent caps" norm: each existing
budget/cap site calls it the moment it drops content, so a live run's log names
what it lost. The report's drop log is recomputed from artifacts here, so it is
authoritative even when a run's stderr is gone.
"""
from __future__ import annotations

import re
import sys
from typing import IO, Iterable, Mapping

from wiki_creator.infobox_relationships import MIN_INFOBOX_COOCCURRENCE, bucket_for_type
from wiki_creator.page_templates import canonical_relationship
from wiki_creator.relationship_types import usable_relationship_type

# Book-level defaults, not per-book knobs: "how much of a character's presence must
# survive onto its page?" is a question about us, not about any one novel (CLAUDE.md
# "Config Is Read By People Who Know Books").

# A page built from fewer than half the chapters the entity appears in is a drop.
CHAPTER_COVERAGE_MIN_RATIO = 0.5
# Only meaningful once the entity spans enough chapters that losing most of them
# matters — a two-chapter figurant covered in one chapter is not a defect.
CHAPTER_COVERAGE_MIN_SOURCE = 4
# An extracted surface form seen this often that never links to a paged entity is a
# lost alias ("the Rabbit" ×22 clears this comfortably, STU-714).
FLOATING_MENTION_FLOOR = 5

# Dialogue delimiters only. Single quotes (straight or curly) double as apostrophes,
# so pairing them would read a contraction as reported speech — dropped on purpose.
_QUOTE_PAIRS = (('"', '"'), ("“", "”"), ("«", "»"))


def merge_registries(registries_by_type: Mapping[str, Mapping[str, dict]]) -> dict[str, dict]:
    """Flatten ``{entity_type: {source_id: entry}}`` into ``{source_id: entry}``.

    ``entry`` is the ``*_full.json`` mention record (``mentions_by_chapter``,
    ``raw_mentions``, ``mention_count``); its ``type`` is stamped from the file it
    came from when absent, so a later lookup by source_id needs no type table.
    """
    merged: dict[str, dict] = {}
    for etype, reg in registries_by_type.items():
        for sid, entry in reg.items():
            e = dict(entry)
            e.setdefault("type", etype)
            merged[sid] = e
    return merged


def _source_chapters(entity: dict, registries: Mapping[str, dict]) -> set[str]:
    chapters: set[str] = set()
    for sid in entity.get("source_ids", []):
        entry = registries.get(sid)
        if entry:
            chapters.update(entry.get("mentions_by_chapter", {}).keys())
    return chapters


def _is_paged(entity: dict, paged_titles: set[str] | None) -> bool:
    """An entity reaches a page unless it is classified ``ignored`` — or, when the
    caller passes the real set of rendered page titles, unless it is absent from it."""
    if paged_titles is not None:
        names = {entity.get("canonical_name", "")} | set(entity.get("aliases") or [])
        return bool(names & paged_titles)
    return entity.get("importance") != "ignored"


def chapter_coverage_ledger(
    entities: Iterable[dict],
    registries: Mapping[str, dict],
    page_chapters: Mapping[str, Iterable[str]] | None = None,
    paged_titles: set[str] | None = None,
    *,
    min_ratio: float = CHAPTER_COVERAGE_MIN_RATIO,
    min_source: int = CHAPTER_COVERAGE_MIN_SOURCE,
) -> list[dict]:
    """Ledger 1 — chapter coverage per paged entity.

    ``page_chapters`` maps a canonical name to the chapters actually represented
    in its page context (the batch ``context_by_chapter`` keys). When given, the
    ledger names the exact dropped chapters (STU-711); when absent it falls back
    to the ``chapters_present`` count the classifier recorded, so a count-only
    shortfall is still caught.
    """
    ledger: list[dict] = []
    for entity in entities:
        if not _is_paged(entity, paged_titles):
            continue
        name = entity.get("canonical_name", "")
        source = _source_chapters(entity, registries)
        source_count = len(source)
        represented: set[str] | None = None
        if page_chapters is not None and name in page_chapters:
            represented = set(page_chapters[name])
            page_count = len(represented)
        else:
            page_count = int(entity.get("chapters_present", 0) or 0)
        ratio = page_count / source_count if source_count else 1.0
        flagged = source_count >= min_source and ratio < min_ratio
        record = {
            "entity": name,
            "type": entity.get("type"),
            "importance": entity.get("importance"),
            "source_chapters": sorted(source),
            "source_chapter_count": source_count,
            "page_chapter_count": page_count,
            "coverage_ratio": round(ratio, 3),
            "flagged": flagged,
        }
        if represented is not None:
            record["dropped_chapters"] = sorted(source - represented)
        ledger.append(record)
    return ledger


def _quoted_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for open_q, close_q in _QUOTE_PAIRS:
        if open_q == close_q:
            # A straight quote pairs greedily: consecutive marks bound one span.
            positions = [m.start() for m in re.finditer(re.escape(open_q), text)]
            for i in range(0, len(positions) - 1, 2):
                spans.append((positions[i], positions[i + 1]))
        else:
            depth = 0
            start = -1
            for i, ch in enumerate(text):
                if ch == open_q:
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == close_q and depth > 0:
                    depth -= 1
                    if depth == 0:
                        spans.append((start, i))
    return spans


def _all_occurrences_quoted(surface: str, contexts: Iterable[str]) -> bool:
    """True iff every occurrence of ``surface`` across ``contexts`` sits inside a
    quoted region — the STU-716 signature of a name that only lives in reported
    speech. False when the surface never occurs (nothing to judge)."""
    saw_any = False
    for context in contexts:
        if not context:
            continue
        spans = _quoted_spans(context)
        for m in re.finditer(re.escape(surface), context):
            saw_any = True
            if not any(lo < m.start() < hi for lo, hi in spans):
                return False
    return saw_any


def mention_coverage_ledger(
    entities: Iterable[dict],
    registries: Mapping[str, dict],
    *,
    min_floating: int = FLOATING_MENTION_FLOOR,
) -> list[dict]:
    """Ledger 2 — floating high-frequency surface forms.

    An extracted ``*_full`` entry whose source_id is in no classified entity is a
    surface form that never linked (STU-714). Above ``min_floating`` mentions it
    is flagged; if every one of those mentions sits inside quoted speech it is the
    STU-716 phantom-in-dialogue case, marked so.
    """
    linked: set[str] = set()
    for entity in entities:
        linked.update(entity.get("source_ids", []))

    ledger: list[dict] = []
    for sid, entry in registries.items():
        if sid in linked:
            continue
        count = int(entry.get("mention_count", 0) or 0)
        if count < min_floating:
            continue
        contexts: list[str] = []
        for mentions in entry.get("mentions_by_chapter", {}).values():
            contexts.extend(mentions)
        surfaces = entry.get("raw_mentions") or []
        quoted_only = bool(surfaces) and all(
            _all_occurrences_quoted(surface, contexts) for surface in surfaces
        )
        ledger.append({
            "source_id": sid,
            "type": entry.get("type"),
            "surface_forms": surfaces,
            "mention_count": count,
            "chapters": sorted(entry.get("mentions_by_chapter", {}).keys()),
            "quoted_speech_only": quoted_only,
            "reason": "quoted_speech_only" if quoted_only else "floating_alias",
            "flagged": True,
        })
    ledger.sort(key=lambda r: (-r["mention_count"], r["source_id"]))
    return ledger


def _has_evidence(rel: dict) -> bool:
    return bool(
        rel.get("evidence")
        or rel.get("sample_contexts")
        or rel.get("key_moments")
        or rel.get("evolution")
    )


def relationship_support_ledger(
    relationships: Iterable[dict],
    *,
    min_cooccurrence: int = MIN_INFOBOX_COOCCURRENCE,
    book_config: dict | None = None,
) -> list[dict]:
    """Ledger 3 — support behind every relation that reaches an infobox slot.

    A relation whose canonical type maps to an infobox bucket (via the same
    ``bucket_for_type`` the renderer uses) must clear the co-occurrence gate
    (STU-715) and carry evidence (STU-700). Relations too weak or specific for a
    slot are skipped — they only ever surface, hedged, in the prose section.
    """
    ledger: list[dict] = []
    for rel in relationships:
        rtype = usable_relationship_type(rel.get("relationship_type"))
        bucket = bucket_for_type(canonical_relationship(rtype, book_config=book_config))
        if not bucket:
            continue
        support = int(rel.get("cooccurrence_count", 0) or 0)
        reasons: list[str] = []
        if support < min_cooccurrence:
            reasons.append("below_cooccurrence_gate")
        if not _has_evidence(rel):
            reasons.append("empty_evidence")
        ledger.append({
            "entity_a": rel.get("entity_a"),
            "entity_b": rel.get("entity_b"),
            "relationship_type": rel.get("relationship_type"),
            "bucket": bucket,
            "cooccurrence_count": support,
            "has_evidence": _has_evidence(rel),
            "reasons": reasons,
            "flagged": bool(reasons),
        })
    return ledger


def aggregate_drops(
    chapter_ledger: list[dict],
    mention_ledger: list[dict],
    relationship_ledger: list[dict],
) -> list[dict]:
    """Fold the three ledgers' flagged rows into one drop log — the single place
    "what did we lose, and where" is answerable for a run."""
    drops: list[dict] = []
    for r in chapter_ledger:
        if not r["flagged"]:
            continue
        dropped = r.get("dropped_chapters")
        count = len(dropped) if dropped is not None else r["source_chapter_count"] - r["page_chapter_count"]
        drops.append({
            "stage": "wiki-preparation.extract_context",
            "entity": r["entity"],
            "count": count,
            "detail": dropped,
            "reason": "chapters absent from page context",
        })
    for r in mention_ledger:
        drops.append({
            "stage": "entity-extraction/classification",
            "entity": ", ".join(r["surface_forms"]) or r["source_id"],
            "count": r["mention_count"],
            "detail": r["chapters"],
            "reason": r["reason"],
        })
    for r in relationship_ledger:
        if not r["flagged"]:
            continue
        drops.append({
            "stage": "relationship-discovery/infobox",
            "entity": f"{r['entity_a']} — {r['entity_b']}",
            "count": r["cooccurrence_count"],
            "detail": r["reasons"],
            "reason": "unsupported infobox relationship slot",
        })
    return drops


def build_coverage_report(
    entities: list[dict],
    registries: Mapping[str, dict],
    relationships: list[dict],
    *,
    page_chapters: Mapping[str, Iterable[str]] | None = None,
    paged_titles: set[str] | None = None,
    book_config: dict | None = None,
) -> dict:
    """Assemble the three ledgers, the drop log and a summary into one report."""
    chapter_ledger = chapter_coverage_ledger(
        entities, registries, page_chapters, paged_titles
    )
    mention_ledger = mention_coverage_ledger(entities, registries)
    relationship_ledger = relationship_support_ledger(
        relationships, book_config=book_config
    )
    drops = aggregate_drops(chapter_ledger, mention_ledger, relationship_ledger)
    return {
        "chapter_ledger": chapter_ledger,
        "mention_ledger": mention_ledger,
        "relationship_ledger": relationship_ledger,
        "drops": drops,
        "summary": {
            "entities_paged": len(chapter_ledger),
            "chapter_coverage_flags": sum(1 for r in chapter_ledger if r["flagged"]),
            "floating_mentions": len(mention_ledger),
            "relationship_slots": len(relationship_ledger),
            "relationship_flags": sum(1 for r in relationship_ledger if r["flagged"]),
            "total_drops": len(drops),
        },
    }


def log_drop(
    stage: str,
    entity: str,
    count: int,
    reason: str,
    *,
    stream: IO[str] | None = None,
) -> None:
    """Emit one structured drop line the moment a cap drops content — the runtime
    half of the "No silent caps" norm. A no-op on ``count <= 0``."""
    if count <= 0:
        return
    print(
        f"[DROP] stage={stage} entity={entity!r} count={count} reason={reason}",
        file=stream if stream is not None else sys.stderr,
    )
