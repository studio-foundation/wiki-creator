"""Editorial register (STU-644): the voice and tone of generated prose, per book.

Orthogonal to editorial stance (STU-507, *who* narrates — in/out of the fiction)
and to grounding (*invent nothing*, unconditional — no register may relax it).
This axis is *form* only: it shapes word choice, rhythm and flavor, never what may
be claimed. A book that declares no register keeps the neutral encyclopedic voice
the pipeline has always used, so an unconfigured book's prompt is unchanged.
"""

from __future__ import annotations

DEFAULT_REGISTER = "Neutral, precise, factual."


def register_clause(book_cfg: dict) -> str:
    """The tone clause that follows ``Write in encyclopedic <language>.`` in every
    writer prompt — the book's declared ``generation.register`` or the neutral
    default. A present-but-empty or non-string value raises rather than degrading:
    a silently ignored register is the STU-470 shape."""
    raw = (book_cfg.get("generation") or {}).get("register")
    if raw is None:
        return DEFAULT_REGISTER
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("generation.register must be a non-empty string")
    return raw.strip()
