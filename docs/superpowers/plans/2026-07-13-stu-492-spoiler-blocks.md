# STU-492 Spoiler Blocks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render chapter-tagged page content as native MediaWiki collapsible blocks keyed by chapter, and add a deterministic dated relationship index under the Relations section.

**Architecture:** A new pure module `wiki_creator/spoiler_blocks.py` does all wikitext transformation (split into `== Heading ==` blocks, wrap gated blocks in `mw-collapsible`, inject the relationship index). Page generation attaches a ready-to-render `relationship_index` list to each page (where entity data is available); `wiki_export.render_page` calls the pure transforms on the converted wikitext. Feature is off unless the book YAML sets `generation.spoiler.collapse_after_chapter`, keeping current output byte-identical.

**Tech Stack:** Python 3, pytest, PyYAML.

## Global Constraints

- Chat in French; **all code, comments, commit messages, docstrings in English**.
- French wiki output: relationship index uses language-neutral fields only (names, French `relationship_type` enum, chapter numbers). Never surface the English `evolution`/`key_moments` fields.
- Feature OFF by default: no `generation.spoiler.collapse_after_chapter` ⇒ zero collapsibles, zero index behavior change is acceptable but index attachment is additive. Existing goldens/smoke tests must stay green (run `make golden` and `pytest -q`).
- Chapter normalization uses the existing `wiki_creator.chapters.chapter_number`.
- Simplicity first, surgical changes, comments only for non-obvious *why*.

---

### Task 1: Extract shared section titles into `wiki_creator/sections.py`

Pure refactor: `_SECTION_TITLES` currently lives in `scripts/generate_wiki_pages.py`; the export-side spoiler logic needs it too. Move it to a shared module, import it back with the same local name (minimal churn).

**Files:**
- Create: `wiki_creator/sections.py`
- Modify: `scripts/generate_wiki_pages.py:47-58` (replace the dict literal with an import)
- Test: `tests/test_sections.py`

**Interfaces:**
- Produces: `wiki_creator.sections.SECTION_TITLES: dict[str, str]` — section key → French heading title. Keys: `infobox, biography, personality, physical, powers, relationships, trivia, events, narrative_role, references`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sections.py
from wiki_creator.sections import SECTION_TITLES


def test_section_titles_cover_known_keys():
    assert SECTION_TITLES["biography"] == "Biographie"
    assert SECTION_TITLES["relationships"] == "Relations"
    assert SECTION_TITLES["references"] == "Références"
    assert SECTION_TITLES["narrative_role"] == "Rôle dans le récit"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_sections.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki_creator.sections'`

- [ ] **Step 3: Create the shared module**

```python
# wiki_creator/sections.py
"""Section key → rendered heading title, shared by page generation and export."""

from __future__ import annotations

SECTION_TITLES: dict[str, str] = {
    "infobox": "Infobox",
    "biography": "Biographie",
    "personality": "Personnalité",
    "physical": "Description physique",
    "powers": "Pouvoirs",
    "relationships": "Relations",
    "trivia": "Anecdotes",
    "events": "Événements",
    "narrative_role": "Rôle dans le récit",
    "references": "Références",
}
```

- [ ] **Step 4: Point generate_wiki_pages at the shared dict**

In `scripts/generate_wiki_pages.py`, delete the `_SECTION_TITLES = { ... }` literal (lines 47-58) and add near the other `wiki_creator` imports:

```python
from wiki_creator.sections import SECTION_TITLES as _SECTION_TITLES
```

