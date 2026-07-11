# Wiki Page Templates — Slice E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate each prose section in its own scoped `wiki-page-item` call and assemble them, with per-section forbidden validation and graceful per-section degradation.

**Architecture:** Two pure helpers (`_assemble_section_blocks`, `_references_block`) plus `_generate_one_section` (one scoped call + per-section forbidden retry) drive a NEW `_run_generation_sectioned` that loops over the content sections; the main loop switches to it. `_run_generation_for_entity` is left unchanged (superseded, cleanup fast-follow) so its tests stay green. Reuses the existing `_run_wiki_page_item`, `_check_forbidden_names`, `_strip_relations_section`, `_force_correct_identity`, `_bind_batch_fields`.

**Tech Stack:** Python 3, `pytest` with monkeypatch (mock the `_run_wiki_page_item` subprocess boundary).

## Global Constraints

- `_run_wiki_page_item` is the subprocess boundary — tests MUST mock it (monkeypatch `scripts.generate_wiki_pages._run_wiki_page_item`), never invoke `studio`.
- Graceful degradation: a failed OPT section is omitted; a failed `biography` (MIN) → failed stub; zero blocks → failed stub.
- `references` is assembled deterministically (`## Références` + `- {book_title}`), no LLM call.
- The sectioned path does NOT call `_recover_identity_rejected_page` (approved simplification); `_force_correct_identity` (PERSON) + `_bind_batch_fields` still run once on the assembled page.
- `_run_generation_sectioned` has the SAME signature as `_run_generation_for_entity`; only the main-loop call site (line ~1172) switches to it. `_run_generation_for_entity` stays unchanged and its tests must remain untouched.
- Baseline: current `main` full suite green (report actual numbers). Run `pytest -q` before each commit.

---

