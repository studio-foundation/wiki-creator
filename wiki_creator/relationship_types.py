"""Renderer-facing normalization of a relationship's ``relationship_type`` (STU-501).

The relationship classifier emits ``relationship_type: null`` for pairs it can't
type, and some runs surface that JSON sentinel as the literal string ``"null"``
rather than a real ``None``. Reader-facing surfaces must never print that sentinel
— nor the internal co-occurrence metric name that used to fill the gap.

Uniform STU-501 decision: a relationship without a real, usable type is **omitted**
from every rendered surface (the dated index, per-relation prose, and the writer
prompt). No neutral placeholder, no metric label — the line simply does not appear.
"""

from __future__ import annotations

_UNTYPED_SENTINELS = frozenset({"", "null", "none"})


def usable_relationship_type(value: object) -> str | None:
    """The ``relationship_type`` to render, or ``None`` when missing/sentinel."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in _UNTYPED_SENTINELS:
        return None
    return text
