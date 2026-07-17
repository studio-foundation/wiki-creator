"""Chapter provenance for generated content (STU-491).

Foundation of per-chapter gating: every content unit that reaches a wiki page
carries the chapter where its information is first revealed. Pure logic — the
bundle hands every chapter reference over as a chapter number already (event
``chapter``, relationship ``chapters``, ``context_chapters``,
``chapter_summary_context``); this just folds them to one
``revealed_at_chapter`` per unit.
"""

from __future__ import annotations

from wiki_creator.relationship_types import usable_relationship_type


def _min_chapter(numbers) -> int | None:
    nums = [n for n in numbers if isinstance(n, int)]
    return min(nums) if nums else None


def relation_revealed_at(rel: dict) -> int | None:
    """First chapter a relationship appears in (min over its ``chapters``)."""
    return _min_chapter(rel.get("chapters") or [])


def section_revealed_at(section: str, entity: dict) -> int | None:
    """Minimal chapter of the bundle data scoped to a rendered section.

    ``None`` when the section has no chapter-bearing source (e.g. a prose
    section for an entity with no context) — the caller leaves it ungated.
    """
    if section == "relationships":
        rels = entity.get("relationships") or []
        return _min_chapter(c for r in rels for c in (r.get("chapters") or []))
    if section == "narrative_role":
        return _min_chapter(e.get("chapter") for e in entity.get("entity_events") or [])
    if section == "backstory":
        return _min_chapter(
            s.get("revealed_at_chapter")
            for s in entity.get("chapter_summary_context") or []
            if s.get("temporal_context") == "flashback"
        )
    numbers = list(entity.get("context_chapters") or [])
    numbers += [s.get("revealed_at_chapter") for s in entity.get("chapter_summary_context") or []]
    return _min_chapter(numbers)


def content_units(sections, entity: dict) -> list[dict]:
    """One ``{section, revealed_at_chapter}`` provenance row per rendered section.

    Infobox and references carry no narrative info to gate, so they are skipped.
    """
    return [
        {"section": s, "revealed_at_chapter": section_revealed_at(s, entity)}
        for s in sections
        if s not in ("infobox", "references")
    ]


def relation_units(entity: dict) -> list[dict]:
    """One ``{name, revealed_at_chapter}`` row per typed relationship.

    ``name`` = the pair's other entity; ``revealed_at_chapter`` = ``max`` over
    the relation's chapters (last chapter of the arc — the gating key). Typed
    relationships with at least one resolvable chapter only; empty when none.
    """
    own = {entity.get("canonical_name")} | set(entity.get("aliases") or [])
    rows = []
    for rel in entity.get("relationships") or []:
        if not usable_relationship_type(rel.get("relationship_type")):
            continue
        chapters = [n for n in (rel.get("chapters") or []) if isinstance(n, int)]
        if not chapters:
            continue
        other = rel["entity_b"] if rel.get("entity_a") in own else rel["entity_a"]
        rows.append({"name": other, "revealed_at_chapter": max(chapters)})
    return rows
