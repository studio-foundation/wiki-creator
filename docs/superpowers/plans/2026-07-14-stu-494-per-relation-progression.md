# STU-494 · Per-relation FR progression subsections — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the `== Relations ==` section as one `=== [[Name]] ===` French-prose subsection per typed relationship, each in its own per-relation `mw-collapsible` gated on that relation's last chapter.

**Architecture:** Two pure helpers (provenance `relation_units`, render `wrap_relation_collapsibles`) plus a generation branch: when the book YAML enables `generation.relations.per_relation_prose`, a PERSON's `relationships` section is generated as N single-relation LLM calls instead of one, and export wraps each subsection in its own collapsible. Opt-in — off/absent keeps output byte-identical to STU-492.

**Tech Stack:** Python 3, pytest, existing Studio `wiki-page-item` generation path.

## Global Constraints

- **PERSON only** — per-relation prose applies to PERSON entities with typed relationships; every other type is untouched.
- **Opt-in / byte-identical when off** — `generation.relations.per_relation_prose` absent or false ⇒ STU-492 behavior exactly. Goldens and smoke tests must stay green with no update.
- **Gating key = `max(chapters)`** per relation (last chapter of the arc).
- **French prose, never English verbatim** — the per-relation prompt reformulates the English `evolution`/`key_moments`/`evidence` into French.
- **Leave-open default** on unmatched headings (LLM drift tolerance), same as `wrap_collapsible`.
- Collapsible attributes match STU-492 exactly: `<div class="mw-collapsible mw-collapsed" data-expandtext="Chapitre {n} — révéler" data-collapsetext="Masquer">`.
- Spec: `docs/superpowers/specs/2026-07-14-stu-494-per-relation-progression-design.md`.

---

### Task 1: `relation_units` provenance helper

**Files:**
- Modify: `wiki_creator/provenance.py`
- Test: `tests/test_provenance.py`

**Interfaces:**
- Consumes: `chapter_number` (already imported in `provenance.py`).
- Produces: `relation_units(entity: dict) -> list[dict]` — one `{"name": <other entity>, "revealed_at_chapter": <max chapter int>}` per typed relationship; typed only; empty when none.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_provenance.py`:

```python
from wiki_creator.provenance import relation_units


def _rel_entity():
    return {
        "canonical_name": "Chaol",
        "aliases": ["Captain Westfall"],
        "relationships": [
            {"entity_a": "Chaol", "entity_b": "Celaena",
             "relationship_type": "amoureux", "chapters": ["ch01", "ch55"]},
            {"entity_a": "Cain", "entity_b": "Captain Westfall",
             "relationship_type": "antagoniste", "chapters": ["ch07"]},
            {"entity_a": "Chaol", "entity_b": "Dorian",
             "relationship_type": None, "chapters": ["ch02"]},
            {"entity_a": "Chaol", "entity_b": "Nox",
             "relationship_type": "ami", "chapters": []},
        ],
    }


def test_relation_units_uses_max_chapter_and_other_name():
    units = relation_units(_rel_entity())
    assert units == [
        {"name": "Celaena", "revealed_at_chapter": 55},
        {"name": "Cain", "revealed_at_chapter": 7},
    ]