All existing `_SECTION_TITLES[...]` references stay unchanged.

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/test_sections.py tests/test_generate_wiki_pages_sectioned.py -q`
Expected: PASS (no behavior change in generation).

- [ ] **Step 6: Commit**

```bash
git add wiki_creator/sections.py scripts/generate_wiki_pages.py tests/test_sections.py
git commit -m "refactor(sections): extract SECTION_TITLES to shared module (STU-492)"
```

---

### Task 2: `wrap_collapsible` + section splitting in `wiki_creator/spoiler_blocks.py`

**Files:**
- Create: `wiki_creator/spoiler_blocks.py`
- Test: `tests/test_spoiler_blocks.py`

**Interfaces:**
- Consumes: `wiki_creator.sections.SECTION_TITLES`, `wiki_creator.chapters.chapter_number`.
- Produces:
  - `_split_sections(body: str) -> list[str]` — returns `[pre, "== H1 ==\n\nbody1", "== H2 ==\n\nbody2", ...]`; `pre` is any text before the first heading (may be empty string).
  - `_norm(title: str) -> str` — strip `=`, whitespace, lowercase.
  - `wrap_collapsible(body: str, content_units: list[dict], collapse_after: int) -> str` — wrap each `== Heading ==` block whose matching `content_units` entry has `revealed_at_chapter > collapse_after` in an `mw-collapsible` div.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_spoiler_blocks.py
from wiki_creator.spoiler_blocks import wrap_collapsible

BODY = (
    "== Biographie ==\n\nNé au chapitre 1.\n\n"
    "== Pouvoirs ==\n\nRévélés plus tard."
)


def test_wrap_gates_block_above_threshold():
    units = [
        {"section": "biography", "revealed_at_chapter": 1},
        {"section": "powers", "revealed_at_chapter": 20},
    ]
    out = wrap_collapsible(BODY, units, collapse_after=5)
    # biography (ch.1 <= 5) stays open
    assert '== Biographie ==\n\nNé au chapitre 1.' in out
    assert 'Biographie ==\n\nNé' in out and 'mw-collapsible' in out
    # powers (ch.20 > 5) is wrapped, expand text names the chapter
    assert 'data-expandtext="Chapitre 20 — révéler"' in out
    assert '<div class="mw-collapsible mw-collapsed"' in out
    assert '</div>' in out


def test_wrap_none_and_unmatched_left_open():
    units = [{"section": "biography", "revealed_at_chapter": None}]
    out = wrap_collapsible(BODY, units, collapse_after=5)
    assert "mw-collapsible" not in out  # None chapter + unmatched Pouvoirs → untouched
    assert out == BODY


def test_wrap_threshold_boundary_is_strict():
    units = [{"section": "biography", "revealed_at_chapter": 5}]
    out = wrap_collapsible(BODY, units, collapse_after=5)
    assert "mw-collapsible" not in out  # exactly == threshold stays open
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spoiler_blocks.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the module**

```python
# wiki_creator/spoiler_blocks.py
"""Per-chapter spoiler rendering for exported wikitext (STU-492).

Pure wikitext transforms used by wiki-export: wrap chapter-gated sections in
native MediaWiki ``mw-collapsible`` blocks, and inject a deterministic dated
relationship index. No LLM, no I/O.
"""

from __future__ import annotations

import re

from wiki_creator.chapters import chapter_number
from wiki_creator.sections import SECTION_TITLES

