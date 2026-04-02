# STU-317: Forbidden Names Guard — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent LLM spoiler hallucinations (e.g. "Aelin Galathynius") in generated wiki pages by adding a deterministic forbidden-names check with one retry and stub fallback.

**Architecture:** Book YAML gains a `validation.forbidden_names` list. `generate_wiki_pages.py` checks LLM output against this list post-generation, retries once with an augmented prompt if spoilers are found, and falls back to a stub. `wiki_page_validator.py` gets the same check for the Studio pipeline path.

**Tech Stack:** Python, pytest, YAML config

---

### Task 1: Add `_check_forbidden_names` detection function

**Files:**
- Modify: `scripts/generate_wiki_pages.py` (after `_strip_relations_section` ~line 406)
- Test: `tests/test_generate_wiki_pages.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_generate_wiki_pages.py`:

```python
from scripts.generate_wiki_pages import _check_forbidden_names


def test_check_forbidden_names_detects_in_content():
    page = {
        "content": "Celaena, aussi connue sous le nom d'Aelin Galathynius, est une assassine.",
        "infobox_fields": {},
    }
    hits = _check_forbidden_names(page, ["Aelin Galathynius", "Aelin"])
    assert "Aelin Galathynius" in hits


def test_check_forbidden_names_detects_in_infobox():
    page = {
        "content": "Texte propre sans spoiler.",
        "infobox_fields": {"alias": "Aelin"},
    }
    hits = _check_forbidden_names(page, ["Aelin Galathynius", "Aelin"])
    assert "Aelin" in hits


def test_check_forbidden_names_case_insensitive():
    page = {
        "content": "Son vrai nom est aelin galathynius.",
        "infobox_fields": {},
    }
    hits = _check_forbidden_names(page, ["Aelin Galathynius"])
    assert "Aelin Galathynius" in hits


def test_check_forbidden_names_returns_empty_when_clean():
    page = {
        "content": "Celaena Sardothien est une assassine.",
        "infobox_fields": {"nom": "Celaena Sardothien"},
    }
    hits = _check_forbidden_names(page, ["Aelin Galathynius", "Aelin"])
    assert hits == []


def test_check_forbidden_names_returns_empty_for_empty_list():
    page = {"content": "N'importe quel contenu.", "infobox_fields": {}}
    hits = _check_forbidden_names(page, [])
    assert hits == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_wiki_pages.py::test_check_forbidden_names_detects_in_content -v`
Expected: FAIL — `ImportError: cannot import name '_check_forbidden_names'`

- [ ] **Step 3: Implement `_check_forbidden_names`**

Add to `scripts/generate_wiki_pages.py` after the `_strip_relations_section` function (~line 406):

```python
def _check_forbidden_names(page: dict, forbidden_names: list[str]) -> list[str]:
    """Return list of forbidden names found in page content or infobox fields."""
    if not forbidden_names:
        return []
    haystack = (page.get("content", "") + " " + str(page.get("infobox_fields", {}))).lower()
    return [name for name in forbidden_names if name.lower() in haystack]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages.py -k "check_forbidden_names" -v`
Expected: all 5 PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(generation): add _check_forbidden_names detection function (STU-317)"
```

---

### Task 2: Add forbidden names block to `build_prompt`

**Files:**
- Modify: `scripts/generate_wiki_pages.py` — `build_prompt` function (line 181) and `_wiki_page_item_input` (line 507)
- Test: `tests/test_generate_wiki_pages.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_generate_wiki_pages.py`:

```python
def test_build_prompt_includes_forbidden_names_block():
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    prompt = build_prompt(entity, "Throne of Glass", sections=["infobox", "biography"],
                          forbidden_names=["Aelin Galathynius", "Aelin"])
    assert "FORBIDDEN NAMES" in prompt
    assert "Aelin Galathynius" in prompt
    assert "Aelin" in prompt


def test_build_prompt_no_forbidden_names_block_when_empty():
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    prompt = build_prompt(entity, "Throne of Glass", sections=["infobox", "biography"],
                          forbidden_names=[])
    assert "FORBIDDEN NAMES" not in prompt


