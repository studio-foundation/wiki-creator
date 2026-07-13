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
