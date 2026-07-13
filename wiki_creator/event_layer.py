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
