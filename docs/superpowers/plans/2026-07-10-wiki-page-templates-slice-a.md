# Wiki Page Templates — Slice A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained template-schema module that resolves, per (entity_type, importance, book overrides), a list of typed slots — each tagged with a provenance class — plus a localizable relationship enum. No pipeline rewiring (that is slices B-E).

**Architecture:** A base-default template lives as data in `wiki_creator/templates/base.yaml`. A new pure module `wiki_creator/page_templates.py` loads it, validates it, merges per-book overrides (honoring the legacy `generation.<tier>.sections` shape for backward compatibility), filters slots by tier, and renders canonical tokens to per-language labels. The existing `generate_wiki_pages.py` is left untouched; slice B will consume this module.

**Tech Stack:** Python 3, `dataclasses`, `PyYAML` (already a dependency), `pytest`.

## Global Constraints

- No hardcoded vocabulary in scripts — all display strings/labels live in `base.yaml` or the book YAML (project invariant: CLAUDE.md "Never add hardcoded word lists to scripts").
- Degrade gracefully to empty when a config key is absent — never raise on a missing optional key (project invariant).
- Provenance ∈ `{batch-bound, extracted-fact, llm-prose}`. Obligation ∈ `{MIN, OPT}`. Tiers ⊆ `{figurant, secondary, principal}`.
- Every `MIN` + `extracted-fact` slot MUST declare a `fallback`.
- Backward compat: a book yaml using the legacy `generation.<tier>.sections` / `sections_by_type` shape must still resolve to the same flat section-token list it produces today.
- Verify with `pytest -q` after each task; baseline is `735 passed, 31 skipped`.

---

### Task 1: Base template data file + loader + validation

**Files:**
- Create: `wiki_creator/templates/base.yaml`
- Create: `wiki_creator/page_templates.py`
- Test: `tests/test_page_templates_schema.py`

**Interfaces:**
- Produces: `load_base_template(path: str | Path | None = None) -> dict` (raw parsed YAML), `validate_template(raw: dict) -> None` (raises `ValueError` on invalid provenance/obligation/tier, or a `MIN`+`extracted-fact` slot without `fallback`). Module constants `PROVENANCES`, `OBLIGATIONS`, `TIERS`, and `DEFAULT_BASE_PATH`.

- [ ] **Step 1: Write the base template data file**

Create `wiki_creator/templates/base.yaml`:

