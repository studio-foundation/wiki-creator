"""Wiki page template schema: typed slots with provenance, resolved per
(entity_type, importance, book overrides). Pure data module — no pipeline
side effects. Consumed by generation (slices B-E)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from wiki_creator.relationship_vocabulary import book_relationship_types

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


def _book_types(book_config, base=None) -> list[dict[str, str]]:
    return book_relationship_types(book_config, reserved=_rel_enum(base).keys())


def relationship_tokens(base=None, book_config=None) -> list[str]:
    return list(_rel_enum(base).keys()) + [d["name"] for d in _book_types(book_config, base)]


def relationship_definitions(base=None, book_config=None) -> list[dict[str, str]]:
    """Type vocabulary + application criterion, injected into the classifier prompt (STU-477).

    A book's own types (STU-472) are appended: the generic enum stays the base, the
    world's bonds are added to it.
    """
    generic = [
        {"name": token, "description": (spec.get("description") or "").strip()}
        for token, spec in _rel_enum(base).items()
    ]
    return generic + _book_types(book_config, base)


def canonical_relationship(value, base=None, book_config=None):
    if not value:
        return None
    enum = _rel_enum(base)
    if value in enum:
        return value
    if any(value == d["name"] for d in _book_types(book_config, base)):
        return value
    for token, spec in enum.items():
        if value in (spec.get("legacy") or []):
            return token
    return None


def relationship_label(token, lang, base=None, book_config=None) -> str:
    spec = _rel_enum(base).get(token)
    if not spec:
        return token  # a book type's name is already its reader-facing label (STU-472)
    return (spec.get("labels") or {}).get(lang, token)


def slot_label(token, lang, base=None) -> str:
    raw = base if base is not None else load_base_template()
    entry = (raw.get("labels") or {}).get(token)
    if entry and lang in entry:
        return entry[lang]
    return token.replace("_", " ").title()


def chrome_label(key, lang, base=None) -> str:
    """Localized reader-facing export chrome string (base.yaml ``chrome``), e.g.
    the spoiler collapsible controls. Returns the raw template — callers that
    interpolate (``reveal`` carries ``{chapter}``) format it themselves."""
    raw = base if base is not None else load_base_template()
    entry = (raw.get("chrome") or {}).get(key) or {}
    return entry.get(lang) or entry.get("fr") or str(key)


def stub_content(kind, lang, base=None) -> str:
    """Localized reader-facing stub page body (base.yaml ``stubs``). ``kind`` is
    ``failed`` or ``insufficient``. Rendered under the biography heading."""
    raw = base if base is not None else load_base_template()
    heading = slot_label("biography", lang, raw)
    entry = (raw.get("stubs") or {}).get(kind) or {}
    message = entry.get(lang) or entry.get("fr") or ""
    return f"## {heading}\n\n*{message}*"


def validator_message(code, lang, base=None, **params) -> str:
    """Localized wiki-page-validator error message (base.yaml ``validator.errors``),
    keyed by a stable neutral ``code``. Falls back to French, then the raw code
    (STU-517). ``params`` fill the ``{placeholders}`` in the template."""
    raw = base if base is not None else load_base_template()
    entry = ((raw.get("validator") or {}).get("errors") or {}).get(code) or {}
    template = entry.get(lang) or entry.get("fr") or code
    return template.format(**params) if params else template


def language_name(lang, base=None) -> str:
    """English display name of a language code, for the (English) prompt
    scaffolding — e.g. ``language_name("fr") == "French"``."""
    raw = base if base is not None else load_base_template()
    names = raw.get("language_names") or {}
    return names.get(lang, str(lang))


def length_guide(tier, base=None) -> str:
    """Per-tier prose length guide. Single source (base.yaml ``length_by_tier``):
    no longer a hardcoded Python restatement of the per-tier length that could
    drift from ``max_tokens_per_page`` (STU-510)."""
    raw = base if base is not None else load_base_template()
    guides = raw.get("length_by_tier") or {}
    return guides.get(tier) or guides.get("figurant") or "1 short paragraph only."


def section_brief(entity_type, token, lang, base=None) -> str | None:
    """Localized writing brief for one (entity_type, section token), or None when
    none is declared. Unknown types fall back to PERSON (STU-510)."""
    raw = base if base is not None else load_base_template()
    briefs = raw.get("briefs") or {}
    etype = str(entity_type).upper()
    by_type = briefs.get(etype) or briefs.get("PERSON") or {}
    entry = by_type.get(token)
    if not entry:
        return None
    return entry.get(lang) or entry.get("fr")


def few_shot_example(lang, base=None) -> dict:
    """Localized few-shot tone/format example (base.yaml ``few_shot``)."""
    raw = base if base is not None else load_base_template()
    examples = raw.get("few_shot") or {}
    return examples.get(lang) or examples.get("fr") or {}


def output_language(book_config) -> str:
    """Language of the generated wiki (titles + prose). Defaults to French, the
    historical output language of this corpus; a book opts into another language
    via ``generation.output_language``. Deliberately independent of
    ``export.categories.language`` (category-label language is a separate axis —
    conflating them is the STU-510 silent-incoherence bug)."""
    cfg = book_config or {}
    gen = cfg.get("generation", {}) if isinstance(cfg.get("generation"), dict) else {}
    if gen.get("output_language"):
        return str(gen["output_language"])
    return "fr"