def test_relation_units_empty_when_no_typed_with_chapters():
    assert relation_units({"canonical_name": "X", "relationships": []}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_provenance.py -k relation_units -v`
Expected: FAIL with `ImportError: cannot import name 'relation_units'`

- [ ] **Step 3: Implement `relation_units`**

Append to `wiki_creator/provenance.py`:

```python
def relation_units(entity: dict) -> list[dict]:
    """One ``{name, revealed_at_chapter}`` row per typed relationship.

    ``name`` = the pair's other entity; ``revealed_at_chapter`` = ``max`` over
    the relation's chapters (last chapter of the arc — the gating key). Typed
    relationships with at least one resolvable chapter only; empty when none.
    """
    own = {entity.get("canonical_name")} | set(entity.get("aliases") or [])
    rows = []
    for rel in entity.get("relationships") or []:
        if not rel.get("relationship_type"):
            continue
        chapters = [n for n in (chapter_number(k) for k in rel.get("chapters") or []) if n is not None]
        if not chapters:
            continue
        other = rel["entity_b"] if rel.get("entity_a") in own else rel["entity_a"]
        rows.append({"name": other, "revealed_at_chapter": max(chapters)})
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_provenance.py -k relation_units -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/provenance.py tests/test_provenance.py
git commit -m "feat(provenance): relation_units for per-relation gating (STU-494)"
```

---

### Task 2: `wrap_relation_collapsibles` render helper

**Files:**
- Modify: `wiki_creator/spoiler_blocks.py`
- Test: `tests/test_spoiler_blocks.py`

**Interfaces:**
- Consumes: existing `_split_sections`, `_heading_of`, `_norm`, `_RELATIONS_TITLE` in `spoiler_blocks.py`.
- Produces: `wrap_relation_collapsibles(body: str, relation_units: list[dict], collapse_after: int) -> str` — within the `== Relations ==` section, wraps each `=== [[Name]] ===` subsection whose matched `revealed_at_chapter > collapse_after` in an mw-collapsible div; unmatched / `None` / `<= collapse_after` left untouched.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spoiler_blocks.py`:

```python
from wiki_creator.spoiler_blocks import wrap_relation_collapsibles

_REL_BODY = (
    "== Relations ==\n\n"
    "=== [[Celaena]] ===\n\nProse arc jusqu'à la fin.\n\n"
    "=== [[Cain]] ===\n\nRival de la compétition.\n\n"
    "== Anecdotes ==\n\nFait divers.\n"
)


def test_wrap_relation_gates_subsection_above_threshold():
    units = [{"name": "Celaena", "revealed_at_chapter": 55},
             {"name": "Cain", "revealed_at_chapter": 2}]
    out = wrap_relation_collapsibles(_REL_BODY, units, collapse_after=3)
    # Celaena (55 > 3) wrapped; Cain (2 <= 3) not
    assert 'data-expandtext="Chapitre 55 — révéler"' in out
    assert out.count("mw-collapsible") == 1
    assert "=== [[Cain]] ===" in out.split("mw-collapsible")[0] or "Cain" in out
    # Anecdotes (outside Relations) never wrapped
    assert "Fait divers." in out
    assert out.index("Fait divers.") > out.index("mw-collapsible")


def test_wrap_relation_boundary_is_strict():
    units = [{"name": "Celaena", "revealed_at_chapter": 3}]
    out = wrap_relation_collapsibles(_REL_BODY, units, collapse_after=3)
    assert "mw-collapsible" not in out


def test_wrap_relation_unmatched_and_none_left_open():
    units = [{"name": "Celaena", "revealed_at_chapter": None},
             {"name": "Ghost", "revealed_at_chapter": 99}]
    out = wrap_relation_collapsibles(_REL_BODY, units, collapse_after=3)
    assert "mw-collapsible" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spoiler_blocks.py -k relation -v`
Expected: FAIL with `ImportError: cannot import name 'wrap_relation_collapsibles'`

- [ ] **Step 3: Implement `wrap_relation_collapsibles`**

`spoiler_blocks.py` already has module-level `_SUBHEADING_RE`? It does not — add one and the function. Append to `wiki_creator/spoiler_blocks.py`:

```python
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


def wrap_relation_collapsibles(body: str, relation_units: list[dict], collapse_after: int) -> str:
    """Wrap each ``=== [[Name]] ===`` subsection of the Relations section whose
    relation is revealed after ``collapse_after`` in an mw-collapsible div.

    Matching is by the normalized name inside ``[[ ]]`` against ``relation_units``.
    Subsections with no match, a ``None`` chapter, or a chapter ``<= collapse_after``
    are left untouched — same leave-open default as ``wrap_collapsible``.
    """
    chapter_by_name = {_norm(u["name"]): u.get("revealed_at_chapter") for u in relation_units}
    blocks = _split_sections(body)
    out = [blocks[0]]
    for block in blocks[1:]:
        heading = _heading_of(block)
        if not heading or _norm(heading) != _RELATIONS_TITLE:
            out.append(block)
            continue
        subs = _split_subsections(block)
        wrapped = [subs[0]]
        for sub in subs[1:]:
            name = _subheading_name(sub)
            chapter = chapter_by_name.get(_norm(name)) if name else None
            if chapter is not None and chapter > collapse_after:
                wrapped.append(
                    f'<div class="mw-collapsible mw-collapsed" '
                    f'data-expandtext="Chapitre {chapter} — révéler" '
                    f'data-collapsetext="Masquer">\n{sub.rstrip()}\n</div>\n'
                )
            else:
                wrapped.append(sub)
        out.append("".join(wrapped))
    return "".join(out)
```

Note: `_norm` lowercases and strips `=`; on a name like `Celaena` it returns `celaena`, matching the unit name normalized the same way.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spoiler_blocks.py -k relation -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/spoiler_blocks.py tests/test_spoiler_blocks.py
git commit -m "feat(spoiler): wrap_relation_collapsibles for per-relation gating (STU-494)"
```

---

### Task 3: Config reader for the feature flag

**Files:**
- Modify: `wiki_creator/spoiler_blocks.py`
- Test: `tests/test_spoiler_blocks.py`

**Interfaces:**
- Produces: `per_relation_prose_enabled(book_cfg: dict) -> bool` — reads `generation.relations.per_relation_prose`, default `False`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_spoiler_blocks.py`:

```python
from wiki_creator.spoiler_blocks import per_relation_prose_enabled


def test_per_relation_prose_enabled_reads_flag():
    cfg = {"generation": {"relations": {"per_relation_prose": True}}}
    assert per_relation_prose_enabled(cfg) is True


def test_per_relation_prose_enabled_defaults_false():
    assert per_relation_prose_enabled({}) is False
    assert per_relation_prose_enabled({"generation": {}}) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spoiler_blocks.py -k per_relation_prose_enabled -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Implement the reader**

Append to `wiki_creator/spoiler_blocks.py` (next to `spoiler_collapse_after`):

```python
def per_relation_prose_enabled(book_cfg: dict) -> bool:
    return bool(
        ((book_cfg.get("generation") or {}).get("relations") or {}).get("per_relation_prose")
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spoiler_blocks.py -k per_relation_prose_enabled -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/spoiler_blocks.py tests/test_spoiler_blocks.py
git commit -m "feat(spoiler): per_relation_prose_enabled config reader (STU-494)"
```

---

### Task 4: Single-relation prompt builder

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_sectioned.py`

**Interfaces:**
- Consumes: `_relationship_evidence_lines(rel)` (existing), `SECTION_TITLES` (imported as `_SECTION_TITLES`).
- Produces: `build_relation_prompt(entity: dict, other: str, rel: dict, book_title: str, forbidden_names: list[str] | None = None) -> str` — prompt for one `### [[other]]` French progression subsection grounded on `rel`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_generate_wiki_pages_sectioned.py`:

```python
def test_build_relation_prompt_grounds_and_requires_french():
    entity = {"canonical_name": "Chaol", "type": "PERSON"}
    rel = {"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux",
           "evolution": "Evolves from antagonism to trust.",
           "key_moments": ["ch10: sparring"], "evidence": "He watched her fight."}
    p = gwp.build_relation_prompt(entity, "Celaena", rel, "ToG", forbidden_names=["Nehemia"])
    assert "Celaena" in p
    assert "amoureux" in p
    assert "Evolves from antagonism to trust." in p          # grounding present
    assert "français" in p.lower() or "french" in p.lower()  # FR instruction
    assert "### [[Celaena]]" in p                             # heading format specified
    assert "Nehemia" in p                                     # forbidden name surfaced
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -k build_relation_prompt -v`
Expected: FAIL with `AttributeError: module 'scripts.generate_wiki_pages' has no attribute 'build_relation_prompt'`

- [ ] **Step 3: Implement `build_relation_prompt`**

Add to `scripts/generate_wiki_pages.py` (near `build_prompt`, after `_relationship_evidence_lines`):

```python
def build_relation_prompt(
    entity: dict,
    other: str,
    rel: dict,
    book_title: str,
    forbidden_names: list[str] | None = None,
) -> str:
    """Prompt for a single ``### [[other]]`` French progression subsection.

    Grounds on this one relation's type / evolution / key_moments / evidence and
    requires French prose — the grounding fields are English and must be
    reformulated, never copied verbatim.
    """
    name = entity["canonical_name"]
    rtype = rel.get("relationship_type") or "relation"
    grounding = "\n".join(_relationship_evidence_lines(rel)) or "    (no extra grounding)"
    forbidden_rule = ""
    if forbidden_names:
        names_list = "\n".join(f"- {n}" for n in forbidden_names)
        forbidden_rule = (
            "\n\nNE JAMAIS mentionner ces personnages (spoilers d'autres tomes) :\n"
            f"{names_list}"
        )
    return f"""Rédige UNE sous-section wiki en français décrivant la progression de la relation entre {name} et {other} dans « {book_title} ».

Type de relation : {rtype}
Éléments d'ancrage (en anglais — À REFORMULER EN FRANÇAIS, ne jamais recopier tel quel) :
{grounding}

Contraintes :
- Écris en français uniquement. Les éléments d'ancrage sont en anglais : traduis et reformule, ne copie aucune phrase anglaise.
- Un seul paragraphe court, ancré uniquement sur les éléments ci-dessus. N'invente rien.
- Commence EXACTEMENT par le titre : ### [[{other}]]
- Ne mentionne aucun autre personnage que {name} et {other}.{forbidden_rule}"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -k build_relation_prompt -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_sectioned.py
git commit -m "feat(pages): build_relation_prompt for per-relation FR prose (STU-494)"
```

---

### Task 5: `prompt_override` threading + per-relation generators

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_sectioned.py`

**Interfaces:**
- Consumes: `_run_wiki_page_item`, `_wiki_page_item_input`, `_check_forbidden_names`, `build_relation_prompt`, `relationship_index_lines` name-selection logic.
- Produces:
  - `_wiki_page_item_input(..., prompt_override: str | None = None)` — uses `prompt_override` as the prompt when set.
  - `_run_wiki_page_item(..., prompt_override: str | None = None)` — passes it through.
  - `_generate_one_relation(*, entity, other, rel, book_title, model, timeout, max_tokens, forbidden_names=None, language="fr", file_path="", grounding=None, runner=None) -> str | None` — one LLM call, isolates the `### [[other]]` prose, forbidden-name check + one retry; `None` on failure/persistent hit.
  - `_generate_relationships_subsections(*, entity, book_title, model, timeout, max_tokens, forbidden_names=None, language="fr", file_path="", grounding=None, runner=None) -> str | None` — full `## Relations` block of concatenated subsections, or `None` when none produced.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_generate_wiki_pages_sectioned.py`:

```python
def test_prompt_override_used_when_set():
    item = gwp._wiki_page_item_input(entity={"canonical_name": "A"}, book_title="B",
                                     sections=["relationships"], max_tokens=500,
                                     prompt_override="CUSTOM PROMPT")
    assert item["prompt"] == "CUSTOM PROMPT"


def test_generate_one_relation_returns_prose(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_item("### [[Celaena]]\n\nLeur méfiance mue en respect."))
    out = gwp._generate_one_relation(
        entity={"canonical_name": "Chaol", "type": "PERSON"}, other="Celaena",
        rel={"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux"},
        book_title="ToG", model="m", timeout=10, max_tokens=500)
    assert out == "### [[Celaena]]\n\nLeur méfiance mue en respect."


def test_generate_one_relation_omits_on_persistent_forbidden(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_item("### [[Celaena]]\n\nNehemia meurt."))
    out = gwp._generate_one_relation(
        entity={"canonical_name": "Chaol", "type": "PERSON"}, other="Celaena",
        rel={"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux"},
        book_title="ToG", model="m", timeout=10, max_tokens=500, forbidden_names=["Nehemia"])
    assert out is None


def test_generate_relationships_subsections_concatenates(monkeypatch):
    entity = {"canonical_name": "Chaol", "type": "PERSON", "aliases": [],
              "relationships": [
                  {"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux",
                   "chapters": ["ch55"]},
                  {"entity_a": "Cain", "entity_b": "Chaol", "relationship_type": "antagoniste",
                   "chapters": ["ch07"]},
                  {"entity_a": "Chaol", "entity_b": "Nox", "relationship_type": None,
                   "chapters": ["ch02"]}]}
    monkeypatch.setattr(gwp, "_generate_one_relation",
                        lambda **kw: f"### [[{kw['other']}]]\n\nprose {kw['other']}")
    out = gwp._generate_relationships_subsections(
        entity=entity, book_title="ToG", model="m", timeout=10, max_tokens=500)
    assert out.startswith("## Relations")
    assert "### [[Celaena]]" in out and "### [[Cain]]" in out
    assert "Nox" not in out  # untyped relation skipped
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -k "prompt_override or one_relation or subsections" -v`
Expected: FAIL (attributes / param missing)

- [ ] **Step 3: Implement threading + generators**

3a. In `_wiki_page_item_input`, add the parameter and use it. Change the signature line and the `prompt` assignment:

```python
def _wiki_page_item_input(
    *,
    entity: dict,
    book_title: str,
    sections: list[str],
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    prompt_override: str | None = None,
) -> dict:
```

and replace the `"prompt": build_prompt(...)` line with:

```python
        "prompt": prompt_override or build_prompt(entity, book_title, sections=sections, forbidden_names=forbidden_names),
```

3b. In `_run_wiki_page_item`, add `prompt_override: str | None = None` to the signature (after `grounding`) and pass `prompt_override=prompt_override` into the `_wiki_page_item_input(...)` call.

3c. Add the two generators after `_generate_one_section`:

```python
def _generate_one_relation(
    *,
    entity: dict,
    other: str,
    rel: dict,
    book_title: str,
    model: str,
    timeout: int,
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    runner: StudioRunner | None = None,
) -> str | None:
    """Generate one ``### [[other]]`` French progression subsection. Returns the
    subsection markdown, or None on error / persistent forbidden-name hit."""
    prompt = build_relation_prompt(entity, other, rel, book_title, forbidden_names=forbidden_names)

    def _once() -> dict:
        return _run_wiki_page_item(
            entity=entity, book_title=book_title, model=model, timeout=timeout,
            sections=["relationships"], max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding, runner=runner,
            prompt_override=prompt,
        )

    result = _once()
    if not isinstance(result, dict) or result.get("error"):
        return None
    content = (result.get("content") or "").strip()
    if forbidden_names and _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
        result = _once()
        if not isinstance(result, dict) or result.get("error"):
            return None
        content = (result.get("content") or "").strip()
        if _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
            return None
    return content or None


def _generate_relationships_subsections(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
    runner: StudioRunner | None = None,
) -> str | None:
    """The full ``## Relations`` block: one prose subsection per typed relationship
    (most-recent-reveal first). None when no subsection is produced."""
    own = {entity.get("canonical_name")} | set(entity.get("aliases") or [])
    typed = []
    for rel in entity.get("relationships") or []:
        if not rel.get("relationship_type"):
            continue
        chapters = [n for n in (chapter_number(k) for k in rel.get("chapters") or []) if n is not None]
        other = rel["entity_b"] if rel.get("entity_a") in own else rel["entity_a"]
        typed.append((max(chapters) if chapters else -1, other, rel))
    typed.sort(key=lambda t: t[0], reverse=True)
    subs = []
    for _, other, rel in typed:
        block = _generate_one_relation(
            entity=entity, other=other, rel=rel, book_title=book_title, model=model,
            timeout=timeout, max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding, runner=runner,
        )
        if block:
            subs.append(block)
    if not subs:
        return None
    return "## Relations\n\n" + "\n\n".join(subs)
```

Add `from wiki_creator.chapters import chapter_number` to the imports at the top of `scripts/generate_wiki_pages.py` if not already present (check the import block near line 34).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -k "prompt_override or one_relation or subsections" -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_sectioned.py
git commit -m "feat(pages): per-relation subsection generators + prompt_override (STU-494)"
```

---

### Task 6: Wire the feature into sectioned generation

**Files:**
- Modify: `scripts/generate_wiki_pages.py` (`_run_generation_sectioned`)
- Test: `tests/test_generate_wiki_pages_sectioned.py`

**Interfaces:**
- Consumes: `per_relation_prose_enabled`, `relation_units` (import both), `_generate_relationships_subsections`.
- Produces: when the flag is on and the entity is a PERSON with typed relationships, the `relationships` section is generated via `_generate_relationships_subsections`, excluded from `content_units`, `page["relation_units"]` is attached, and `page["relationship_index"]` is set to `[]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_generate_wiki_pages_sectioned.py`:

```python
def test_sectioned_per_relation_prose_when_enabled(monkeypatch):
    entity = _entity(rels=[
        {"entity_a": "Chaol", "entity_b": "Celaena", "relationship_type": "amoureux",
         "chapters": ["ch55"]},
        {"entity_a": "Cain", "entity_b": "Chaol", "relationship_type": "antagoniste",
         "chapters": ["ch07"]}])
    def fake(**kw):
        sec = kw["sections"][0]
        if sec == "relationships" and kw.get("prompt_override"):
            other = "Celaena" if "Celaena" in kw["prompt_override"] else "Cain"
            return _fake_item(f"### [[{other}]]\n\nprose {other}")
        return _fake_item(f"## {sec}\n\ntext")
    monkeypatch.setattr(gwp, "_run_wiki_page_item", fake)
    from pathlib import Path
    cfg = {"generation": {"relations": {"per_relation_prose": True}}}
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "relationships", "references"],
        max_tokens=500, dry_run=False, debug_dir=Path("/tmp"), book_config=cfg)
    assert "## Relations\n\n### [[Celaena]]" in page["content"]
    assert "### [[Cain]]" in page["content"]
    assert page["relation_units"] == [
        {"name": "Celaena", "revealed_at_chapter": 55},
        {"name": "Cain", "revealed_at_chapter": 7}]
    # relationships excluded from content_units; index dropped
    assert all(u["section"] != "relationships" for u in page["content_units"])
    assert page["relationship_index"] == []


def test_sectioned_per_relation_off_keeps_single_block(monkeypatch):
    entity = _entity(rels=[{"entity_a": "Chaol", "entity_b": "Celaena",
                            "relationship_type": "amoureux", "chapters": ["ch55"]}])
    _sectioned(monkeypatch, {"relationships": "## Relations\n\nProse unique."})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=entity, book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "relationships", "references"],
        max_tokens=500, dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert "Prose unique." in page["content"]
    assert "relation_units" not in page
    assert page["relationship_index"]  # STU-492 index still built
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -k "per_relation_prose_when or per_relation_off" -v`
Expected: FAIL (`relation_units` KeyError / content mismatch)

- [ ] **Step 3: Implement the wiring**

3a. Add imports near the existing `from wiki_creator.spoiler_blocks import relationship_index_lines` (line ~38):

```python
from wiki_creator.spoiler_blocks import relationship_index_lines, per_relation_prose_enabled
from wiki_creator.provenance import content_units, relation_units
```

(Merge with the existing `from wiki_creator.provenance import content_units` line — don't duplicate the import.)

3b. In `_run_generation_sectioned`, compute the flag once and branch the relationships section inside the loop. Replace the loop body:

```python
    content_sections = [s for s in sections if s not in ("infobox", "references")]
    per_relation = (
        entity.get("type") == "PERSON"
        and per_relation_prose_enabled(book_config or {})
        and bool(relation_units(entity))
    )
    blocks: list[str] = []
    emitted: list[str] = []
    for section in content_sections:
        if section == "relationships" and per_relation:
            block = _generate_relationships_subsections(
                entity=entity, book_title=book_title, model=model, timeout=timeout,
                max_tokens=max_tokens, forbidden_names=forbidden_names,
                language=language, file_path=file_path, grounding=grounding, runner=runner,
            )
            if block:
                blocks.append(block)
                # NOTE: 'relationships' deliberately NOT appended to `emitted`
                # so it is excluded from content_units — per-relation gating
                # (relation_units) replaces whole-section gating.
            continue
        block = _generate_one_section(
            entity=entity, section=section, book_title=book_title, model=model,
            timeout=timeout, max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding, runner=runner,
        )
        if block:
            blocks.append(block)
            emitted.append(section)
        elif section == "biography":
            _save_generation_debug_artifact(debug_dir, entity, {"error": "biography_failed"})
            return make_stub_page(entity, failed=True)
```

3c. After the `page = { ... }` dict is built (the block ending with `"relationship_index": relationship_index_lines(entity)`), add per-relation fields:

```python
    if per_relation:
        page["relation_units"] = relation_units(entity)
        page["relationship_index"] = []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -v`
Expected: PASS (all, including pre-existing sectioned tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_sectioned.py
git commit -m "feat(pages): wire per-relation prose into sectioned generation (STU-494)"
```

---

### Task 7: Wire per-relation rendering into export

**Files:**
- Modify: `scripts/wiki_export.py` (`render_page`)
- Test: `tests/test_wiki_export.py`

**Interfaces:**
- Consumes: `wrap_relation_collapsibles` (add to the existing `from wiki_creator.spoiler_blocks import ...` block).
- Produces: `render_page` renders per-relation collapsibles and skips the dated index when `page["relation_units"]` is present.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wiki_export.py` (mirror the module's existing `render_page` test style — reuse its `labels` fixture/dict shape):

```python
def test_render_page_per_relation_collapsibles():
    page = {
        "title": "Chaol",
        "entity_type": "PERSON",
        "importance": "principal",
        "infobox_fields": {},
        "content": ("## Relations\n\n"
                    "### [[Celaena]]\n\nProse arc.\n\n"
                    "### [[Cain]]\n\nRival.\n"),
        "relation_units": [{"name": "Celaena", "revealed_at_chapter": 55},
                           {"name": "Cain", "revealed_at_chapter": 2}],
        "relationship_index": [],
    }
    from scripts.wiki_export import render_page
    _, out = render_page(page, {}, collapse_after=3)
    assert 'data-expandtext="Chapitre 55 — révéler"' in out  # Celaena gated
    assert out.count("mw-collapsible") == 1                   # Cain (2<=3) not gated
    assert "''Évolution :''" not in out                       # dated index dropped


def test_render_page_per_relation_no_collapse_config():
    page = {
        "title": "Chaol", "entity_type": "PERSON", "importance": "principal",
        "infobox_fields": {},
        "content": "## Relations\n\n### [[Celaena]]\n\nProse.\n",
        "relation_units": [{"name": "Celaena", "revealed_at_chapter": 55}],
        "relationship_index": [],
    }
    from scripts.wiki_export import render_page
    _, out = render_page(page, {}, collapse_after=None)
    assert "=== [[Celaena]] ===" in out
    assert "mw-collapsible" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wiki_export.py -k per_relation -v`
Expected: FAIL (`ImportError` / index still injected / no collapsible)

- [ ] **Step 3: Implement the wiring**

3a. Add `wrap_relation_collapsibles` to the import block at the top of `scripts/wiki_export.py`:

```python
from wiki_creator.spoiler_blocks import (
    wrap_collapsible,
    wrap_relation_collapsibles,
    inject_relationship_index,
    spoiler_collapse_after,
)
```

3b. In `render_page`, replace the body-building lines (90–93) with a per-relation branch:

```python
    body = convert(page.get("content", ""))
    relation_units = page.get("relation_units")
    if relation_units:
        if collapse_after is not None:
            body = wrap_relation_collapsibles(body, relation_units, collapse_after)
    else:
        body = inject_relationship_index(body, page.get("relationship_index") or [])
        if collapse_after is not None:
            body = wrap_collapsible(body, page.get("content_units") or [], collapse_after)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wiki_export.py -k per_relation -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add scripts/wiki_export.py tests/test_wiki_export.py
git commit -m "feat(export): render per-relation collapsibles, drop index when set (STU-494)"
```

---

### Task 8: Full-suite regression + golden safety

**Files:**
- None (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: PASS — `1113 passed, 37 skipped` plus the new tests (no regressions, no golden updates). If any golden test fails, the opt-in wiring leaked into the default path — fix so that `per_relation_prose` absent leaves output byte-identical.

- [ ] **Step 2: Type-check**

Run: `mypy wiki_creator/`
Expected: no new errors.

- [ ] **Step 3: Golden regression**

Run: `make golden`
Expected: PASS with no diff (the fixture book sets no `per_relation_prose`).

- [ ] **Step 4: Commit (only if any incidental fix was needed)**

```bash
git add -A
git commit -m "test: STU-494 full-suite regression green"
```

---

## Self-Review

**Spec coverage:**
- Relations restructured into `=== [[Name]] ===` subsections → Tasks 5–6 (generation) + 7 (render).
- French progression prose grounded on evolution/key_moments/evidence → Task 4 prompt + Task 5 generators.
- Per-relation `mw-collapsible` gating on `max(chapters)` → Task 1 (`relation_units` max) + Task 2 (`wrap_relation_collapsibles`) + Task 7 (render).
- Dated index dropped for these pages → Task 6 (`relationship_index=[]`) + Task 7 (skip inject).
- Feature flag, byte-identical when off → Task 3 reader + Task 6 branch + Task 8 golden verify.
- forbidden_names per relation → Task 4 prompt rule + Task 5 check/retry.
- PERSON only → Task 6 `entity.get("type") == "PERSON"` guard.

**Placeholder scan:** none — every code step shows full code.

**Type consistency:** `relation_units` returns `{name, revealed_at_chapter}` used identically in Tasks 1/2/6/7. `_generate_relationships_subsections` / `_generate_one_relation` signatures match their call sites. `prompt_override` param name consistent across `_wiki_page_item_input`, `_run_wiki_page_item`, `_generate_one_relation`.
