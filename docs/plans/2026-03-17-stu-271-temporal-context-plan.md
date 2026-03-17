# STU-271 — `temporal_context` in chapter-summary: Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `temporal_context` ("present" / "flashback" / "mixed" / "unknown") and `flashback_anchor` fields to chapter summaries, detect them via heuristic (extractive) or LLM, and use them in the wiki prompt to separate flashback bullets into a dedicated "Backstory context" section.

**Architecture:** Three-layer change — (1) contracts + agent prompt declare the new fields; (2) `chapter_summary.py` populates them via flashback_cues from `cue_words/<lang>.json` (extractive) or LLM response passthrough; (3) `generate_wiki_pages.py` splits the prompt into two labeled blocks.

**Tech Stack:** Python, YAML contracts, Ollama agent, `wiki_creator/cue_words/<lang>.json`

---

### Task 1: Add `flashback_cues` to cue_words files

**Files:**
- Modify: `wiki_creator/cue_words/fr.json`
- Modify: `wiki_creator/cue_words/en.json`

**Step 1: Add to `fr.json`**

Open `wiki_creator/cue_words/fr.json` and add the following key (same level as `place_cue_words`):

```json
"flashback_cues": [
  "des années plus tôt",
  "des années auparavant",
  "des mois plus tôt",
  "bien avant",
  "il se souvenait",
  "elle se souvenait",
  "il se rappelait",
  "elle se rappelait",
  "dans un autre temps",
  "autrefois",
  "jadis"
]
```

**Step 2: Add to `en.json`**

Open `wiki_creator/cue_words/en.json` and add:

```json
"flashback_cues": [
  "years before",
  "years earlier",
  "months before",
  "long before",
  "she remembered",
  "he remembered",
  "she recalled",
  "he recalled",
  "in another time",
  "once upon a time"
]
```

**Step 3: Run existing tests to ensure nothing is broken**

```bash
pytest -q
```
Expected: all 288 pass (no change to production code yet).

**Step 4: Commit**

```bash
git add wiki_creator/cue_words/fr.json wiki_creator/cue_words/en.json
git commit -m "feat(stu-271): add flashback_cues to fr and en cue_words"
```

---

### Task 2: Update contracts

**Files:**
- Modify: `.studio/contracts/chapter-summary-item.contract.yaml`
- Modify: `.studio/contracts/chapter-summary.contract.yaml`

**Step 1: Update `chapter-summary-item.contract.yaml`**

Current content ends after `# summary_bullets: list of 1..N non-empty summary bullet strings`.
Add after that line:

```yaml
# temporal_context: "present" | "flashback" | "mixed" | "unknown"  (optional, default "unknown")
# flashback_anchor: str | null  — e.g. "5 ans avant les événements du ch.01"
```

**Step 2: Update `chapter-summary.contract.yaml`**

The schema comment block describes each entry in `chapter_summaries`. After `"summary_method": "extractive|llm|extractive_fallback"` add:

```yaml
#       "temporal_context": "present"|"flashback"|"mixed"|"unknown",
#       "flashback_anchor": "..." | null
```

**Step 3: Run tests**

```bash
pytest -q
```
Expected: 288 pass.

**Step 4: Commit**

```bash
git add .studio/contracts/chapter-summary-item.contract.yaml .studio/contracts/chapter-summary.contract.yaml
git commit -m "feat(stu-271): add temporal_context and flashback_anchor to contracts"
```

---

### Task 3: Update the chapter-summary agent prompt

**Files:**
- Modify: `.studio/agents/chapter-summary.agent.yaml`

**Step 1: Update the system prompt**

Replace the current `system_prompt` with:

