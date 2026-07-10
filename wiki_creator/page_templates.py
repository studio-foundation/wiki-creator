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
        tiers = slot.get("tiers") or []
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


def resolve_template(entity_type, importance, book_config=None, base=None):
    raw = base if base is not None else load_base_template()
    etype = str(entity_type).upper()
    groups = (raw.get("entity_types") or {}).get(etype)
    if not groups:
        return ResolvedTemplate(etype, importance, ())
    slots = []
    for group in ("infobox", "sections"):
        for slot_raw in groups.get(group) or []:
            slot = _slot_from_raw(slot_raw)
            if importance in slot.tiers:
                slots.append(slot)
    return ResolvedTemplate(etype, importance, tuple(slots))