_HEADING_RE = re.compile(r"(?m)^(==\s+.+?\s+==)\s*$")


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
                f'data-collapsetext="Masquer">\n{block}\n</div>'
            )
        else:
            out.append(block)
    return "".join(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spoiler_blocks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/spoiler_blocks.py tests/test_spoiler_blocks.py
git commit -m "feat(spoiler): mw-collapsible wrapping of chapter-gated sections (STU-492)"
```

---

### Task 3: `relationship_index_lines`

**Files:**
- Modify: `wiki_creator/spoiler_blocks.py`
- Test: `tests/test_spoiler_blocks.py`

**Interfaces:**
- Produces: `relationship_index_lines(entity: dict) -> list[str]` — one `* [[Other]] — <type> (ch.X→ch.Y)` line per typed relationship carrying chapters, sorted by first-reveal chapter descending (most recent first). Empty list when none.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_spoiler_blocks.py
from wiki_creator.spoiler_blocks import relationship_index_lines


def _entity():
    return {
        "canonical_name": "Celaena Sardothien",
        "aliases": ["Lillian Gordaina"],
        "relationships": [
            {"entity_a": "Celaena Sardothien", "entity_b": "Chaol",
             "relationship_type": "amoureux", "chapters": ["C01.xhtml", "C55.xhtml"]},
            {"entity_a": "Cain", "entity_b": "Celaena Sardothien",
             "relationship_type": "antagoniste", "chapters": ["C07.xhtml"]},
            {"entity_a": "Celaena Sardothien", "entity_b": "Ghost",
             "relationship_type": None, "chapters": ["C03.xhtml"]},
            {"entity_a": "Celaena Sardothien", "entity_b": "NoChap",
             "relationship_type": "ami", "chapters": []},
        ],
    }


def test_relationship_index_lines_content_and_order():
    lines = relationship_index_lines(_entity())
    # untyped (Ghost) and chapter-less (NoChap) excluded
    assert lines == [
        "* [[Cain]] — antagoniste (ch.7)",          # reveal ch.7, most recent first
        "* [[Chaol]] — amoureux (ch.1→ch.55)",      # reveal ch.1
    ]


def test_relationship_index_lines_empty_when_no_typed():
    assert relationship_index_lines({"canonical_name": "X", "relationships": []}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spoiler_blocks.py::test_relationship_index_lines_content_and_order -v`
Expected: FAIL with `ImportError: cannot import name 'relationship_index_lines'`.

- [ ] **Step 3: Implement**

```python
# append to wiki_creator/spoiler_blocks.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spoiler_blocks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/spoiler_blocks.py tests/test_spoiler_blocks.py
git commit -m "feat(spoiler): deterministic dated relationship index lines (STU-492)"
```

---

### Task 4: `inject_relationship_index` + `spoiler_collapse_after`

**Files:**
- Modify: `wiki_creator/spoiler_blocks.py`
- Test: `tests/test_spoiler_blocks.py`

**Interfaces:**
- Produces:
  - `inject_relationship_index(body: str, lines: list[str]) -> str` — append an `''Évolution :''` sub-block (the given lines) at the end of the `== Relations ==` section. No-op if no Relations section or empty lines.
  - `spoiler_collapse_after(book_cfg: dict) -> int | None` — read `generation.spoiler.collapse_after_chapter`; `None` when absent.

- [ ] **Step 1: Write the failing tests**

```python
# add to tests/test_spoiler_blocks.py
from wiki_creator.spoiler_blocks import inject_relationship_index, spoiler_collapse_after

REL_BODY = "== Biographie ==\n\nBio.\n\n== Relations ==\n\nProse FR.\n"


def test_inject_appends_index_under_relations():
    out = inject_relationship_index(REL_BODY, ["* [[Chaol]] — amoureux (ch.1→ch.55)"])
    assert "Prose FR." in out
    assert "''Évolution :''" in out
    assert "* [[Chaol]] — amoureux (ch.1→ch.55)" in out
    # index sits inside the Relations section, not after Biographie
    assert out.index("Évolution") > out.index("Relations")
    assert out.index("Évolution") > out.index("Bio.")


def test_inject_noop_without_relations_or_lines():
    assert inject_relationship_index("== Biographie ==\n\nBio.", ["* x"]) == "== Biographie ==\n\nBio."
    assert inject_relationship_index(REL_BODY, []) == REL_BODY


def test_spoiler_collapse_after_reads_config():
    assert spoiler_collapse_after({"generation": {"spoiler": {"collapse_after_chapter": 3}}}) == 3
    assert spoiler_collapse_after({}) is None
    assert spoiler_collapse_after({"generation": {}}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spoiler_blocks.py::test_inject_appends_index_under_relations -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement**

```python
# append to wiki_creator/spoiler_blocks.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spoiler_blocks.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/spoiler_blocks.py tests/test_spoiler_blocks.py
git commit -m "feat(spoiler): relations index injection + collapse-after config reader (STU-492)"
```

---

### Task 5: Attach `relationship_index` to generated pages

Attach the ready-to-render index to each page next to the existing `content_units` attachment (3 sites), so export needs no relationship logic.

**Files:**
- Modify: `scripts/generate_wiki_pages.py` (import + 3 attachment sites near lines 1089, 1140, 1199)
- Test: `tests/test_generate_wiki_pages_sectioned.py`

**Interfaces:**
- Consumes: `wiki_creator.spoiler_blocks.relationship_index_lines`.
- Produces: `page["relationship_index"]: list[str]` on every non-stub page.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_generate_wiki_pages_sectioned.py
def test_sectioned_page_carries_relationship_index(monkeypatch):
    import scripts.generate_wiki_pages as gwp
    monkeypatch.setattr(gwp, "_generate_one_section", lambda **kw: "## Biographie\n\nBio.")
    entity = {
        "canonical_name": "Celaena", "type": "PERSON", "importance": "principal",
        "aliases": [], "context_by_chapter": {"C01.xhtml": ["ctx"]},
        "relationships": [
            {"entity_a": "Celaena", "entity_b": "Chaol",
             "relationship_type": "amoureux", "chapters": ["C01.xhtml", "C55.xhtml"]},
        ],
    }
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["biography", "relationships"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert page["relationship_index"] == ["* [[Chaol]] — amoureux (ch.1→ch.55)"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py::test_sectioned_page_carries_relationship_index -v`
Expected: FAIL with `KeyError: 'relationship_index'`.

- [ ] **Step 3: Implement — import and 3 attachment sites**

Add to the `wiki_creator` imports in `scripts/generate_wiki_pages.py`:

```python
from wiki_creator.spoiler_blocks import relationship_index_lines
```

At the identity-recovery site (near line 1089), directly after
`recovered["content_units"] = content_units(sections, entity)`:

```python
            recovered["relationship_index"] = relationship_index_lines(entity)
```

At the single-shot site (near line 1140), directly after
`item_result["content_units"] = content_units(sections, entity)`:

```python
        item_result["relationship_index"] = relationship_index_lines(entity)
```

At the sectioned site (near line 1199), add a key to the `page` dict literal
right after `"content_units": content_units(emitted, entity),`:

```python
        "relationship_index": relationship_index_lines(entity),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_sectioned.py
git commit -m "feat(pages): attach relationship_index to generated pages (STU-492)"
```

---

### Task 6: Wire rendering into `wiki_export.render_page`

**Files:**
- Modify: `scripts/wiki_export.py` (import, `render_page` signature + body, `main` config load + call)
- Test: `tests/test_wiki_export.py` (create if absent)

**Interfaces:**
- Consumes: `wiki_creator.spoiler_blocks.{wrap_collapsible, inject_relationship_index, spoiler_collapse_after}`.
- Produces: `render_page(page, labels, collapse_after=None)` — same return, body now carries the injected index and (when `collapse_after` is set) collapsibles.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_wiki_export.py
from scripts.wiki_export import render_page


def _page():
    return {
        "title": "Celaena", "entity_type": "PERSON", "importance": "principal",
        "content": "## Biographie\n\nBio.\n\n## Relations\n\nProse.",
        "infobox_fields": {"nom": "Celaena"},
        "content_units": [
            {"section": "biography", "revealed_at_chapter": 1},
            {"section": "relationships", "revealed_at_chapter": 20},
        ],
        "relationship_index": ["* [[Chaol]] — amoureux (ch.1→ch.55)"],
    }


LABELS = {"persons": "Personnages", "principal": "Personnages principaux",
          "secondary": "Personnages secondaires", "locations": "Lieux",
          "organizations": "Organisations", "events": "Événements",
          "persons_by_tome": "Personnages du Tome {n}", "locations_by_tome": "Lieux du Tome {n}",
          "organizations_by_tome": "Organisations du Tome {n}"}


def test_render_page_off_by_default_no_collapsible_but_index_present():
    _, content = render_page(_page(), LABELS)
    assert "mw-collapsible" not in content              # feature off
    assert "''Évolution :''" in content                # index always injected
    assert "* [[Chaol]] — amoureux (ch.1→ch.55)" in content


def test_render_page_collapses_late_sections_when_configured():
    _, content = render_page(_page(), LABELS, collapse_after=5)
    # Relations revealed ch.20 > 5 → wrapped; index rides inside it
    assert 'data-expandtext="Chapitre 20 — révéler"' in content
    assert content.index("mw-collapsible") < content.index("Évolution")
    assert "== Biographie ==" in content                # ch.1 <= 5 stays open
    assert "mw-collapsible mw-collapsed\">\n== Biographie" not in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wiki_export.py -v`
Expected: FAIL (`''Évolution :''` absent — index not yet injected).

- [ ] **Step 3: Implement render_page changes**

Add to imports in `scripts/wiki_export.py`:

```python
from pathlib import Path  # already imported; keep single import
from wiki_creator.spoiler_blocks import (
    wrap_collapsible,
    inject_relationship_index,
    spoiler_collapse_after,
)
```

Change the signature and body of `render_page`:

```python
def render_page(page: dict, labels: dict, collapse_after: int | None = None) -> tuple[str, str]:
    """(path relative to the wiki dir, wikitext content) for one page.

    STU-492: the Relations index is injected under the Relations section, and —
    when ``collapse_after`` is set — sections first revealed after that chapter
    are wrapped in native mw-collapsible blocks. ``collapse_after=None`` keeps the
    output byte-identical to pre-STU-492.
    """
    title = page["title"]
    entity_type = page.get("entity_type", "PERSON")
    body = convert(page.get("content", ""))
    body = inject_relationship_index(body, page.get("relationship_index") or [])
    if collapse_after is not None:
        body = wrap_collapsible(body, page.get("content_units") or [], collapse_after)
    filename = page_filename(title) + ".wiki"

    if entity_type == "SYNOPSIS":
        return filename, body

    infobox = make_infobox_call(entity_type, page.get("infobox_fields", {}))
    cats = category_tags(
        entity_type, page.get("importance", "secondaire"), labels, page.get("books")
    )
    page_content = infobox + "\n\n" + body
    if cats:
        page_content += "\n\n" + "\n".join(cats)
    subdir = _SUBDIR.get(entity_type, "characters")
    return f"{subdir}/{filename}", page_content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wiki_export.py -v`
Expected: PASS.

- [ ] **Step 5: Load `collapse_after` in `main` and pass it through**

In `scripts/wiki_export.py`, add a book-config loader near the other module
helpers:

```python
def _load_book_config(payload: dict) -> dict:
    """Read the book YAML (generation.spoiler lives there) from additional_context."""
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        return {}
    yaml_path = Path(file_path).with_suffix(".yaml")
    if not yaml_path.exists():
        return {}
    try:
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}
```

In `main`, after `paths = studio_io.paths_from_payload(payload)`:

```python
    collapse_after = spoiler_collapse_after(_load_book_config(payload))
