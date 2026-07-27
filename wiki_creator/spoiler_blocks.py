"""Per-chapter spoiler rendering for exported wikitext (STU-492).

Pure wikitext transforms used by wiki-export: wrap chapter-gated sections in
native MediaWiki ``mw-collapsible`` blocks, and inject a deterministic dated
relationship index. No LLM, no I/O.
"""

from __future__ import annotations

import re

from wiki_creator.infobox_relationships import bucket_for_type
from wiki_creator.page_templates import (
    canonical_relationship,
    chrome_label,
    relationship_label,
    slot_label,
)
from wiki_creator.relationship_types import usable_relationship_type

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


def _collapsible(inner: str, expandtext: str, collapsetext: str) -> str:
    """A collapsed ``mw-collapsible`` div wrapping ``inner`` — the one div literal
    the chapter axis, the relation axis and the tome axis (STU-668) all share."""
    return (
        f'<div class="mw-collapsible mw-collapsed" '
        f'data-expandtext="{expandtext}" data-collapsetext="{collapsetext}">\n{inner}\n</div>\n'
    )


def tome_collapsible_section(heading: str, body: str, expandtext: str, collapsetext: str) -> str:
    """One ``== heading ==`` section collapsed behind an mw-collapsible div — the
    tome axis of STU-232 (``wrap_collapsible`` is the chapter axis).

    A series character page (STU-668) stacks one of these per tome. Every tome
    collapses by default, so spoiler safety rides entirely on the reader expanding
    the tomes they have read — the coarse per-tome export gate is given up on
    purpose. The latest-wins Status scalar lives in the (separately gated) infobox.
    """
    return _collapsible(f"== {heading} ==\n\n{body.strip()}", expandtext, collapsetext)


def wrap_collapsible(body: str, content_units: list[dict], collapse_after: int, lang: str = "fr") -> str:
    """Wrap each section revealed after ``collapse_after`` in an mw-collapsible div.

    Matching is by normalized heading title (via ``slot_label``), so it is robust
    to LLM heading drift and to a leading Infobox block. Sections with no matching
    unit, a ``None`` chapter, or a chapter ``<= collapse_after`` are left untouched.
    """
    chapter_by_title = {
        _norm(slot_label(u["section"], lang)): u.get("revealed_at_chapter")
        for u in content_units
    }
    blocks = _split_sections(body)
    out = [blocks[0]]
    for block in blocks[1:]:
        heading = _heading_of(block)
        chapter = chapter_by_title.get(_norm(heading)) if heading else None
        if chapter is not None and chapter > collapse_after:
            expand = chrome_label("reveal", lang).format(chapter=chapter)
            out.append(_collapsible(block, expand, chrome_label("collapse", lang)))
        else:
            out.append(block)
    return "".join(out)


_SPOILER_INFOBOX_TOKENS = ("status", "death")


def gate_infobox_spoilers(fields: dict, lang: str = "fr") -> dict:
    """Collapse the spoiler-bearing infobox values behind an inline mw-collapsible.

    ``status`` and ``death`` (STU-488/STU-552) are the only infobox rows that leak
    an end-of-tome fact — that a character dies, and by whose hand. This is the
    Fandom convention for a status row: the value collapses, the label stays.

    No reveal chapter is computed. A whole-tome status verdict has no sound
    intra-tome chapter — STU-488 measured deriving one from the quoting snippet
    3/4 wrong — so the rows are gated unconditionally whenever spoiler mode is on,
    treated as revealed at the end of the tome. An ``unknown`` status is not a
    spoiler and is left open. Only PERSON pages carry these tokens.
    """
    gated = dict(fields)
    unknown = chrome_label("status_unknown", lang)
    expand = chrome_label("reveal_spoiler", lang)
    collapse = chrome_label("collapse", lang)
    for token in _SPOILER_INFOBOX_TOKENS:
        value = gated.get(token)
        if not value or (token == "status" and value == unknown):
            continue
        gated[token] = (
            f'<span class="mw-collapsible mw-collapsed" '
            f'data-expandtext="{expand}" data-collapsetext="{collapse}">{value}</span>'
        )
    return gated


def citation_ref(book_title: str, chapter: int, lang: str = "fr") -> str:
    """MediaWiki footnote (STU-656) citing the book and the chapter a fact is
    grounded in — ``<ref>{book_title}, {chapter}</ref>``. The chapter comes from
    the unit's own provenance, so it invents no page/line number; the localized
    "chapter N" label is ``chrome.chapter_tag``."""
    where = chrome_label("chapter_tag", lang).format(chapter=chapter)
    return f"<ref>{book_title}, {where}</ref>"


