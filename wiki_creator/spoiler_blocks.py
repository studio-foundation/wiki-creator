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
                f'data-collapsetext="Masquer">\n{block}\n</div>\n'
            )
        else:
            out.append(block)
    return "".join(out)


def relationship_index_lines(entity: dict) -> list[str]:
    """Dated index line per typed relationship, most-recent-reveal first.

    Language-neutral: entity names + the French relationship_type enum + chapter
    numbers only. The English evolution/key_moments fields are never surfaced.
    """
    own = {entity.get("canonical_name")} | set(entity.get("aliases") or [])
    rows = []
    for rel in entity.get("relationships") or []:
        rtype = rel.get("relationship_type")
        if not rtype:
            continue
        chapters = [c for c in (chapter_number(k) for k in rel.get("chapters") or []) if c is not None]
        if not chapters:
            continue
        other = rel["entity_b"] if rel.get("entity_a") in own else rel["entity_a"]
        lo, hi = min(chapters), max(chapters)
        span = f"ch.{lo}" if lo == hi else f"ch.{lo}→ch.{hi}"
        rows.append((lo, f"* [[{other}]] — {rtype} ({span})"))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [line for _, line in rows]


_RELATIONS_TITLE = _norm(SECTION_TITLES["relationships"])


def inject_relationship_index(body: str, lines: list[str]) -> str:
    """Append an ''Évolution :'' index sub-block at the end of the Relations section."""
    if not lines:
        return body
    blocks = _split_sections(body)
    for i, block in enumerate(blocks[1:], start=1):
        heading = _heading_of(block)
        if heading and _norm(heading) == _RELATIONS_TITLE:
            sub = "''Évolution :''\n" + "\n".join(lines)
            blocks[i] = f"{block.rstrip()}\n\n{sub}\n"
            return "".join(blocks)
    return body


def spoiler_collapse_after(book_cfg: dict) -> int | None:
    return ((book_cfg.get("generation") or {}).get("spoiler") or {}).get("collapse_after_chapter")


def per_relation_prose_enabled(book_cfg: dict) -> bool:
    return bool(
        ((book_cfg.get("generation") or {}).get("relations") or {}).get("per_relation_prose")
    )


_SUBHEADING_RE = re.compile(r"(?m)^(===\s+.+?\s+===) *$")
_NAME_RE = re.compile(r"\[\[([^\]|]+)")


def _split_subsections(section_body: str) -> list[str]:
    """Split a section's wikitext into [pre, '=== H ===...', ...] sub-blocks."""
    parts = _SUBHEADING_RE.split(section_body)
    blocks = [parts[0]]
    for heading, content in zip(parts[1::2], parts[2::2]):
        blocks.append(f"{heading.strip()}{content}")
    return blocks


def _subheading_name(block: str) -> str | None:
    m = _SUBHEADING_RE.match(block.strip())
    if not m:
        return None
    n = _NAME_RE.search(m.group(1))
    return n.group(1).strip() if n else None


def wrap_relation_collapsibles(body: str, relation_units: list[dict], collapse_after: int) -> str:
    """Wrap each ``=== [[Name]] ===`` subsection of the Relations section whose
    relation is revealed after ``collapse_after`` in an mw-collapsible div.

    Matching is by the normalized name inside ``[[ ]]`` against ``relation_units``.
    Subsections with no match, a ``None`` chapter, or a chapter ``<= collapse_after``
    are left untouched — same leave-open default as ``wrap_collapsible``.
    """
    chapter_by_name = {_norm(u["name"]): u.get("revealed_at_chapter") for u in relation_units}
    blocks = _split_sections(body)
    out = [blocks[0]]
    for block in blocks[1:]:
        heading = _heading_of(block)
        if not heading or _norm(heading) != _RELATIONS_TITLE:
            out.append(block)
            continue
        subs = _split_subsections(block)
        wrapped = [subs[0]]
        for sub in subs[1:]:
            name = _subheading_name(sub)
            chapter = chapter_by_name.get(_norm(name)) if name else None
            if chapter is not None and chapter > collapse_after:
                wrapped.append(
                    f'<div class="mw-collapsible mw-collapsed" '
                    f'data-expandtext="Chapitre {chapter} — révéler" '
                    f'data-collapsetext="Masquer">\n{sub.rstrip()}\n</div>\n'
                )
            else:
                wrapped.append(sub)
        out.append("".join(wrapped))
    return "".join(out)