```yaml
system_prompt: |
  Respond with ONLY a valid JSON object. No markdown fences, no explanation, no other text.

  You summarize one novel chapter into concise wiki-context bullets and classify its temporal context.

  You receive input with:
  - chapter_id
  - chapter_title
  - chapter_content
  - max_bullets

  Return exactly:
  {
    "chapter_id": input["chapter_id"],
    "chapter_title": input["chapter_title"],
    "summary_bullets": ["...", "..."],
    "temporal_context": "present" | "flashback" | "mixed" | "unknown",
    "flashback_anchor": "..." | null
  }

  Temporal context detection rules:
  - "flashback": the chapter describes events clearly prior to the main narrative (tense shifts to pluperfect/past perfect, phrases like "Des années plus tôt", "Years before", "Il se souvenait de", "She remembered")
  - "mixed": the chapter contains both present-narrative and flashback sequences
  - "present": the chapter is entirely in the main narrative timeline
  - "unknown": cannot determine with confidence — USE THIS WHEN IN DOUBT

  flashback_anchor: a short description of the temporal offset (e.g. "5 ans avant les événements du ch.01"). Set to null if temporal_context is "present" or "unknown".

  Rules:
  - Use only chapter_content
  - Do not invent facts
  - Return at most max_bullets bullets
  - Each bullet must be a complete standalone sentence
  - Do not return a string in place of the object
  - When in doubt about temporal_context, use "unknown"
```

**Step 2: Run tests**

```bash
pytest -q
```
Expected: 288 pass (agent file not tested by unit tests).

**Step 3: Commit**

```bash
git add .studio/agents/chapter-summary.agent.yaml
git commit -m "feat(stu-271): enrich chapter-summary agent prompt with temporal_context detection"
```

---

### Task 4: Add `_detect_temporal_context` to `chapter_summary.py`

**Files:**
- Modify: `scripts/chapter_summary.py`
- Test: `tests/test_chapter_summary.py`

**Step 1: Write the failing tests**

Add to `tests/test_chapter_summary.py`:

```python
from scripts.chapter_summary import _detect_temporal_context


def test_detect_temporal_context_flashback_when_cue_matches():
    content = "Des années plus tôt, Celaena vivait encore à Rifthold."
    result = _detect_temporal_context(content, flashback_cues=("des années plus tôt",))
    assert result == "flashback"


def test_detect_temporal_context_present_when_no_cue():
    content = "Celaena entered the castle and met Dorian."
    result = _detect_temporal_context(content, flashback_cues=("years before", "she remembered"))
    assert result == "present"


def test_detect_temporal_context_unknown_when_no_cues_provided():
    content = "Celaena entered the castle and met Dorian."
    result = _detect_temporal_context(content, flashback_cues=())
    assert result == "unknown"


def test_detect_temporal_context_case_insensitive():
    content = "YEARS BEFORE she had trained under Arobynn."
    result = _detect_temporal_context(content, flashback_cues=("years before",))
    assert result == "flashback"
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_chapter_summary.py::test_detect_temporal_context_flashback_when_cue_matches -v
```
Expected: FAIL with `ImportError: cannot import name '_detect_temporal_context'`

**Step 3: Implement `_detect_temporal_context` in `scripts/chapter_summary.py`**

Add this function after `_looks_dialogue_heavy`:

```python
def _detect_temporal_context(content: str, flashback_cues: tuple[str, ...] = ()) -> str:
    if not flashback_cues:
        return "unknown"
    lowered = (content or "").lower()
    for cue in flashback_cues:
        if cue.lower() in lowered:
            return "flashback"
    return "present"
```

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_chapter_summary.py -v -k "detect_temporal"
```
Expected: 4 PASS

**Step 5: Commit**

```bash
git add scripts/chapter_summary.py tests/test_chapter_summary.py
git commit -m "feat(stu-271): add _detect_temporal_context with flashback_cues"
```

---

### Task 5: Wire `temporal_context` into extractive summarization

**Files:**
- Modify: `scripts/chapter_summary.py`
- Test: `tests/test_chapter_summary.py`

**Step 1: Write failing tests**

Add to `tests/test_chapter_summary.py`:

```python
def test_summarize_chapter_extractive_sets_temporal_context_present():
    chapter = {
        "id": "ch01", "title": "Chapter 1",
        "content": "Celaena entered the castle and met Dorian.",
    }
    result = summarize_chapter(chapter, flashback_cues=("years before",))
    assert result["temporal_context"] == "present"
    assert result["flashback_anchor"] is None