def relationship_index_lines(
    entity: dict,
    lang: str = "fr",
    book_config: dict | None = None,
    book_title: str | None = None,
) -> list[str]:
    """Dated index line per typed relationship, most-recent-reveal first.

    Surfaces entity names + the localized relationship type + chapter numbers only.
    The English evolution/key_moments fields are never surfaced. The classifier emits
    canonical tokens (STU-477); a token is rendered through its ``lang`` label, and a
    French string from a pre-STU-477 artifact resolves via the enum's ``legacy`` map.
    ``book_config`` carries the types only this novel declares (STU-472) — their name
    is already the reader's term, so they render as written.

    When ``book_title`` is given, each line carries a ``<ref>`` citation (STU-656)
    grounded in the relation's first-reveal chapter — the deterministic per-line
    provenance the ``<references/>`` back-matter collects into footnotes.
    """
    own = {entity.get("canonical_name")} | set(entity.get("aliases") or [])
    rows = []
    for rel in entity.get("relationships") or []:
        rtype = usable_relationship_type(rel.get("relationship_type"))
        if not rtype:
            continue
        token = canonical_relationship(rtype, book_config=book_config)
        # STU-664: the dated index scopes to the same bonds the infobox buckets do
        # — Family/Romance/Friends/Enemies — instead of dumping every typed pair.
        # A weak (acquaintance) or unbucketed book-specific type stays in the prose
        # only, so the index consolidates rather than duplicating what the infobox
        # already lists.
        if not bucket_for_type(token):
            continue
        rtype = relationship_label(token, lang, book_config=book_config) if token else rtype
        chapters = [c for c in (rel.get("chapters") or []) if isinstance(c, int)]
        if not chapters:
            continue
        other = rel["entity_b"] if rel.get("entity_a") in own else rel["entity_a"]
        lo, hi = min(chapters), max(chapters)
        span = f"ch.{lo}" if lo == hi else f"ch.{lo}→ch.{hi}"
        line = f"* [[{other}]] — {rtype} ({span})"
        if book_title:
            line += citation_ref(book_title, lo, lang)
        rows.append((lo, line))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [line for _, line in rows]


def _relations_title(lang: str) -> str:
    return _norm(slot_label("relationships", lang))


def inject_relationship_index(body: str, lines: list[str], lang: str = "fr") -> str:
    """Append a localized ''Evolution'' index sub-block at the end of the Relations section."""
    if not lines:
        return body
    relations_title = _relations_title(lang)
    blocks = _split_sections(body)
    for i, block in enumerate(blocks[1:], start=1):
        heading = _heading_of(block)
        if heading and _norm(heading) == relations_title:
            sub = f"''{chrome_label('evolution', lang)}''\n" + "\n".join(lines)
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


def wrap_relation_collapsibles(body: str, relation_units: list[dict], collapse_after: int, lang: str = "fr") -> str:
    """Wrap each ``=== [[Name]] ===`` subsection of the Relations section whose
    relation is revealed after ``collapse_after`` in an mw-collapsible div.

    Matching is by the normalized name inside ``[[ ]]`` against ``relation_units``.
    Subsections with no match, a ``None`` chapter, or a chapter ``<= collapse_after``
    are left untouched — same leave-open default as ``wrap_collapsible``.
    """
    relations_title = _relations_title(lang)
    chapter_by_name = {_norm(u["name"]): u.get("revealed_at_chapter") for u in relation_units}
    blocks = _split_sections(body)
    out = [blocks[0]]
    for block in blocks[1:]:
        heading = _heading_of(block)
        if not heading or _norm(heading) != relations_title:
            out.append(block)
            continue
        subs = _split_subsections(block)
        wrapped = [subs[0]]
        for sub in subs[1:]:
            name = _subheading_name(sub)
            chapter = chapter_by_name.get(_norm(name)) if name else None
            if chapter is not None and chapter > collapse_after:
                expand = chrome_label("reveal", lang).format(chapter=chapter)
                wrapped.append(_collapsible(sub.rstrip(), expand, chrome_label("collapse", lang)))
            else:
                wrapped.append(sub)
        out.append("".join(wrapped))
    return "".join(out)