```

Change the page render loop:

```python
    for page in pages:
        rel_path, page_content = render_page(page, labels, collapse_after)
```

- [ ] **Step 6: Run the full suite + golden + smoke**

Run: `pytest -q && make golden && make smoke`
Expected: `pytest` all pass (37 skips ok); golden and smoke succeed. If golden changed, the feature leaked into default output — the export must only wrap when `collapse_after is not None`; investigate before updating goldens.

- [ ] **Step 7: Commit**

```bash
git add scripts/wiki_export.py tests/test_wiki_export.py
git commit -m "feat(export): render mw-collapsible blocks + relations index (STU-492)"
```

---

### Task 7: Document config + CLAUDE.md gotcha

**Files:**
- Modify: `Makefile` book YAML (the default `BOOK`) — add a commented example, OR document in CLAUDE.md only (no functional change).
- Modify: `CLAUDE.md` (Gotchas section)

**Interfaces:** none (docs only).

- [ ] **Step 1: Add a Gotchas entry to `CLAUDE.md`**

Append under `## Gotchas`:

```markdown
- Spoiler blocks (STU-492): `wiki_export.render_page` wraps chapter-gated sections
  in native `mw-collapsible` divs and injects a dated relationship index under the
  Relations section. Gating is per-section via `content_units.revealed_at_chapter`
  (the min-chapter provenance from STU-491), matched to headings by normalized
  title. Enabled only when the book YAML sets `generation.spoiler.collapse_after_chapter: N`
  — unset keeps output byte-identical (goldens safe). The relationship index uses
  language-neutral fields only (names, French `relationship_type`, chapter numbers);
  the classifier's English `evolution`/`key_moments` are never surfaced. Pure logic
  in `wiki_creator/spoiler_blocks.py`; section→heading map in `wiki_creator/sections.py`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: STU-492 spoiler-blocks gotcha + config note"
```

---

## Self-Review

**Spec coverage:**
- Native `mw-collapsible` wrapping per chapter → Task 2 + Task 6. ✓
- Configurable `collapse_after_chapter`, off by default → Task 4 (`spoiler_collapse_after`) + Task 6. ✓
- Dated relationship index, language-neutral → Task 3 + Task 5 (attach) + Task 6 (inject). ✓
- Keep existing FR Relations prose untouched → Task 6 (`inject_relationship_index` appends, never replaces). ✓
- Shared `SECTION_TITLES` refactor → Task 1. ✓
- md2wiki unchanged (wrap post-convert) → Task 6 (transforms run on converted wikitext). ✓
- Goldens/smoke stay green → Task 6 Step 6 gate. ✓
- Known limitation (section-granularity) documented → Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `wrap_collapsible`, `inject_relationship_index`, `relationship_index_lines`, `spoiler_collapse_after`, `SECTION_TITLES` names match across Tasks 1–6. Page key `relationship_index` consistent between Task 5 (producer) and Task 6 (consumer). `content_units` entry shape `{section, revealed_at_chapter}` matches STU-491's `provenance.content_units`. ✓
