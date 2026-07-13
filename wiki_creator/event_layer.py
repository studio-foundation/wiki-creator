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


# STU-483: position was the dominant (and often only live) term, crushing
# early-book setup beats regardless of narrative weight. Position is now a
# minor tie-breaker; participant importance carries the most weight, with the
# turning-point cue (action_cues now spans setup/reveal/resolution phrasing,
# not just resolution) close behind. Weights sum to 1.0 = the score cap.
_CUE_WEIGHT = 0.35
_PARTICIPANT_WEIGHT = 0.45
_POSITION_WEIGHT = 0.20


def _participant_importance_score(
    participants: list[str], participant_importance: dict[str, float]
) -> float:
    """Average importance weight of an event's participants.

    0.0 when there are no participants or no importance signal (registry-less
    runs degrade to the cue+position terms only).
    """
    if not participants or not participant_importance:
        return 0.0
    scores = [participant_importance.get(p, 0.0) for p in participants]
    return sum(scores) / len(scores)


def _salience(
    description: str,
    chapter: int,
    total_chapters: int,
    action_cues: list[str],
    participants: list[str] | None = None,
    participant_importance: dict[str, float] | None = None,
) -> float:
    """Score a beat by narrative importance, not just where it sits in the book.

    Returns a score in [0.0, 1.0], the sum of three terms:
    - up to `_CUE_WEIGHT` for a turning-point cue hit (setup/reveal/resolution
      phrasing via `action_cues`)
    - up to `_PARTICIPANT_WEIGHT` scaled by the average importance of the
      event's participants
    - up to `_POSITION_WEIGHT` scaled by chapter position (minor climax bias)
    """
    score = _CUE_WEIGHT if _has_action_cue(description, action_cues) else 0.0
    score += _PARTICIPANT_WEIGHT * _participant_importance_score(
        participants or [], participant_importance or {}
    )
    if total_chapters > 0 and chapter > 0:
        score += _POSITION_WEIGHT * (chapter / total_chapters)
    return round(min(score, 1.0), 3)


def _strip_marker(text: str) -> str:
    """Remove a leading 'Ch12:' / 'Chapter 12:' marker, return the description."""
    return _CHAPTER_RE.sub("", text).lstrip(" :—-").strip()


def build_events(
    chapter_summaries: dict,
    relationships: list[dict],
    registry: "Registry | None",
    action_cues: list[str],
    participant_importance: dict[str, float] | None = None,
) -> list[dict]:
    """Assemble chapter-summary bullets + relationship key-moments into
    deduplicated, scored events, sorted by (chapter, description) — with
    event_id assigned per chapter in that resulting sort order.

    `participant_importance` maps canonical entity name -> importance weight
    (e.g. derived from entity-classification tiers) and feeds the salience
    formula (STU-483). Omitted/empty degrades to a cue+position-only score.
    """
    chapter_summaries = chapter_summaries or {}
    relationships = relationships or []
    participant_importance = participant_importance or {}
    total_chapters = len(chapter_summaries)

    # (chapter, normalized_description) -> aggregate
    agg: dict[tuple[int, str], dict] = {}
    # Participants seeded by relationship key-moments, per chapter — the
    # "source pair" a same-chapter, participant-less summary beat can inherit
    # from (STU-483: orphaned high-salience climax events).
    chapter_rel_participants: dict[int, set[str]] = {}

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
        resolved_seed = [_resolve(s, registry) for s in seed]
        for km in rel.get("key_moments") or []:
            chapter = _parse_chapter(km)
            if chapter is None:
                continue
            add_beat(chapter, km, _strip_marker(km), seed)
            chapter_rel_participants.setdefault(chapter, set()).update(resolved_seed)

    # Source 2: chapter summary bullets
    for key, summary in chapter_summaries.items():
        chapter = _parse_chapter(str(summary.get("chapter_title") or key))
        if chapter is None:
            chapter = _parse_chapter(str(summary.get("chapter_id") or ""))
        if chapter is None:
            continue
        for bullet in summary.get("summary_bullets") or []:
            add_beat(chapter, bullet, bullet.strip(), [])

    # Materialize, score, id, sort
    events: list[dict] = []
    for (chapter, _norm), entry in agg.items():
        description = entry["description"]
        participants = entry["participants"]
        if not participants and chapter in chapter_rel_participants:
            participants = chapter_rel_participants[chapter]
        participants = sorted(participants)
        events.append({
            "chapter": chapter,
            "description": description,
            "participants": participants,
            "places": sorted(entry["places"]),
            "outcome": description if _has_action_cue(description, action_cues) else None,
            "salience": _salience(
                description, chapter, total_chapters, action_cues,
                participants, participant_importance,
            ),
            "source_bullets": entry["source_bullets"],
        })

    events.sort(key=lambda e: (e["chapter"], e["description"].casefold()))
    by_chapter: dict[int, int] = {}
    for e in events:
        idx = by_chapter.get(e["chapter"], 0)
        e["event_id"] = f"e_ch{e['chapter']}_{idx}"
        by_chapter[e["chapter"]] = idx + 1
    return events
