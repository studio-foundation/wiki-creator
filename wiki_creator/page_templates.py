"""Wiki page template schema: typed slots with provenance, resolved per
(entity_type, importance, book overrides). Pure data module — no pipeline
side effects. Consumed by generation (slices B-E)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from wiki_creator.lang import book_language
from wiki_creator.relationship_vocabulary import book_relationship_types

PROVENANCES = {"batch-bound", "extracted-fact", "llm-prose"}
OBLIGATIONS = {"MIN", "OPT"}
TIERS = ("figurant", "secondary", "principal")

DEFAULT_VALIDATE_PAGES = "principal"


def should_validate_page(importance: str, setting: str = DEFAULT_VALIDATE_PAGES) -> bool:
    """Whether a page of this tier runs the grounding validator + re-generation
    loop (STU-670). ``setting`` names the FLOOR tier — validate it and every
    tier above — or the sentinels ``all`` / ``off``. An unknown importance
    validates (fail safe: never silently drop grounding on an unrecognized tier).

    The cost this gates is the ``group max_iterations`` re-generation, not the
    validator itself (a deterministic script); skipping it lets a low-tier page
    through as if it had passed, uncontested."""
    setting = (setting or DEFAULT_VALIDATE_PAGES).strip().lower()
    if setting == "off":
        return False
    if setting == "all":
        return True
    floor = TIERS.index(setting) if setting in TIERS else TIERS.index(DEFAULT_VALIDATE_PAGES)
    return TIERS.index(importance) >= floor if importance in TIERS else True


DEFAULT_BASE_PATH = Path(__file__).resolve().parent / "templates" / "base.yaml"
LANG_PACK_DIR = Path(__file__).resolve().parent / "templates" / "lang"
FALLBACK_LANG = "en"
_PACK_DOCS = "docs/adding-a-language.md"


def load_base_template(path: str | Path | None = None) -> dict:
    p = Path(path) if path else DEFAULT_BASE_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class TemplatePackError(Exception):
    """A localized string is declared nowhere, not even in the reference pack."""


def shipped_languages() -> tuple[str, ...]:
    """Language codes that ship a template pack, English first."""
    codes = (p.stem for p in LANG_PACK_DIR.glob("*.yaml"))
    return tuple(sorted(codes, key=lambda c: (c != FALLBACK_LANG, c)))


@lru_cache(maxsize=None)
def load_lang_template(lang: str) -> dict:
    """Output strings for one language (``templates/lang/<lang>.yaml``, STU-732).

    Empty when the language ships no pack: resolution then runs entirely through
    the English fallback, so a book in an unsupported output language renders
    English chrome rather than failing — or, before the split, French chrome.
    """
    path = LANG_PACK_DIR / f"{lang}.yaml"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


_RAISE = object()


def localized(lang, *path, default=_RAISE):
    """Resolve one localized value: requested language -> ``en`` -> ``default``.

    The single fallback chain (STU-732). Before the split each helper had its own,
    and most ended in French — a German book missing a key got a French string.
    A ``default`` of ``_RAISE`` means the key is required: absent from ``en.yaml``
    it is declared nowhere, which is a bug in the repo, not in the book.
    """
    for code in (lang, FALLBACK_LANG):
        node = load_lang_template(str(code))
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if node not in (None, ""):
            return node
    if default is _RAISE:
        raise TemplatePackError(
            f"No string for {'.'.join(str(k) for k in path)} in lang pack "
            f"{lang!r} nor in the {FALLBACK_LANG!r} reference pack. "
            f"Declare it in {LANG_PACK_DIR.name}/{FALLBACK_LANG}.yaml (see {_PACK_DOCS})."
        )
    return default


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


def _sub_role_enum(base: dict | None):
    raw = base if base is not None else load_base_template()
    return (raw.get("relationships") or {}).get("sub_roles") or {}


def sub_role_tokens(base=None) -> list[str]:
    """The kinship/romance sub-role tokens a discovered pair may carry (STU-665)."""
    return list(_sub_role_enum(base).keys())


def sub_role_definitions(base=None) -> list[dict[str, str]]:
    """Sub-role vocabulary + application criterion, injected into the discovery prompt (STU-665)."""
    return [
        {"name": token, "description": (spec.get("description") or "").strip()}
        for token, spec in _sub_role_enum(base).items()
    ]


def sub_role_label(token, lang) -> str:
    """Reader-facing localized sub-role label, or the token itself when the packs
    declare none (STU-665)."""
    return localized(lang, "sub_role_labels", token, default=token)


def _confidence_enum(base: dict | None):
    raw = base if base is not None else load_base_template()
    return (raw.get("relationships") or {}).get("confidence") or {}


def confidence_tokens(base=None) -> list[str]:
    return list(_confidence_enum(base).keys())


def confidence_definitions(base=None) -> list[dict[str, str]]:
    """Confidence tiers + grading criterion, injected into the classifier prompt (STU-476)."""
    return [
        {"name": token, "description": (spec.get("description") or "").strip()}
        for token, spec in _confidence_enum(base).items()
    ]


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
    if token not in _rel_enum(base):
        return token  # a book type's name is already its reader-facing label (STU-472)
    return localized(lang, "relationship_labels", token, default=token)


def slot_label(token, lang) -> str:
    """Reader-facing name of a page token (pack ``labels``). A token no pack
    declares renders titlecased, so a book-declared custom slot needs no pack
    edit."""
    return localized(lang, "labels", token, default=None) \
        or token.replace("_", " ").title()


def infobox_tokens(entity_type, base=None) -> list[str]:
    """The infobox slot tokens a type declares, in order (every tier). This is the
    vocabulary the page renderer emits into ``infobox_fields``, so it is also the
    parameter list of the generated infobox template (STU-729)."""
    raw = base if base is not None else load_base_template()
    spec = (raw.get("entity_types") or {}).get(str(entity_type).upper()) or {}
    return [s["token"] for s in (spec.get("infobox") or []) if s.get("token")]


def render_infobox_source(entity_type, lang, base=None) -> str | None:
    """Generate the MediaWiki infobox template for a type from its declared infobox
    tokens (STU-729): the first token is the header (the name), each remaining token
    a row labelled from the `lang` template pack. Deriving the template from the same
    vocabulary the renderer emits is what stops the two from drifting — a hand-kept
    template declared ``{{{name}}}`` while the renderer emitted ``nom=``, so every
    row rendered empty. Returns None for a type with no infobox (OTHER, SYNOPSIS)."""
    tokens = infobox_tokens(entity_type, base)
    if not tokens:
        return None
    header, *rows = tokens
    lines = ['<includeonly>', '{| class="infobox"', '|-', "! colspan=\"2\" | {{{" + header + "}}}"]
    for token in rows:
        lines.append("|-")
        lines.append("| '''" + slot_label(token, lang) + "''' || {{{" + token + "|}}}")
    lines.append("|}")
    lines.append("</includeonly>")
    return "\n".join(lines)


def chrome_label(key, lang) -> str:
    """Localized reader-facing export chrome string (pack ``chrome``), e.g. the
    spoiler collapsible controls. Returns the raw template — callers that
    interpolate (``reveal`` carries ``{chapter}``) format it themselves."""
    return localized(lang, "chrome", key)


def stub_message(kind, lang) -> str:
    """Localized stub body text (pack ``stubs``) — the sentence rendered in place
    of a page that could not be generated. ``stub_content`` wraps it under the
    biography heading; the event pages use the ``course`` heading instead."""
    return localized(lang, "stubs", kind)


def stub_content(kind, lang) -> str:
    """Localized reader-facing stub page body. ``kind`` is ``failed`` or
    ``insufficient``. Rendered under the biography heading."""
    return f"## {slot_label('biography', lang)}\n\n*{stub_message(kind, lang)}*"


def validator_message(code, lang, **params) -> str:
    """Localized wiki-page-validator error message (pack ``validator_errors``),
    keyed by a stable neutral ``code`` (STU-517). ``params`` fill the
    ``{placeholders}`` in the template."""
    template = localized(lang, "validator_errors", code)
    return template.format(**params) if params else template


def language_name(lang) -> str:
    """English display name of a language code, for the (English) prompt
    scaffolding — e.g. ``language_name("fr") == "French"``.

    The one key with no English fallback: it names the pack itself, so a language
    that ships none degrades to its own code. Answering "English" for a German
    book would order English prose from the writer.
    """
    return load_lang_template(str(lang)).get("language_name") or str(lang)


def length_guide(tier, base=None) -> str:
    """Per-tier prose length guide. Single source (base.yaml ``length_by_tier``):
    no longer a hardcoded Python restatement of the per-tier length that could
    drift from ``max_tokens_per_page`` (STU-510)."""
    raw = base if base is not None else load_base_template()
    guides = raw.get("length_by_tier") or {}
    return guides.get(tier) or guides.get("figurant") or "1 short paragraph only."


def section_brief(entity_type, token, lang) -> str | None:
    """Localized writing brief for one (entity_type, section token), or None when
    none is declared. Unknown types fall back to PERSON (STU-510)."""
    etype = str(entity_type).upper()
    for code in (lang, FALLBACK_LANG):
        briefs = load_lang_template(str(code)).get("briefs") or {}
        by_type = briefs.get(etype) or briefs.get("PERSON") or {}
        if by_type.get(token):
            return by_type[token]
    return None


def few_shot_example(lang) -> dict:
    """Localized few-shot tone/format example (pack ``few_shot``)."""
    return localized(lang, "few_shot")


def output_language(book_config) -> str:
    """Language of the generated wiki (titles + prose). Defaults to the book's own
    language (``book_language`` — the language the NER/cue-words already run in), so
    an English source yields an English wiki unless a book opts into another language
    via ``generation.output_language``. Deliberately independent of
    ``export.categories.language`` (category-label language is a separate axis —
    conflating them is the STU-510 silent-incoherence bug)."""
    cfg = book_config or {}
    gen = cfg.get("generation", {}) if isinstance(cfg.get("generation"), dict) else {}
    if gen.get("output_language"):
        return str(gen["output_language"])
    return book_language(cfg)
