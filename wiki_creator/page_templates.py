"""Wiki page template schema: typed slots with provenance, resolved per
(entity_type, importance, book overrides). Pure data module — no pipeline
side effects. Consumed by generation (slices B-E)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

PROVENANCES = {"batch-bound", "extracted-fact", "llm-prose"}
OBLIGATIONS = {"MIN", "OPT"}
TIERS = ("figurant", "secondary", "principal")

DEFAULT_BASE_PATH = Path(__file__).resolve().parent / "templates" / "base.yaml"


def load_base_template(path: str | Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_BASE_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _iter_slots(raw: dict):
    for etype, groups in (raw.get("entity_types") or {}).items():
        for group in ("infobox", "sections"):
            for slot in groups.get(group) or []:
                yield etype, slot


def validate_template(raw: dict) -> None:
    for etype, slot in _iter_slots(raw):
        token = slot.get("token", "<missing>")
        prov = slot.get("provenance")
        if prov not in PROVENANCES:
            raise ValueError(f"{etype}.{token}: invalid provenance {prov!r}")
        obl = slot.get("obligation")
        if obl not in OBLIGATIONS:
            raise ValueError(f"{etype}.{token}: invalid obligation {obl!r}")
        tiers = slot.get("tiers")
        if tiers is not None and len(tiers) == 0:
            raise ValueError(f"{etype}.{token}: empty tiers list will never resolve")
        tiers = tiers or []
        if not set(tiers) <= set(TIERS):
            raise ValueError(f"{etype}.{token}: invalid tiers {tiers!r}")
        if obl == "MIN" and prov == "extracted-fact" and not slot.get("fallback"):
            raise ValueError(f"{etype}.{token}: MIN extracted-fact needs a fallback")


@dataclass(frozen=True)
class Slot:
    token: str
    group: str
    provenance: str
    obligation: str
    tiers: tuple[str, ...]
    fallback: str | None = None
    genre_gated: bool = False


@dataclass(frozen=True)
class ResolvedTemplate:
    entity_type: str
    importance: str
    slots: tuple[Slot, ...]

    def infobox(self) -> list[Slot]:
        return [s for s in self.slots if s.group == "infobox"]

    def sections(self) -> list[Slot]:
        return [s for s in self.slots if s.group == "section"]

    def section_tokens(self) -> list[str]:
        toks: list[str] = []
        if self.infobox():
            toks.append("infobox")
        toks.extend(s.token for s in self.sections())
        return toks


def _slot_from_raw(raw: dict) -> Slot:
    return Slot(
        token=raw["token"],
        group=raw.get("group", "section"),
        provenance=raw["provenance"],
        obligation=raw["obligation"],
        tiers=tuple(raw.get("tiers") or ()),
        fallback=raw.get("fallback"),
        genre_gated=bool(raw.get("genre_gated", False)),
    )


def _apply_new_overrides(slots: list, override: dict) -> list:
    remove = set(override.get("remove") or [])
    slots = [s for s in slots if s.token not in remove]
    for add in override.get("add") or []:
        slots.append(_slot_from_raw(add))
    return slots


def resolve_template(entity_type, importance, book_config=None, base=None):
    raw = base if base is not None else load_base_template()
    etype = str(entity_type).upper()
    groups = (raw.get("entity_types") or {}).get(etype)
    if not groups:
        return ResolvedTemplate(etype, importance, ())

    gen = book_config.get("generation", {}) if book_config else {}
    tier_cfg = gen.get(importance, {}) if isinstance(gen, dict) else {}
    legacy = tier_cfg.get("sections_by_type", {}).get(etype) \
        if isinstance(tier_cfg.get("sections_by_type"), dict) else None
    if legacy is None:
        legacy = tier_cfg.get("sections")  # may be None
    legacy_set = set(legacy) if isinstance(legacy, list) else None

    slots = []
    for group in ("infobox", "sections"):
        for slot_raw in groups.get(group) or []:
            slot = _slot_from_raw(slot_raw)
            if importance not in slot.tiers:
                continue
            # Legacy shape lists section tokens (and the "infobox" token);
            # honor it as a whitelist over sections. Infobox group is kept
            # whenever "infobox" appears in the legacy list.
            if legacy_set is not None:
                if slot.group == "infobox" and "infobox" not in legacy_set:
                    continue
                if slot.group == "section" and slot.token not in legacy_set:
                    continue
            slots.append(slot)

    if legacy is not None:
        legacy_order = {token: i for i, token in enumerate(legacy)}
        infobox_slots = [s for s in slots if s.group == "infobox"]
        section_slots = [s for s in slots if s.group == "section"]
        section_slots.sort(key=lambda s: legacy_order.get(s.token, len(legacy_order)))
        slots = infobox_slots + section_slots

    template_cfg = gen.get("template") if isinstance(gen, dict) else None
    new_override = template_cfg.get(etype) if isinstance(template_cfg, dict) else None
    if new_override:
        slots = _apply_new_overrides(slots, new_override)
    return ResolvedTemplate(etype, importance, tuple(slots))


def _rel_enum(base: dict | None):
    raw = base if base is not None else load_base_template()
    return (raw.get("relationships") or {}).get("enum") or {}


def relationship_tokens(base=None) -> list[str]:
    return list(_rel_enum(base).keys())


def canonical_relationship(value, base=None):
    if not value:
        return None
    enum = _rel_enum(base)
    if value in enum:
        return value
    for token, spec in enum.items():
        if value in (spec.get("legacy") or []):
            return token
    return None


def relationship_label(token, lang, base=None) -> str:
    spec = _rel_enum(base).get(token)
    if not spec:
        return token
    return (spec.get("labels") or {}).get(lang, token)


def slot_label(token, lang, base=None) -> str:
    raw = base if base is not None else load_base_template()
    entry = (raw.get("labels") or {}).get(token)
    if entry and lang in entry:
        return entry[lang]
    return token.replace("_", " ").title()


def output_language(book_config) -> str:
    cfg = book_config or {}
    gen = cfg.get("generation", {}) if isinstance(cfg.get("generation"), dict) else {}
    if gen.get("output_language"):
        return str(gen["output_language"])
    export = cfg.get("export", {}) if isinstance(cfg.get("export"), dict) else {}
    cats = export.get("categories", {}) if isinstance(export.get("categories"), dict) else {}
    if cats.get("language"):
        return str(cats["language"])
    return "en"
