"""Fold co-occurrence relationship edges onto canonical entities (STU-435).

The co-occurrence graph is built at the *mention* level (surface forms, before
alias-resolution), so a single entity's edges are split across its surface forms
(``Chaol Westfall`` vs ``Captain Westfall``). This module folds those nodes onto
their canonical identity via ``registry.alias_table()`` (surface -> entity_id),
sums ``cooccurrence_count`` and unions ``chapters`` / ``sample_contexts`` so that
each canonical pair is classified exactly once.

Pure function; the only dependency is the loaded :class:`Registry`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from wiki_creator.registry import Registry

# Match the per-edge sample cap used by relationship_extraction._sample_distributed.
_MAX_SAMPLE_CONTEXTS = 12


def fold_relationships(relationships: list[dict], registry: "Registry") -> list[dict]:
    """Collapse surface-form edges onto canonical entities.

    Each surface name in ``entity_a`` / ``entity_b`` is resolved through the
    registry's alias table to its canonical name. Edges that resolve to the same
    unordered canonical pair are merged: counts summed, chapters and
    sample_contexts unioned. Names absent from the alias table pass through
    unchanged (graceful degradation — the edge is kept, just not folded).

    ``relationship_type`` / ``direction`` / ``evolution`` are reset to ``None``:
    the folded edge is a fresh, single canonical pair to be classified once.
    """
    alias_table = registry.alias_table()
    id_to_canonical = {rec.entity_id: rec.canonical_name for rec in registry.entities}

    def canonical(name: str) -> str:
        entity_id = alias_table.get(name)
        if entity_id is None:
            return name
        return id_to_canonical.get(entity_id, name)

    aggregated: dict[tuple[str, str], dict] = {}
    for rel in relationships:
        a = canonical(str(rel.get("entity_a", "")))
        b = canonical(str(rel.get("entity_b", "")))
        if not a or not b or a == b:
            continue
        key: tuple[str, str] = (a, b) if a <= b else (b, a)
        base = aggregated.get(key)
        if base is None:
            base = {
                "entity_a": key[0],
                "entity_b": key[1],
                "cooccurrence_count": 0,
                "_chapters": set(),
                "_contexts": [],
                "relationship_type": None,
                "direction": None,
                "evolution": None,
            }
            aggregated[key] = base
        base["cooccurrence_count"] += int(rel.get("cooccurrence_count", 0) or 0)
        base["_chapters"].update(rel.get("chapters", []) or [])
        base["_contexts"].extend(rel.get("sample_contexts", []) or [])

    folded: list[dict] = []
    for base in aggregated.values():
        chapters = sorted(base.pop("_chapters"))
        contexts = _dedup(base.pop("_contexts"))[:_MAX_SAMPLE_CONTEXTS]
        base["chapters"] = chapters
        base["sample_contexts"] = contexts
        folded.append(base)

    folded.sort(key=lambda r: r["cooccurrence_count"], reverse=True)
    return folded


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
