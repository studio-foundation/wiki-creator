"""Per-chapter spoiler rendering for exported wikitext (STU-492).

Pure wikitext transforms used by wiki-export: wrap chapter-gated sections in
native MediaWiki ``mw-collapsible`` blocks, and inject a deterministic dated
relationship index. No LLM, no I/O.
"""

from __future__ import annotations

import re

from wiki_creator.chapters import chapter_number
from wiki_creator.sections import SECTION_TITLES

_HEADING_RE = re.compile(r"(?m)^(==\s+.+?\s+==) *$")


def _norm(title: str) -> str:
    return title.strip().strip("=").strip().lower()


def _split_sections(body: str) -> list[str]:
    """Split wikitext into [pre, '== H ==\\n\\nbody', ...] blocks."""
    parts = _HEADING_RE.split(body)
    blocks = [parts[0]]
    for heading, content in zip(parts[1::2], parts[2::2]):
        blocks.append(f"{heading.strip()}{content}")
    return blocks


def _heading_of(block: str) -> str | None:
    m = _HEADING_RE.match(block.strip())
    return m.group(1) if m else None


def wrap_collapsible(body: str, content_units: list[dict], collapse_after: int) -> str:
    """Wrap each section revealed after ``collapse_after`` in an mw-collapsible div.

    Matching is by normalized heading title (via SECTION_TITLES), so it is robust
    to LLM heading drift and to a leading Infobox block. Sections with no matching
    unit, a ``None`` chapter, or a chapter ``<= collapse_after`` are left untouched.
    """
    chapter_by_title = {
        _norm(SECTION_TITLES.get(u["section"], u["section"])): u.get("revealed_at_chapter")
        for u in content_units
    }
    blocks = _split_sections(body)
    out = [blocks[0]]
    for block in blocks[1:]:
        heading = _heading_of(block)
        chapter = chapter_by_title.get(_norm(heading)) if heading else None
        if chapter is not None and chapter > collapse_after:
            out.append(
                f'<div class="mw-collapsible mw-collapsed" '
                f'data-expandtext="Chapitre {chapter} — révéler" '
                f'data-collapsetext="Masquer">\n{block}\n</div>'
            )
        else:
            out.append(block)
    return "".join(out)