def test_summarize_chapter_extractive_detects_flashback():
    chapter = {
        "id": "ch02", "title": "Chapter 2",
        "content": "Years before, she had trained under Arobynn in the Assassins Keep.",
    }
    result = summarize_chapter(chapter, flashback_cues=("years before",))
    assert result["temporal_context"] == "flashback"
    assert result["flashback_anchor"] is None


def test_summarize_chapter_no_cues_gives_unknown():
    chapter = {
        "id": "ch03", "title": "Chapter 3",
        "content": "Celaena studied the map and found nothing.",
    }
    result = summarize_chapter(chapter, flashback_cues=())
    assert result["temporal_context"] == "unknown"
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_chapter_summary.py -k "temporal_context" -v
```
Expected: FAIL — `summarize_chapter` doesn't accept `flashback_cues` returning temporal_context yet (the extractive path doesn't set it).

**Step 3: Update `_summarize_chapter_extractive`**

Add `flashback_cues` parameter and append fields to the returned dict:

```python
def _summarize_chapter_extractive(
    chapter: dict,
    cfg: ChapterSummaryConfig,
    method: str = "extractive",
    seed_flags: list[str] | None = None,
    action_cues: tuple[str, ...] = (),
    flashback_cues: tuple[str, ...] = (),
) -> dict:
    # ... existing logic unchanged ...
    result = {
        "chapter_id": chapter_id,
        "chapter_title": chapter_title,
        "summary_bullets": bullets,
        "summary_method": method,
        "quality_flags": quality_flags,
        "temporal_context": _detect_temporal_context(chapter.get("content", ""), flashback_cues),
        "flashback_anchor": None,
    }
    return result
```

**Step 4: Update `summarize_chapter` signature to accept and pass `flashback_cues`**

```python
def summarize_chapter(
    chapter: dict,
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
    flashback_cues: tuple[str, ...] = (),
) -> dict:
    cfg = config or ChapterSummaryConfig()
    if cfg.mode == "llm":
        llm_result = _call_llm_summary(...)
        return summarize_chapter_from_item_result(chapter, llm_result, config=cfg, action_cues=action_cues, flashback_cues=flashback_cues)
    return _summarize_chapter_extractive(chapter, cfg, action_cues=action_cues, flashback_cues=flashback_cues)
