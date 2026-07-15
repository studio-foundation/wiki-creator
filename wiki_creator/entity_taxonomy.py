"""Single authority for the entity-type taxonomy (STU-505).

`base.yaml#entity_types` declares every type's NER labels and export routing;
this module reads them so no Python table restates the vocabulary. Adding a type
is a `base.yaml` edit — nothing here enumerates the types.
"""
from __future__ import annotations

from wiki_creator.page_templates import load_base_template


def _types(base: dict | None = None) -> dict:
    raw = base if base is not None else load_base_template()
    return raw.get("entity_types") or {}


def _export(etype: str, base: dict | None = None) -> dict:
    return (_types(base).get(etype) or {}).get("export") or {}


def declared_types(base: dict | None = None) -> tuple[str, ...]:
    return tuple(_types(base).keys())


def ner_label_map(base: dict | None = None) -> dict[str, str]:
    """{NER label: entity_type} — the union of every type's ``ner_labels``."""
    out: dict[str, str] = {}
    for etype, spec in _types(base).items():
        for label in (spec or {}).get("ner_labels") or []:
            out[label] = etype
    return out


def ner_types(base: dict | None = None) -> tuple[str, ...]:
    """Types produced directly by the NER model (those with ``ner_labels``), in
    declaration order. These get a per-type ``*_full.json`` mention registry."""
    return tuple(t for t, spec in _types(base).items() if (spec or {}).get("ner_labels"))


def resolution_types(base: dict | None = None) -> tuple[str, ...]:
    """Types that flow through extraction/resolution: every NER type plus OTHER
    (the untyped fallback bucket). Generation-only pseudo-types (SYNOPSIS,
    COLLATION) are excluded."""
    types = _types(base)
    out = list(ner_types(base))
    if "OTHER" in types and "OTHER" not in out:
        out.append("OTHER")
    return tuple(out)


def subdir(etype: str, base: dict | None = None) -> str:
    return _export(etype, base).get("subdir") or "characters"


def subdirs(base: dict | None = None) -> tuple[str, ...]:
    seen: list[str] = []
    for etype in _types(base):
        s = _export(etype, base).get("subdir")
        if s and s not in seen:
            seen.append(s)
    return tuple(seen)


def full_registry_files(base: dict | None = None) -> tuple[tuple[str, str, str], ...]:
    """``(entity_type, filename, json_key)`` for each NER type's ``*_full.json``."""
    out = []
    for etype in ner_types(base):
        key = _export(etype, base).get("full_key")
        if key:
            out.append((etype, f"{key}_full.json", f"{key}_full"))
    return tuple(out)


def infobox_template_name(etype: str, base: dict | None = None) -> str | None:
    return _export(etype, base).get("infobox_template")


def infobox_source(etype: str, base: dict | None = None) -> str | None:
    return _export(etype, base).get("infobox_source")


def category_key(etype: str, base: dict | None = None) -> str | None:
    return _export(etype, base).get("category_key")


def category_default(etype: str, base: dict | None = None) -> str | None:
    return _export(etype, base).get("category_default")


def tome_label_key(etype: str, base: dict | None = None) -> str | None:
    return _export(etype, base).get("tome_label_key")


def exposes_importance_categories(etype: str, base: dict | None = None) -> bool:
    return bool(_export(etype, base).get("importance_categories"))