### Task 1: Pure assembly + references helpers

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_sectioned.py` (new)

**Interfaces:**
- Produces: `_assemble_section_blocks(blocks: list[str]) -> str`; `_references_block(book_title: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_generate_wiki_pages_sectioned.py`:

```python
import scripts.generate_wiki_pages as gwp


def test_assemble_joins_nonempty_blocks_with_blank_line():
    blocks = ["## Biographie\n\nTexte.", "  ", "", "## Anecdotes\n\nFait."]
    out = gwp._assemble_section_blocks(blocks)
    assert out == "## Biographie\n\nTexte.\n\n## Anecdotes\n\nFait."


def test_assemble_empty_is_empty_string():
    assert gwp._assemble_section_blocks([]) == ""
    assert gwp._assemble_section_blocks(["", "   "]) == ""


def test_references_block_lists_only_book_title():
    assert gwp._references_block("Throne of Glass") == "## Références\n\n- Throne of Glass"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_assemble_section_blocks'`.

- [ ] **Step 3: Write minimal implementation**

Add to `scripts/generate_wiki_pages.py` (near the other content helpers, e.g. after `_content_template_for_sections`):

```python
def _assemble_section_blocks(blocks: list[str]) -> str:
    """Join non-empty section markdown blocks with a blank line."""
    return "\n\n".join(b.strip() for b in blocks if b and b.strip())


def _references_block(book_title: str) -> str:
    """Deterministic References section — lists only the book title (no LLM)."""
    return f"## {_SECTION_TITLES['references']}\n\n- {book_title}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_sectioned.py
git commit -m "feat(generation): section-block assembly + deterministic references (slice E)"
```

---

### Task 2: `_generate_one_section` — one scoped call + per-section forbidden retry

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_sectioned.py`

**Interfaces:**
- Consumes: `_run_wiki_page_item`, `_check_forbidden_names`, `_strip_relations_section`.
- Produces: `_generate_one_section(*, entity, section, book_title, model, timeout, max_tokens, forbidden_names=None, language="fr", file_path="", grounding=None) -> str | None` — the section's content block, or None on error / persistent forbidden hit / empty.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_generate_wiki_pages_sectioned.py`:

```python
def _fake_item(content):
    return {"title": "X", "importance": "principal", "entity_type": "PERSON",
            "infobox_fields": {}, "content": content}


def test_generate_one_section_returns_content(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_item("## Biographie\n\nTexte."))
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out == "## Biographie\n\nTexte."


def test_generate_one_section_none_on_error(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item", lambda **kw: {"error": "studio_run_failed"})
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="powers",
                                    book_title="B", model="m", timeout=10, max_tokens=500)
    assert out is None


def test_generate_one_section_scopes_to_single_section(monkeypatch):
    seen = {}
    def fake(**kw):
        seen["sections"] = kw["sections"]
        return _fake_item("## Anecdotes\n\nFait.")
    monkeypatch.setattr(gwp, "_run_wiki_page_item", fake)
    gwp._generate_one_section(entity={"canonical_name": "A"}, section="trivia",
                              book_title="B", model="m", timeout=10, max_tokens=500)
    assert seen["sections"] == ["trivia"]


def test_generate_one_section_omits_on_persistent_forbidden(monkeypatch):
    monkeypatch.setattr(gwp, "_run_wiki_page_item",
                        lambda **kw: _fake_item("## Biographie\n\nNehemia dies."))
    out = gwp._generate_one_section(entity={"canonical_name": "A"}, section="biography",
                                    book_title="B", model="m", timeout=10, max_tokens=500,
                                    forbidden_names=["Nehemia"])
    assert out is None   # one retry attempted, still hit → omit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -k one_section -v`
Expected: FAIL — `_generate_one_section` undefined.

- [ ] **Step 3: Write the implementation**

Add to `scripts/generate_wiki_pages.py`:

```python
def _generate_one_section(
    *,
    entity: dict,
    section: str,
    book_title: str,
    model: str,
    timeout: int,
    max_tokens: int,
    forbidden_names: list[str] | None = None,
    language: str = "fr",
    file_path: str = "",
    grounding: dict | None = None,
) -> str | None:
    """Generate a single section via a scoped wiki-page-item call. Returns the
    section's content block, or None on error / persistent forbidden-name hit."""

    def _once() -> dict:
        return _run_wiki_page_item(
            entity=entity, book_title=book_title, model=model, timeout=timeout,
            sections=[section], max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding,
        )

    result = _once()
    if not isinstance(result, dict) or result.get("error"):
        return None
    content = result.get("content") or ""
    if section == "relationships" and not entity.get("relationships"):
        content = _strip_relations_section(content)
    if forbidden_names and _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
        result = _once()
        if not isinstance(result, dict) or result.get("error"):
            return None
        content = result.get("content") or ""
        if section == "relationships" and not entity.get("relationships"):
            content = _strip_relations_section(content)
        if _check_forbidden_names({"content": content, "infobox_fields": {}}, forbidden_names):
            return None
    content = content.strip()
    return content or None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -k one_section -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_sectioned.py
git commit -m "feat(generation): per-section scoped generation helper (slice E)"
```

---

### Task 3: Add `_run_generation_sectioned` + switch the main loop (additive)

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages_sectioned.py`

**Interfaces:**
- Consumes: `_generate_one_section`, `_assemble_section_blocks`, `_references_block`, `_force_correct_identity`, `_bind_batch_fields` (all above / existing).
- Produces: **new** `_run_generation_sectioned(...)` with the SAME signature as `_run_generation_for_entity`, looping over content sections. The main-loop call site switches to it. `_run_generation_for_entity` is left UNCHANGED (superseded; its existing tests keep passing untouched).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_generate_wiki_pages_sectioned.py`:

```python
def _entity(rels=None):
    return {"canonical_name": "Chaol", "type": "PERSON", "importance": "principal",
            "aliases": ["Captain Westfall"], "titles": ["Captain"],
            "context_by_chapter": {"C01": ["ctx"]}, "relationships": rels or []}


def _sectioned(monkeypatch, produced):
    # produced: dict section -> content string, or None to simulate failure
    calls = []
    def fake(**kw):
        sec = kw["sections"][0]
        calls.append(sec)
        val = produced.get(sec, f"## {sec}\n\ntext")
        return {"error": "x"} if val is None else _fake_item(val)
    monkeypatch.setattr(gwp, "_run_wiki_page_item", fake)
    return calls


def test_sectioned_calls_once_per_content_section_and_assembles(monkeypatch):
    calls = _sectioned(monkeypatch, {"biography": "## Biographie\n\nBio."})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=_entity(), book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "references"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert calls == ["biography"]                       # infobox + references not LLM'd
    assert "## Biographie" in page["content"]
    assert "## Références\n\n- ToG" in page["content"]   # deterministic refs
    assert page["infobox_fields"]["nom"] == "Chaol"     # slice-B binding still applied
    assert page["infobox_fields"]["titles"] == "Captain"


def test_sectioned_biography_failure_returns_stub(monkeypatch):
    _sectioned(monkeypatch, {"biography": None})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=_entity(), book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "references"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert page.get("_failed") is True


def test_sectioned_omits_failed_optional_section(monkeypatch):
    _sectioned(monkeypatch, {"biography": "## Biographie\n\nBio.", "powers": None})
    from pathlib import Path
    page = gwp._run_generation_sectioned(
        entity=_entity(), book_title="ToG", model="m", timeout=10,
        sections=["infobox", "biography", "powers", "references"], max_tokens=500,
        dry_run=False, debug_dir=Path("/tmp"), book_config={})
    assert page.get("_failed") is not True
    assert "## Biographie" in page["content"]
    assert "powers" not in page["content"]              # failed OPT section omitted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -k sectioned -v`
Expected: FAIL — the current `_run_generation_for_entity` makes one all-sections call, so `calls` won't equal `["biography"]` and references won't be deterministic.

- [ ] **Step 3: Add the new `_run_generation_sectioned` function**

Add a NEW function `_run_generation_sectioned` (do NOT modify `_run_generation_for_entity`). Give it the identical signature to `_run_generation_for_entity` (`*, entity, book_title, model, timeout, sections, max_tokens, dry_run, debug_dir, forbidden_names=None, language="fr", file_path="", grounding=None, sibling_canonicals=None, book_config=None`) with this body:

```python
    if not entity.get("context_by_chapter", {}):
        return make_stub_page(entity, insufficient_data=True)
    if dry_run:
        return make_stub_page(entity)

    content_sections = [s for s in sections if s not in ("infobox", "references")]
    blocks: list[str] = []
    for section in content_sections:
        block = _generate_one_section(
            entity=entity, section=section, book_title=book_title, model=model,
            timeout=timeout, max_tokens=max_tokens, forbidden_names=forbidden_names,
            language=language, file_path=file_path, grounding=grounding,
        )
        if block:
            blocks.append(block)
        elif section == "biography":
            _save_generation_debug_artifact(debug_dir, entity, {"error": "biography_failed"})
            return make_stub_page(entity, failed=True)
        # else: OPT section omitted

    if not blocks:
        return make_stub_page(entity, failed=True)

    if "references" in sections:
        blocks.append(_references_block(book_title))

    page = {
        "title": entity["canonical_name"],
        "importance": entity["importance"],
        "entity_type": entity["type"],
        "infobox_fields": {},
        "content": _assemble_section_blocks(blocks),
    }
    if entity.get("type") == "PERSON":
        _force_correct_identity(page, entity, sibling_canonicals)
    _bind_batch_fields(page, entity, book_config)
    return page
```

- [ ] **Step 4: Switch the main-loop call site**

In `main()` (the batch loop, call site near line ~1172), change the call from `_run_generation_for_entity(...)` to `_run_generation_sectioned(...)`. Keep every keyword argument identical (same signature). This is the only production wiring change; `_run_generation_for_entity` is now superseded but stays in the file.

- [ ] **Step 5: Run the sectioned tests**

Run: `pytest tests/test_generate_wiki_pages_sectioned.py -v`
Expected: PASS (all).

- [ ] **Step 6: Run the full suite — existing tests must be UNTOUCHED and green**

Run: `pytest tests/test_generate_wiki_pages.py -q` then `pytest -q`
Expected: green with **zero** changes to existing tests. Because `_run_generation_for_entity` is unchanged, its ~10 tests still pass as-is. If any existing test fails, STOP and report — it means the switch touched more than intended (do not "fix" existing tests to make them pass; investigate why the additive change broke them).

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages_sectioned.py
git commit -m "feat(generation): section-scoped page generation with graceful degradation (slice E)"
```

---

## Self-Review

**Spec coverage** (against `2026-07-11-wiki-page-templates-slice-e-design.md`):
- Per-section scoped call + assembly → Tasks 1-3.
- Per-section forbidden validation with one retry → Task 2 (`_generate_one_section`).
- Graceful degradation (omit OPT; biography→stub; zero blocks→stub) → Task 3.
- Deterministic references → Task 1 (`_references_block`) + Task 3 (appended, not LLM'd).
- Drop `_recover_identity_rejected_page` in sectioned path; keep `_force_correct_identity` + `_bind_batch_fields` on assembled page → Task 3.
- Infobox bound once → Task 3 (`_bind_batch_fields`).

**Placeholder scan:** No TBD/TODO; complete code in every code step; real assertions with monkeypatched subprocess boundary.

**Type consistency:** `_generate_one_section(...) -> str | None` and `_assemble_section_blocks(list[str]) -> str` / `_references_block(str) -> str` used consistently across tasks. `_run_generation_sectioned` has the identical signature to `_run_generation_for_entity`, so the main-loop call site switches with the same kwargs. `_run_generation_for_entity` is untouched. Tests mock `_run_wiki_page_item` (the subprocess boundary) — no `studio` invocation.