```

**Step 5: Update `summarize_chapters` and `summarize_chapters_incrementally`** to accept and pass `flashback_cues`:

```python
def summarize_chapters(
    chapters: list[dict],
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
    flashback_cues: tuple[str, ...] = (),
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for chapter in chapters:
        if _is_frontmatter_chapter(chapter):
            continue
        key = _chapter_key(chapter)
        if not key:
            continue
        result[key] = summarize_chapter(chapter, config=config, action_cues=action_cues, flashback_cues=flashback_cues)
    return result
```

```python
def summarize_chapters_incrementally(
    chapters: list[dict],
    *,
    output_file: Path,
    debug_dir: Path | None = None,
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
    flashback_cues: tuple[str, ...] = (),
) -> dict[str, dict]:
    # ... existing resume logic ...
    for chapter in chapters:
        # ...
        if (config or ChapterSummaryConfig()).mode == "llm":
            item_result = _run_chapter_summary_item(chapter=chapter, config=...)
            # ...
            result[key] = summarize_chapter_from_item_result(chapter, item_result, config=config, action_cues=action_cues, flashback_cues=flashback_cues)
        else:
            result[key] = summarize_chapter(chapter, config=config, action_cues=action_cues, flashback_cues=flashback_cues)
        _save_chapter_summaries(result, output_file)
    return result
```

**Step 6: Update `main()` to load and pass `flashback_cues`**

In `main()`, after loading `action_cues`:
```python
flashback_cues = tuple(load_lang_config(language).get("flashback_cues", ()))
```
Then pass to `summarize_chapters_incrementally`.

**Step 7: Run tests**

```bash
pytest tests/test_chapter_summary.py -v
```
Expected: all existing + new tests pass.

**Step 8: Commit**

```bash
git add scripts/chapter_summary.py tests/test_chapter_summary.py
git commit -m "feat(stu-271): wire temporal_context into extractive summarization"
```

---

### Task 6: Wire `temporal_context` through the LLM path

**Files:**
- Modify: `scripts/chapter_summary.py`
- Test: `tests/test_chapter_summary.py`

**Step 1: Write failing tests**

```python
def test_summarize_chapter_from_item_result_passes_through_temporal_context():
    chapter = {"id": "ch01", "title": "Chapter 1", "content": "..."}
    item_result = {
        "chapter_id": "ch01",
        "chapter_title": "Chapter 1",
        "summary_bullets": ["Celaena found a clue."],
        "temporal_context": "flashback",
        "flashback_anchor": "5 ans avant les événements du ch.01",
    }
    result = summarize_chapter_from_item_result(chapter, item_result)
    assert result["temporal_context"] == "flashback"
    assert result["flashback_anchor"] == "5 ans avant les événements du ch.01"


def test_summarize_chapter_from_item_result_defaults_unknown_when_missing():
    chapter = {"id": "ch01", "title": "Chapter 1", "content": "..."}
    item_result = {
        "summary_bullets": ["Celaena found a clue."],
    }
    result = summarize_chapter_from_item_result(chapter, item_result)
    assert result["temporal_context"] == "unknown"
    assert result["flashback_anchor"] is None


def test_summarize_chapter_from_item_result_fallback_uses_heuristic(monkeypatch):
    chapter = {
        "id": "ch02", "title": "Chapter 2",
        "content": "Years before, Celaena had trained in the Keep.",
    }
    item_result = {"summary_bullets": [], "error": "llm_timeout"}
    cfg = ChapterSummaryConfig(mode="llm", llm_fallback_to_extractive=True)
    result = summarize_chapter_from_item_result(
        chapter, item_result, config=cfg, flashback_cues=("years before",)
    )
    assert result["summary_method"] == "extractive_fallback"
    assert result["temporal_context"] == "flashback"
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_chapter_summary.py -k "item_result" -v
```
Expected: FAIL

**Step 3: Update `summarize_chapter_from_item_result`**

```python
def summarize_chapter_from_item_result(
    chapter: dict,
    item_result: dict | list[str],
    config: ChapterSummaryConfig | None = None,
    action_cues: tuple[str, ...] = (),
    flashback_cues: tuple[str, ...] = (),
) -> dict:
    cfg = config or ChapterSummaryConfig()
    if isinstance(item_result, list):
        llm_bullets = item_result
        llm_error = None if llm_bullets else "llm_invalid_response"
        temporal_context = "unknown"
        flashback_anchor = None
    else:
        llm_bullets = _sanitize_bullets(item_result.get("summary_bullets"), cfg.max_bullets)
        llm_error = item_result.get("error") or None
        temporal_context = item_result.get("temporal_context") or "unknown"
        flashback_anchor = item_result.get("flashback_anchor") or None

    if llm_bullets:
        return {
            "chapter_id": str(chapter.get("id", "")).strip(),
            "chapter_title": str(chapter.get("title", "")).strip(),
            "summary_bullets": llm_bullets,
            "summary_method": "llm",
            "quality_flags": [],
            "temporal_context": temporal_context,
            "flashback_anchor": flashback_anchor,
        }
    if cfg.llm_fallback_to_extractive:
        return _summarize_chapter_extractive(
            chapter, cfg,
            method="extractive_fallback",
            seed_flags=([llm_error] if llm_error else []) + ["fallback_used"],
            action_cues=action_cues,
            flashback_cues=flashback_cues,
        )
    return {
        "chapter_id": str(chapter.get("id", "")).strip(),
        "chapter_title": str(chapter.get("title", "")).strip(),
        "summary_bullets": [_FALLBACK_BULLET],
        "summary_method": "llm",
        "quality_flags": [llm_error] if llm_error else [],
        "temporal_context": "unknown",
        "flashback_anchor": None,
    }
```

**Step 4: Run all tests**

```bash
pytest tests/test_chapter_summary.py -v
```
Expected: all pass.

**Step 5: Commit**

```bash
git add scripts/chapter_summary.py tests/test_chapter_summary.py
git commit -m "feat(stu-271): pass temporal_context through LLM path and fallback"
```

---

### Task 7: Propagate `temporal_context` in `wiki_preparation.py`

**Files:**
- Modify: `scripts/wiki_preparation.py`
- Test: `tests/test_wiki_preparation.py`

**Step 1: Write the failing test**

In `tests/test_wiki_preparation.py`, find the tests for `build_chapter_summary_context` (search for `build_chapter_summary_context`). Add:

```python
def test_build_chapter_summary_context_includes_temporal_context():
    entity = {"type": "PERSON", "canonical_name": "Celaena", "chapter_mentions": {}}
    chapter_summaries = {
        "Chapter 1": {
            "chapter_id": "ch01",
            "chapter_title": "Chapter 1",
            "summary_bullets": ["Celaena arrived at the castle."],
            "temporal_context": "flashback",
        }
    }
    context_by_chapter = {"ch01": ["some mention"], "Chapter 1": ["some mention"]}
    result = build_chapter_summary_context(entity, chapter_summaries, 10, context_by_chapter)
    assert len(result) == 1
    assert result[0]["temporal_context"] == "flashback"


def test_build_chapter_summary_context_defaults_unknown_when_missing():
    entity = {"type": "PERSON", "canonical_name": "Celaena", "chapter_mentions": {}}
    chapter_summaries = {
        "Chapter 1": {
            "chapter_id": "ch01",
            "chapter_title": "Chapter 1",
            "summary_bullets": ["Celaena arrived."],
            # no temporal_context key
        }
    }
    context_by_chapter = {"Chapter 1": ["some mention"]}
    result = build_chapter_summary_context(entity, chapter_summaries, 10, context_by_chapter)
    assert result[0]["temporal_context"] == "unknown"
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_wiki_preparation.py -k "temporal_context" -v
```
Expected: FAIL — `temporal_context` not in returned dicts.

**Step 3: Update `build_chapter_summary_context` in `scripts/wiki_preparation.py`**

Change the `result.append(...)` call (around line 298) to:

```python
result.append({
    "chapter_key": chapter_key,
    "summary_bullets": bullets,
    "temporal_context": summary.get("temporal_context", "unknown"),
})
```

**Step 4: Run all tests**

```bash
pytest -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add scripts/wiki_preparation.py tests/test_wiki_preparation.py
git commit -m "feat(stu-271): propagate temporal_context in build_chapter_summary_context"
```

---

### Task 8: Split prompt into present + backstory blocks in `generate_wiki_pages.py`

**Files:**
- Modify: `scripts/generate_wiki_pages.py`
- Test: `tests/test_generate_wiki_pages.py`

**Step 1: Write failing tests**

In `tests/test_generate_wiki_pages.py`, find tests for `build_prompt`. Add:

```python
def test_build_prompt_puts_flashback_chapters_in_backstory_block():
    entity = {
        "canonical_name": "Celaena",
        "type": "PERSON",
        "importance": "principal",
        "aliases": [],
        "context_by_chapter": {},
        "related_context": [],
        "relationships": [],
        "chapter_summary_context": [
            {
                "chapter_key": "ch01",
                "summary_bullets": ["She arrived at the castle."],
                "temporal_context": "present",
            },
            {
                "chapter_key": "ch02",
                "summary_bullets": ["Five years earlier, she trained under Arobynn."],
                "temporal_context": "flashback",
            },
        ],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["## Biographie", "## Relations"])
    assert "## Chapter summary context" in prompt
    assert "She arrived at the castle." in prompt
    assert "## Backstory context" in prompt
    assert "Five years earlier" in prompt
    # Present bullet must not appear in backstory block and vice versa
    backstory_start = prompt.index("## Backstory context")
    present_start = prompt.index("## Chapter summary context")
    assert present_start < backstory_start
    assert prompt.index("She arrived at the castle.") < backstory_start


def test_build_prompt_omits_backstory_block_when_no_flashbacks():
    entity = {
        "canonical_name": "Dorian",
        "type": "PERSON",
        "importance": "secondary",
        "aliases": [],
        "context_by_chapter": {},
        "related_context": [],
        "relationships": [],
        "chapter_summary_context": [
            {
                "chapter_key": "ch01",
                "summary_bullets": ["Dorian met Chaol in the hall."],
                "temporal_context": "present",
            },
        ],
    }
    prompt = build_prompt(entity, "Throne of Glass", ["## Biographie"])
    assert "## Backstory context" not in prompt
    assert "Dorian met Chaol" in prompt
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_generate_wiki_pages.py -k "backstory" -v
```
Expected: FAIL

**Step 3: Replace the `chapter_summary_lines` block in `build_prompt`**

Find this block in `scripts/generate_wiki_pages.py` (lines ~253–265):

```python
chapter_summary_lines = []
for chapter in chapter_summary_context[:8]:
    chapter_key = chapter.get("chapter_key", "").strip()
    if not chapter_key:
        continue
    chapter_summary_lines.append(f"  - Chapter: {chapter_key}")
    for bullet in chapter.get("summary_bullets", [])[:3]:
        chapter_summary_lines.append(f"    - {bullet}")
chapter_summary_block = (
    "\n".join(chapter_summary_lines)
    if chapter_summary_lines
    else "  (no chapter summaries available)"
)
```

Replace with:

```python
present_lines = []
backstory_lines = []
for chapter in chapter_summary_context[:8]:
    chapter_key = chapter.get("chapter_key", "").strip()
    if not chapter_key:
        continue
    temporal = chapter.get("temporal_context", "unknown")
    entry_lines = [f"  - Chapter: {chapter_key}"]
    for bullet in chapter.get("summary_bullets", [])[:3]:
        entry_lines.append(f"    - {bullet}")
    if temporal == "flashback":
        backstory_lines.extend(entry_lines)
    else:
        present_lines.extend(entry_lines)

present_block = (
    "## Chapter summary context\n" + "\n".join(present_lines)
    if present_lines
    else "## Chapter summary context\n  (no chapter summaries available)"
)
backstory_block = (
    "## Backstory context (flashback chapters — events before the main narrative)\n" + "\n".join(backstory_lines)
    if backstory_lines
    else ""
)
chapter_summary_block = present_block + ("\n\n" + backstory_block if backstory_block else "")
```

**Step 4: Run all tests**

```bash
pytest -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add scripts/generate_wiki_pages.py tests/test_generate_wiki_pages.py
git commit -m "feat(stu-271): split prompt into present/backstory blocks by temporal_context"
```

---

### Task 9: Final verification

**Step 1: Run full test suite**

```bash
pytest -q
```
Expected: ≥ 288 pass, 0 fail.

**Step 2: Verify contracts are syntactically valid YAML**

```bash
python -c "import yaml; yaml.safe_load(open('.studio/contracts/chapter-summary-item.contract.yaml'))"
python -c "import yaml; yaml.safe_load(open('.studio/contracts/chapter-summary.contract.yaml'))"
```
Expected: no output (no errors).

**Step 3: Commit final tag if all passes**

```bash
git add -A
git status  # should be clean
```