```yaml
version: 1
entity_types:
  PERSON:
    infobox:
      - {token: nom,         group: infobox, provenance: batch-bound,    obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: type,        group: infobox, provenance: batch-bound,    obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: alias,       group: infobox, provenance: batch-bound,    obligation: OPT, tiers: [figurant, secondary, principal]}
      - {token: status,      group: infobox, provenance: extracted-fact, obligation: MIN, fallback: unknown, tiers: [figurant, secondary, principal]}
      - {token: species,     group: infobox, provenance: extracted-fact, obligation: OPT, genre_gated: true, tiers: [secondary, principal]}
      - {token: affiliation, group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [secondary, principal]}
      - {token: titles,      group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [principal]}
    sections:
      - {token: biography,     group: section, provenance: llm-prose,      obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: relationships, group: section, provenance: extracted-fact, obligation: OPT, tiers: [secondary, principal]}
      - {token: personality,   group: section, provenance: llm-prose,      obligation: OPT, tiers: [principal]}
      - {token: physical,      group: section, provenance: llm-prose,      obligation: OPT, tiers: [principal]}
      - {token: powers,        group: section, provenance: llm-prose,      obligation: OPT, genre_gated: true, tiers: [principal]}
      - {token: trivia,        group: section, provenance: llm-prose,      obligation: OPT, tiers: [principal]}
      - {token: references,    group: section, provenance: extracted-fact, obligation: MIN, fallback: none, tiers: [figurant, secondary, principal]}
  PLACE:
    infobox:
      - {token: nom,         group: infobox, provenance: batch-bound,    obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: type,        group: infobox, provenance: batch-bound,    obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: location,    group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [secondary, principal]}
    sections:
      - {token: biography,     group: section, provenance: llm-prose,      obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: physical,      group: section, provenance: llm-prose,      obligation: OPT, tiers: [principal]}
      - {token: relationships, group: section, provenance: extracted-fact, obligation: OPT, tiers: [principal]}
      - {token: trivia,        group: section, provenance: llm-prose,      obligation: OPT, tiers: [principal]}
      - {token: references,    group: section, provenance: extracted-fact, obligation: MIN, fallback: none, tiers: [figurant, secondary, principal]}
  ORG:
    infobox:
      - {token: nom,     group: infobox, provenance: batch-bound,    obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: type,    group: infobox, provenance: batch-bound,    obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: leaders, group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [secondary, principal]}
    sections:
      - {token: biography,     group: section, provenance: llm-prose,      obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: relationships, group: section, provenance: extracted-fact, obligation: OPT, tiers: [secondary, principal]}
      - {token: references,    group: section, provenance: extracted-fact, obligation: MIN, fallback: none, tiers: [figurant, secondary, principal]}
  EVENT:
    infobox:
      - {token: nom,  group: infobox, provenance: batch-bound, obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: type, group: infobox, provenance: batch-bound, obligation: MIN, tiers: [figurant, secondary, principal]}
    sections:
      - {token: biography,     group: section, provenance: llm-prose,      obligation: MIN, tiers: [figurant, secondary, principal]}
      - {token: relationships, group: section, provenance: extracted-fact, obligation: OPT, tiers: [secondary, principal]}
      - {token: references,    group: section, provenance: extracted-fact, obligation: MIN, fallback: none, tiers: [figurant, secondary, principal]}
relationships:
  enum:
    family:       {legacy: [famille],            labels: {en: Family,       fr: Famille}}
    mentor:       {legacy: ["mentor/protégé"],   labels: {en: Mentor,       fr: "Mentor/protégé"}}
    romance:      {legacy: [amoureux],           labels: {en: Romance,      fr: Amoureux}}
    antagonist:   {legacy: [antagoniste],        labels: {en: Antagonist,   fr: Antagoniste}}
    ally:         {legacy: [allié],              labels: {en: Ally,         fr: Allié}}
    employment:   {legacy: ["employeur/employé"], labels: {en: Employment,  fr: "Employeur/employé"}}
    friend:       {legacy: [ami],                labels: {en: Friend,       fr: Ami}}
    acquaintance: {legacy: [connaissance],       labels: {en: Acquaintance, fr: Connaissance}}
    other:        {legacy: [autre],              labels: {en: Other,        fr: Autre}}
labels:
  nom:           {en: Name,        fr: Nom}
  type:          {en: Type,        fr: Type}
  alias:         {en: Aliases,     fr: Alias}
  status:        {en: Status,      fr: Statut}
  species:       {en: Species,     fr: Espèce}
  affiliation:   {en: Affiliation, fr: Affiliation}
  titles:        {en: Titles,      fr: Titres}
  location:      {en: Location,    fr: Localisation}
  leaders:       {en: Leaders,     fr: Leaders}
  infobox:       {en: Infobox,     fr: Infobox}
  biography:     {en: Biography,   fr: Biographie}
  relationships: {en: Relationships, fr: Relations}
  personality:   {en: Personality, fr: Personnalité}
  physical:      {en: Appearance,  fr: "Description physique"}
  powers:        {en: Powers,      fr: Pouvoirs}
  trivia:        {en: Trivia,      fr: Anecdotes}
  references:    {en: References,  fr: Références}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_page_templates_schema.py`:

```python
import copy
import pytest
from wiki_creator import page_templates as pt


def test_base_template_loads_and_validates():
    raw = pt.load_base_template()
    assert set(raw["entity_types"]) >= {"PERSON", "PLACE", "ORG", "EVENT"}
    pt.validate_template(raw)  # must not raise


def test_validate_rejects_unknown_provenance():
    raw = copy.deepcopy(pt.load_base_template())
    raw["entity_types"]["PERSON"]["infobox"][0]["provenance"] = "made-up"
    with pytest.raises(ValueError, match="provenance"):
        pt.validate_template(raw)


def test_validate_requires_fallback_for_min_extracted_fact():
    raw = copy.deepcopy(pt.load_base_template())
    slot = {"token": "x", "group": "infobox", "provenance": "extracted-fact",
            "obligation": "MIN", "tiers": ["figurant"]}
    raw["entity_types"]["PERSON"]["infobox"].append(slot)
    with pytest.raises(ValueError, match="fallback"):
        pt.validate_template(raw)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_page_templates_schema.py -v`
Expected: FAIL with `ModuleNotFoundError` / `AttributeError: module 'wiki_creator.page_templates' has no attribute 'load_base_template'`

- [ ] **Step 4: Write minimal implementation**

Create `wiki_creator/page_templates.py`:

```python
"""Wiki page template schema: typed slots with provenance, resolved per
(entity_type, importance, book overrides). Pure data module — no pipeline
side effects. Consumed by generation (slices B-E)."""
from __future__ import annotations

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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_page_templates_schema.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Ensure the data file ships with the package**

Confirm the package includes YAML data. Check `pyproject.toml` for package-data / setuptools config:

Run: `grep -nE "package-data|include-package-data|\.yaml|MANIFEST" pyproject.toml MANIFEST.in 2>/dev/null`

If `wiki_creator/cue_words/*.json` is already shipped (it is used at runtime), YAML under `wiki_creator/templates/` ships by the same mechanism — no change needed. If cue_words relies on `include-package-data = true` with an sdist that globs, verify `*.yaml` is not excluded. Add `wiki_creator/templates/*.yaml` to package-data only if cue_words required an explicit entry.

- [ ] **Step 7: Commit**

```bash
git add wiki_creator/templates/base.yaml wiki_creator/page_templates.py tests/test_page_templates_schema.py
git commit -m "feat(templates): base wiki page template schema + validation (slice A)"
```

---

### Task 2: Slot/ResolvedTemplate dataclasses + resolve_template (base-default + tier filter)

**Files:**
- Modify: `wiki_creator/page_templates.py`
- Test: `tests/test_page_templates_resolve.py`

**Interfaces:**
- Consumes: `load_base_template`, `validate_template`, `TIERS` from Task 1.
- Produces: frozen dataclasses `Slot(token: str, group: str, provenance: str, obligation: str, tiers: tuple[str, ...], fallback: str | None, genre_gated: bool)` and `ResolvedTemplate(entity_type: str, importance: str, slots: tuple[Slot, ...])` with methods `infobox() -> list[Slot]`, `sections() -> list[Slot]`. Function `resolve_template(entity_type: str, importance: str, book_config: dict | None = None, base: dict | None = None) -> ResolvedTemplate` (Task 2 handles only base-default + tier filtering; `book_config` is accepted but ignored until Task 3).

- [ ] **Step 1: Write the failing test**

Create `tests/test_page_templates_resolve.py`:

```python
from wiki_creator import page_templates as pt


def test_resolve_person_principal_includes_all_tiers():
    rt = pt.resolve_template("PERSON", "principal")
    tokens = [s.token for s in rt.sections()]
    assert "biography" in tokens
    assert "personality" in tokens  # principal-only
    assert "references" in tokens


def test_resolve_person_figurant_is_minimal():
    rt = pt.resolve_template("PERSON", "figurant")
    section_tokens = [s.token for s in rt.sections()]
    assert "biography" in section_tokens
    assert "references" in section_tokens   # references is MIN at every tier
    assert "personality" not in section_tokens  # principal-only, filtered out
    info_tokens = [s.token for s in rt.infobox()]
    assert "nom" in info_tokens
    assert "species" not in info_tokens  # species starts at secondary


def test_resolve_unknown_type_returns_empty():
    rt = pt.resolve_template("MONSTER", "principal")
    assert rt.slots == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_page_templates_resolve.py -v`
Expected: FAIL with `AttributeError: module 'wiki_creator.page_templates' has no attribute 'resolve_template'`

- [ ] **Step 3: Write minimal implementation**

Append to `wiki_creator/page_templates.py`:

```python
from dataclasses import dataclass


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_page_templates_resolve.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/page_templates.py tests/test_page_templates_resolve.py
git commit -m "feat(templates): resolve typed slots by entity_type and tier (slice A)"
```

---

### Task 3: Per-book overrides + legacy compat + section_tokens() adapter

**Files:**
- Modify: `wiki_creator/page_templates.py`
- Test: `tests/test_page_templates_overrides.py`

**Interfaces:**
- Consumes: `resolve_template`, `ResolvedTemplate`, `Slot` from Task 2.
- Produces: `ResolvedTemplate.section_tokens() -> list[str]` (legacy flat list: `["infobox"]` when any infobox slot is present, followed by each section token — parity with `generate_wiki_pages.generation_profile`'s section list). `resolve_template` now honors `book_config` overrides read from `book_config["generation"]`: (a) legacy `<tier>.sections` and `<tier>.sections_by_type.<ETYPE>` restrict/override the section-token set; (b) new `generation.template.<ETYPE>` may add/remove/rename slots.

- [ ] **Step 1: Write the failing test**

Create `tests/test_page_templates_overrides.py`:

```python
from wiki_creator import page_templates as pt


def test_section_tokens_parity_shape():
    rt = pt.resolve_template("PERSON", "secondary")
    toks = rt.section_tokens()
    assert toks[0] == "infobox"
    assert "biography" in toks and "references" in toks


def test_legacy_sections_by_type_override_restricts_sections():
    book = {"generation": {"principal": {
        "sections_by_type": {"ORG": ["infobox", "biography", "references"]}}}}
    rt = pt.resolve_template("ORG", "principal", book_config=book)
    assert rt.section_tokens() == ["infobox", "biography", "references"]
    # relationships was in the base ORG.principal set but is excluded by the override
    assert "relationships" not in rt.section_tokens()


def test_new_template_override_removes_slot():
    book = {"generation": {"template": {"PERSON": {"remove": ["powers"]}}}}
    rt = pt.resolve_template("PERSON", "principal", book_config=book)
    assert "powers" not in [s.token for s in rt.sections()]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_page_templates_overrides.py -v`
Expected: FAIL with `AttributeError: 'ResolvedTemplate' object has no attribute 'section_tokens'`

- [ ] **Step 3: Write minimal implementation**

Add the `section_tokens` method to `ResolvedTemplate`:

```python
    def section_tokens(self) -> list[str]:
        toks: list[str] = []
        if self.infobox():
            toks.append("infobox")
        toks.extend(s.token for s in self.sections())
        return toks
```

Replace `resolve_template` body with override-aware logic:

```python
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

    gen = (book_config or {}).get("generation", {}) if book_config else {}
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

    new_override = (gen.get("template", {}) or {}).get(etype) if isinstance(gen.get("template"), dict) else None
    if new_override:
        slots = _apply_new_overrides(slots, new_override)
    return ResolvedTemplate(etype, importance, tuple(slots))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_page_templates_overrides.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/page_templates.py tests/test_page_templates_overrides.py
git commit -m "feat(templates): per-book overrides + legacy section-token compat (slice A)"
```

---

### Task 4: Relationship enum — canonicalization + localized labels

**Files:**
- Modify: `wiki_creator/page_templates.py`
- Test: `tests/test_page_templates_relationships.py`

**Interfaces:**
- Consumes: `load_base_template` from Task 1.
- Produces: `canonical_relationship(value: str | None, base: dict | None = None) -> str | None` (maps a legacy French label OR an already-canonical token to its canonical token; returns `None` for `None`/unknown), `relationship_label(token: str, lang: str, base: dict | None = None) -> str` (renders a canonical token to its display label, falling back to the token itself if lang/label absent), and `relationship_tokens(base=None) -> list[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_page_templates_relationships.py`:

```python
from wiki_creator import page_templates as pt


def test_canonical_from_legacy_french():
    assert pt.canonical_relationship("employeur/employé") == "employment"
    assert pt.canonical_relationship("antagoniste") == "antagonist"


def test_canonical_passthrough_and_unknown():
    assert pt.canonical_relationship("family") == "family"   # already canonical
    assert pt.canonical_relationship(None) is None
    assert pt.canonical_relationship("gibberish") is None


def test_relationship_label_localized():
    assert pt.relationship_label("antagonist", "en") == "Antagonist"
    assert pt.relationship_label("antagonist", "fr") == "Antagoniste"
    # unknown token/lang falls back to the token
    assert pt.relationship_label("antagonist", "de") == "antagonist"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_page_templates_relationships.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'canonical_relationship'`

- [ ] **Step 3: Write minimal implementation**

Append to `wiki_creator/page_templates.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_page_templates_relationships.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/page_templates.py tests/test_page_templates_relationships.py
git commit -m "feat(templates): canonical relationship enum + localized labels (slice A)"
```

---

### Task 5: Slot label rendering + output-language resolution

**Files:**
- Modify: `wiki_creator/page_templates.py`
- Test: `tests/test_page_templates_labels.py`

**Interfaces:**
- Consumes: `load_base_template` from Task 1; `book_language` from `wiki_creator.lang`.
- Produces: `slot_label(token: str, lang: str, base: dict | None = None) -> str` (renders a slot/section token to its display label via the `labels` table, falling back to a title-cased token), and `output_language(book_config: dict | None) -> str` (returns `book_config["generation"]["output_language"]` if set, else `book_config["export"]["categories"]["language"]`, else `"en"`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_page_templates_labels.py`:

```python
from wiki_creator import page_templates as pt


def test_slot_label_localized():
    assert pt.slot_label("status", "en") == "Status"
    assert pt.slot_label("status", "fr") == "Statut"


def test_slot_label_fallback_titlecase():
    assert pt.slot_label("made_up_token", "en") == "Made Up Token"


def test_output_language_precedence():
    assert pt.output_language({"generation": {"output_language": "fr"}}) == "fr"
    assert pt.output_language({"export": {"categories": {"language": "en"}}}) == "en"
    assert pt.output_language(None) == "en"
    # generation.output_language wins over export
    cfg = {"generation": {"output_language": "fr"},
           "export": {"categories": {"language": "en"}}}
    assert pt.output_language(cfg) == "fr"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_page_templates_labels.py -v`
Expected: FAIL with `AttributeError: ... has no attribute 'slot_label'`

- [ ] **Step 3: Write minimal implementation**

Append to `wiki_creator/page_templates.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_page_templates_labels.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `pytest -q`
Expected: `749 passed, 31 skipped` (baseline 735 + 14 new template tests), no failures.

- [ ] **Step 6: Commit**

```bash
git add wiki_creator/page_templates.py tests/test_page_templates_labels.py
git commit -m "feat(templates): slot label rendering + output-language resolution (slice A)"
```

---

## Self-Review

**Spec coverage** (against `2026-07-10-wiki-page-templates-design.md`):
- Three-axis slot model (token / obligation×tier / provenance) → Tasks 1-2 (data + dataclasses).
- Field-level infobox (vs opaque `infobox` token) → Task 1 data + Task 2 `infobox()`.
- `batch-bound` / `extracted-fact` / `llm-prose` classes → Task 1 `PROVENANCES` + validation.
- MIN extracted-fact fallback rule → Task 1 `validate_template`.
- Base-default + per-book override → Task 3.
- Backward compat with legacy `generation.<tier>.sections` / `sections_by_type` → Task 3 + `section_tokens()`.
- Canonical relationship enum (fixes French-labels bug) → Task 4.
- Canonical tokens + `labels[lang]` rendering, `output_language` per book → Tasks 4-5.
- Type-completeness (PERSON/PLACE/ORG/EVENT) → Task 1 data.
- Cross-cutting rules live in invariants, NOT schema → intentionally out of scope (spec §"Cross-cutting rules"); no task, correct.
- Slices B-E (generation rewiring) → out of scope per spec; no task, correct.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test shows real assertions.

**Type consistency:** `Slot`/`ResolvedTemplate` fields identical across Tasks 2-3. `resolve_template` signature `(entity_type, importance, book_config=None, base=None)` stable from Task 2 (accepts+ignores `book_config`) into Task 3 (honors it). `base=None` optional-arg convention consistent across `resolve_template`, `canonical_relationship`, `relationship_label`, `slot_label`. `section_tokens()` shape (`["infobox", ...section tokens]`) matches the legacy `generation_profile` section list it must be swap-compatible with.

**Note for slice B handoff:** slice B replaces `generate_wiki_pages.generation_profile`'s section list with `resolve_template(...).section_tokens()` and binds `batch-bound` infobox slots (`nom`, `type`, `alias`) from the batch entity in `parse_response` — generalizing the STU-319 force-set hack. `max_tokens_per_page` resolution stays in `generation_profile` (not a template concern).

**Deferred findings & caveats (from the final whole-branch review — slice B/C authors read this):**

- **Order parity is now guaranteed** — `section_tokens()` preserves the legacy config's section ORDER, not just its set (fixed in `65d470e`). The slice-B swap of `generation_profile`'s list for `section_tokens()` is a genuine no-op on the shipping book; `test_legacy_section_order_is_preserved` pins this.
- **`add` overrides bypass tier filtering** — `_apply_new_overrides` appends `add` slots unconditionally, ignoring their declared `tiers` (an added `tiers:[principal]` slot still shows at `secondary`). Treat explicit `add` as force-include for now; if C/D needs tier-aware adds, apply the tier filter in `_apply_new_overrides` and add a test.
- **Legacy tokens absent from `base.yaml` are silently dropped** — the legacy path is a whitelist over base slots. A book listing a custom section token `base.yaml` doesn't define yields no slot (old `generation_profile` passed it through). The sanctioned path is `generation.template.<ETYPE>.add`; no shipping book hits this.
- **`rename` is not implemented** — only `add`/`remove` exist on `generation.template.<ETYPE>`. Rename = remove + add. Implement `rename` or trim the interface docs when a book needs it.
- **Cheap cleanups deferred** (safe): type annotations on `resolve_template`/`_apply_new_overrides`; tests for the invalid-`obligation`/invalid-`tiers` raise branches in `validate_template`.
