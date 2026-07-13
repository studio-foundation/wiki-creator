"""Event Layer (SP0): structure existing chapter summaries + relationship
key-moments into per-chapter events. Deterministic, zero LLM. Mirrors the
relationship_fold.py pure-module pattern.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wiki_creator.registry import Registry

_CHAPTER_RE = re.compile(r"^\s*(?:chapter\s+|c\.?h?\.?\s*)0*(\d+)", re.IGNORECASE)


def _parse_chapter(text: str) -> int | None:
    """Extract the leading chapter number from a beat string or summary key."""
    if not text:
        return None
    m = _CHAPTER_RE.match(text)
    return int(m.group(1)) if m else None


def _resolve(name: str, registry: "Registry | None") -> str:
    """Canonical name for a surface via the registry, or the input unchanged."""
    if registry is None:
        return name
    record = registry.lookup(name)
    return record.canonical_name if record is not None else name


def _names_in(text: str, registry: "Registry | None", entity_type: str) -> list[str]:
    """Canonical names of the given `entity_type` whose surface appears as a whole word in `text`.

    Returns empty list when no registry.
    """
    if registry is None or not text:
        return []
    low = text.casefold()
    found: set[str] = set()
    for record in registry.entities:
        if record.entity_type != entity_type:
            continue
        for alias in record.aliases:
            if re.search(rf"\b{re.escape(alias.casefold())}\b", low):
                found.add(record.canonical_name)
                break
    return sorted(found)


def _has_action_cue(description: str, action_cues: list[str]) -> bool:
    """Check if description contains a whole-word match of any action cue (case-insensitive)."""
    low = description.casefold()
    return any(re.search(rf"\b{re.escape(c.casefold())}\b", low) for c in action_cues)


def _salience(description: str, chapter: int, total_chapters: int,
              action_cues: list[str]) -> float:
    """Score a beat by action-cue presence and chapter position (climax bias).

    Returns a score in [0.0, 1.0]:
    - 0.5 for an action-cue hit
    - Up to 0.5 scaled by chapter position (climax bias)
    """
    score = 0.5 if _has_action_cue(description, action_cues) else 0.0
    if total_chapters > 0 and chapter > 0:
        score += 0.5 * (chapter / total_chapters)
    return round(min(score, 1.0), 3)


def _strip_marker(text: str) -> str:
    """Remove a leading 'Ch12:' / 'Chapter 12:' marker, return the description."""
    return _CHAPTER_RE.sub("", text).lstrip(" :—-").strip()


def build_events(
    chapter_summaries: dict,
    relationships: list[dict],
    registry: "Registry | None",
    action_cues: list[str],
) -> list[dict]:
    """Assemble chapter-summary bullets + relationship key-moments into
    deduplicated, scored events, sorted by (chapter, event_id).
    """
    total_chapters = len(chapter_summaries) if chapter_summaries else 0

    # (chapter, normalized_description) -> aggregate
    agg: dict[tuple[int, str], dict] = {}

    def add_beat(chapter: int, raw: str, description: str, seed: list[str]) -> None:
        key = (chapter, description.casefold())
        entry = agg.get(key)
        if entry is None:
            entry = {
                "chapter": chapter,
                "description": description,
                "participants": set(),
                "places": set(),
                "source_bullets": [],
            }
            agg[key] = entry
        entry["source_bullets"].append(raw)
        for name in seed:
            entry["participants"].add(_resolve(name, registry))
        for name in _names_in(description, registry, "PERSON"):
            entry["participants"].add(name)
        for name in _names_in(description, registry, "PLACE"):
            entry["places"].add(name)

    # Source 1: relationship key_moments
    for rel in relationships:
        seed = [str(rel.get("entity_a", "")), str(rel.get("entity_b", ""))]
        seed = [s for s in seed if s]
        for km in rel.get("key_moments") or []:
            chapter = _parse_chapter(km)
            if chapter is None:
                continue
            add_beat(chapter, km, _strip_marker(km), seed)

    # Source 2: chapter summary bullets
    for key, summary in (chapter_summaries or {}).items():
        chapter = _parse_chapter(str(summary.get("chapter_title") or key)) \
            or _parse_chapter(str(summary.get("chapter_id") or ""))
        if chapter is None:
            continue
        for bullet in summary.get("summary_bullets") or []:
            add_beat(chapter, bullet, bullet.strip(), [])

    # Materialize, score, id, sort
    events: list[dict] = []
    for (chapter, _norm), entry in agg.items():
        description = entry["description"]
        events.append({
            "chapter": chapter,
            "description": description,
            "participants": sorted(entry["participants"]),
            "places": sorted(entry["places"]),
            "outcome": description if _has_action_cue(description, action_cues) else None,
            "salience": _salience(description, chapter, total_chapters, action_cues),
            "source_bullets": entry["source_bullets"],
        })

    events.sort(key=lambda e: (e["chapter"], e["description"].casefold()))
    by_chapter: dict[int, int] = {}
    for e in events:
        idx = by_chapter.get(e["chapter"], 0)
        e["event_id"] = f"e_ch{e['chapter']}_{idx}"
        by_chapter[e["chapter"]] = idx + 1
    return events