def test_build_prompt_no_forbidden_names_block_when_omitted():
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    prompt = build_prompt(entity, "Throne of Glass", sections=["infobox", "biography"])
    assert "FORBIDDEN NAMES" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_wiki_pages.py::test_build_prompt_includes_forbidden_names_block -v`
Expected: FAIL — `TypeError: build_prompt() got an unexpected keyword argument 'forbidden_names'`

- [ ] **Step 3: Add `forbidden_names` parameter to `build_prompt`**

Modify `scripts/generate_wiki_pages.py`:

1. Change signature at line 181:

```python
def build_prompt(entity: dict, book_title: str, sections: list[str], forbidden_names: list[str] | None = None) -> str:
```

2. Before the final `return` statement (line 315), add the forbidden names block. Insert just before `return f"""This is a fictional world...`:

Build the forbidden names rule string (after the `relations_rule` block, around line 313):

```python
    forbidden_names_rule = ""
    if forbidden_names:
        names_list = "\n".join(f"- {n}" for n in forbidden_names)
        forbidden_names_rule = (
            f"\n\nFORBIDDEN NAMES (spoilers from later books — NEVER use these):\n"
            f"{names_list}\n"
            f"Use ONLY the entity's canonical name and listed aliases. "
            f"Any output containing a forbidden name will be rejected."
        )
```

3. Append `{forbidden_names_rule}` at the end of the WRITING RULES section in the f-string, after the `{section_def_lines}` block (before the `---` separator that precedes the REMINDER line). Add it after the line `{section_def_lines}` (~line 377):

```
{section_def_lines}
{forbidden_names_rule}
```

4. Update `_wiki_page_item_input` (line 507) to accept and pass through `forbidden_names`:

```python
def _wiki_page_item_input(*, entity: dict, book_title: str, sections: list[str], max_tokens: int, forbidden_names: list[str] | None = None) -> dict:
    return {
        "title": entity.get("canonical_name", ""),
        "importance": entity.get("importance", ""),
        "entity_type": entity.get("type", ""),
        "max_tokens": max_tokens,
        "prompt": build_prompt(entity, book_title, sections=sections, forbidden_names=forbidden_names),
    }
```

5. Update `_run_wiki_page_item` (line 517) to accept and pass through `forbidden_names`:

```python
def _run_wiki_page_item(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    sections: list[str],
    max_tokens: int,
    forbidden_names: list[str] | None = None,
) -> dict:
    item_input = _wiki_page_item_input(
        entity=entity,
        book_title=book_title,
        sections=sections,
        max_tokens=max_tokens,
        forbidden_names=forbidden_names,
    )
```

(The rest of `_run_wiki_page_item` stays the same.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages.py -k "build_prompt" -v`
Expected: all PASS (including existing `build_prompt` tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(generation): add forbidden_names parameter to build_prompt (STU-317)"
```

---

### Task 3: Add retry logic in `_run_generation_for_entity`

**Files:**
- Modify: `scripts/generate_wiki_pages.py` — `_run_generation_for_entity` (line 625)
- Test: `tests/test_generate_wiki_pages.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_generate_wiki_pages.py`:

```python
def test_run_generation_retries_on_forbidden_name(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    debug_dir = tmp_path / "debug"
    calls = []

    def fake_runner(**kwargs):
        calls.append(kwargs.get("forbidden_names"))
        if len(calls) == 1:
            return {
                "title": "Celaena Sardothien",
                "importance": "principal",
                "entity_type": "PERSON",
                "infobox_fields": {},
                "content": "Celaena, aussi connue sous le nom d'Aelin Galathynius, est une assassine.",
            }
        return {
            "title": "Celaena Sardothien",
            "importance": "principal",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Celaena Sardothien est une assassine.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
        forbidden_names=["Aelin Galathynius", "Aelin"],
    )

    assert len(calls) == 2
    assert "Aelin" not in page.get("content", "")
    assert page["title"] == "Celaena Sardothien"


def test_run_generation_returns_stub_after_failed_retry(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    debug_dir = tmp_path / "debug"

    def fake_runner(**kwargs):
        return {
            "title": "Celaena Sardothien",
            "importance": "principal",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Celaena, aussi connue sous le nom d'Aelin Galathynius.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
        forbidden_names=["Aelin Galathynius"],
    )

    assert page.get("_failed") is True
    assert page.get("_spoiler_rejected") is True


def test_run_generation_no_retry_when_clean(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    debug_dir = tmp_path / "debug"
    calls = []

    def fake_runner(**kwargs):
        calls.append(1)
        return {
            "title": "Celaena Sardothien",
            "importance": "principal",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Celaena Sardothien est une assassine.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
        forbidden_names=["Aelin Galathynius"],
    )

    assert len(calls) == 1
    assert page["title"] == "Celaena Sardothien"
    assert not page.get("_failed")


def test_run_generation_no_retry_when_no_forbidden_names(monkeypatch, tmp_path):
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "context_by_chapter": {"ch01": ["Celaena entre dans la salle."]},
    }
    debug_dir = tmp_path / "debug"
    calls = []

    def fake_runner(**kwargs):
        calls.append(1)
        return {
            "title": "Celaena Sardothien",
            "importance": "principal",
            "entity_type": "PERSON",
            "infobox_fields": {},
            "content": "Celaena aussi connue sous le nom d'Aelin Galathynius.",
        }

    monkeypatch.setattr("scripts.generate_wiki_pages._run_wiki_page_item", fake_runner)

    page = _run_generation_for_entity(
        entity=entity,
        book_title="Throne of Glass",
        model="qwen2.5",
        timeout=120,
        sections=["infobox", "biography"],
        max_tokens=800,
        dry_run=False,
        debug_dir=debug_dir,
    )

    assert len(calls) == 1
    assert not page.get("_failed")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_generate_wiki_pages.py::test_run_generation_retries_on_forbidden_name -v`
Expected: FAIL — `TypeError: _run_generation_for_entity() got an unexpected keyword argument 'forbidden_names'`

- [ ] **Step 3: Implement retry logic**

Modify `_run_generation_for_entity` in `scripts/generate_wiki_pages.py`:

```python
def _run_generation_for_entity(
    *,
    entity: dict,
    book_title: str,
    model: str,
    timeout: int,
    sections: list[str],
    max_tokens: int,
    dry_run: bool,
    debug_dir: Path,
    forbidden_names: list[str] | None = None,
) -> dict:
    if not entity.get("context_by_chapter", {}):
        return make_stub_page(entity, insufficient_data=True)
    if dry_run:
        return make_stub_page(entity)

    item_result = _run_wiki_page_item(
        entity=entity,
        book_title=book_title,
        model=model,
        timeout=timeout,
        sections=sections,
        max_tokens=max_tokens,
        forbidden_names=forbidden_names,
    )
    if isinstance(item_result, dict) and item_result.get("error"):
        _save_generation_debug_artifact(debug_dir, entity, item_result)
        return make_stub_page(entity, failed=True)
    typed_rels = entity.get("relationships", [])
    if isinstance(item_result, dict) and "content" in item_result:
        if "relationships" not in sections or not typed_rels:
            item_result["content"] = _strip_relations_section(item_result["content"] or "")

    # Forbidden names check + retry
    if forbidden_names and isinstance(item_result, dict) and "content" in item_result:
        hits = _check_forbidden_names(item_result, forbidden_names)
        if hits:
            print(f" ⚠ spoiler detected ({', '.join(hits)}), retrying…", file=sys.stderr, end="", flush=True)
            item_result = _run_wiki_page_item(
                entity=entity,
                book_title=book_title,
                model=model,
                timeout=timeout,
                sections=sections,
                max_tokens=max_tokens,
                forbidden_names=forbidden_names,
            )
            if isinstance(item_result, dict) and item_result.get("error"):
                _save_generation_debug_artifact(debug_dir, entity, item_result)
                return make_stub_page(entity, failed=True)
            if isinstance(item_result, dict) and "content" in item_result:
                if "relationships" not in sections or not typed_rels:
                    item_result["content"] = _strip_relations_section(item_result["content"] or "")
            hits = _check_forbidden_names(item_result, forbidden_names)
            if hits:
                print(f" ✗ spoiler persists ({', '.join(hits)})", file=sys.stderr, end="", flush=True)
                page = make_stub_page(entity, failed=True)
                page["_spoiler_rejected"] = True
                return page

    return item_result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_generate_wiki_pages.py -k "run_generation" -v`
Expected: all PASS (new + existing tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(generation): retry on forbidden name detection, stub fallback (STU-317)"
```

---

### Task 4: Thread `forbidden_names` through `main()` from book YAML

**Files:**
- Modify: `scripts/generate_wiki_pages.py` — `main()` (line 816)
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

- [ ] **Step 1: Add `forbidden_names` to the book YAML**

Add to `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml` under the existing `validation:` key:

```yaml
validation:
  series: Throne of Glass
  forbidden_series:
    - Kingkiller Chronicle
    - A Court of Thorns and Roses
    - An Ember in the Ashes
    - The Selection
    - Daughter of Smoke and Bone
  forbidden_names:
    - Aelin Galathynius
    - Aelin
```

- [ ] **Step 2: Load forbidden_names in `main()`**

In `scripts/generate_wiki_pages.py`, in `main()`, after `generation_cfg = book_cfg.get("generation", {})` (line 833), add:

```python
    validation_cfg = book_cfg.get("validation", {})
    forbidden_names = validation_cfg.get("forbidden_names", [])
    if forbidden_names:
        print(f"[generate-wiki-pages] Forbidden names active: {forbidden_names}", file=sys.stderr)
```

- [ ] **Step 3: Pass `forbidden_names` to `_run_generation_for_entity`**

In the `_run_generation_for_entity` call inside `main()` (~line 894), add the parameter:

```python
                    page = _run_generation_for_entity(
                        entity=entity,
                        book_title=book_title,
                        model=args.model,
                        timeout=args.timeout,
                        sections=sections,
                        max_tokens=max_tokens,
                        dry_run=args.dry_run,
                        debug_dir=debug_dir,
                        forbidden_names=forbidden_names,
                    )
```

- [ ] **Step 4: Run full test suite**

Run: `pytest tests/test_generate_wiki_pages.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(generation): thread forbidden_names from book YAML config (STU-317)"
```

---

### Task 5: Add `check_forbidden_names` to `wiki_page_validator.py`

**Files:**
- Modify: `scripts/wiki_page_validator.py`
- Test: `tests/test_wiki_page_validator.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_wiki_page_validator.py`:

```python
from scripts.wiki_page_validator import check_forbidden_names


def test_check_forbidden_names_detects_in_content():
    page = {"content": "Celaena, aussi connue sous le nom d'Aelin Galathynius.", "infobox_fields": {}}
    meta = {"forbidden_names": ["Aelin Galathynius"]}
    errors = check_forbidden_names(page, meta)
    assert any("Aelin Galathynius" in e for e in errors)


def test_check_forbidden_names_detects_in_infobox():
    page = {"content": "Texte propre.", "infobox_fields": {"alias": "Aelin"}}
    meta = {"forbidden_names": ["Aelin"]}
    errors = check_forbidden_names(page, meta)
    assert errors != []


def test_check_forbidden_names_passes_clean():
    page = {"content": "Celaena Sardothien est une assassine.", "infobox_fields": {}}
    meta = {"forbidden_names": ["Aelin Galathynius"]}
    assert check_forbidden_names(page, meta) == []


def test_check_forbidden_names_empty_config():
    page = {"content": "N'importe quel contenu.", "infobox_fields": {}}
    meta = {}
    assert check_forbidden_names(page, meta) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wiki_page_validator.py::test_check_forbidden_names_detects_in_content -v`
Expected: FAIL — `ImportError: cannot import name 'check_forbidden_names'`

- [ ] **Step 3: Implement `check_forbidden_names`**

Add to `scripts/wiki_page_validator.py` after `check_forbidden_series` (~line 73):

```python
def check_forbidden_names(page: dict, meta: dict) -> list[str]:
    forbidden = meta.get("forbidden_names", [])
    if not forbidden:
        return []
    haystack = page.get("content", "") + str(page.get("infobox_fields", {}))
    hits = [name for name in forbidden if name.lower() in haystack.lower()]
    if hits:
        return [f"❌ Spoiler détecté (nom interdit) : {hits[0]}"]
    return []
```

- [ ] **Step 4: Wire into `validate_page`**

In `scripts/wiki_page_validator.py`, in the `validate_page` function (~line 115), add after `check_forbidden_series`:

```python
    errors += check_forbidden_names(page, meta)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_wiki_page_validator.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add scripts/wiki_page_validator.py tests/test_wiki_page_validator.py
git commit -m "feat(validator): add check_forbidden_names for Studio pipeline (STU-317)"
```

---

### Task 6: Final validation

- [ ] **Step 1: Run full test suite**

Run: `pytest -q`
Expected: all tests pass (485 existing + ~13 new)

- [ ] **Step 2: Run mypy**

Run: `mypy wiki_creator/`
Expected: no new errors (scripts/ is not under mypy, but check anyway: `mypy scripts/generate_wiki_pages.py scripts/wiki_page_validator.py --ignore-missing-imports`)

- [ ] **Step 3: Commit any fixups if needed**
