"""Deterministic first-mention wikilinking for narrative prose (STU-500).

The SP1 "Rôle dans le récit" writer names participating characters in plain
prose; this pass wraps the first *bare* mention of each known entity (one that
has its own wiki page) in a ``[[...]]`` wikilink, so the reader always reaches
a navigable link instead of a bare name. Pure, no LLM, no I/O.

Contract enforced: the first mention of a known named entity is a wikilink,
systematically. A name already wikilinked in the prose is left untouched (no
double-wrap, no second link).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_WIKILINK_RE = re.compile(r"\[\[[^\]]*\]\]")


def _link_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _WIKILINK_RE.finditer(text)]


def link_first_mentions(text: str, names: Iterable[str]) -> str:
    """Wikilink the first bare mention of each name in ``names``.

    Longest names first so ``Celaena Sardothien`` wins over a bare ``Celaena``.
    A name already wikilinked anywhere in ``text`` is skipped; a bare mention
    that falls inside an existing ``[[...]]`` never gets re-wrapped.
    """
    if not text or not names:
        return text
    ordered = sorted(
        {str(n).strip() for n in names if str(n).strip()}, key=len, reverse=True
    )
    for name in ordered:
        esc = re.escape(name)
        if re.search(rf"\[\[\s*{esc}\s*(?:\||\]\])", text):
            continue
        spans = _link_spans(text)
        for m in re.finditer(rf"\b{esc}\b", text):
            if any(ls <= m.start() < le for ls, le in spans):
                continue
            text = f"{text[:m.start()]}[[{name}]]{text[m.end():]}"
            break
    return text
