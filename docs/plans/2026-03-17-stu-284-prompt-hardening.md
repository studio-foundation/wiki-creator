# STU-284 Prompt Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace weak negative grounding constraints in the wiki-page-item agent with positive constraints that prevent Mistral 7B from generating content from pre-trained knowledge.

**Architecture:** Two-file change — harden the system prompt in the agent YAML (primary lever, applies to every LLM call) and reinforce it in `build_prompt()` (user-level redundancy). No schema changes, no new dependencies.

**Tech Stack:** Python, pytest, YAML, Ollama/Mistral 7B

---

### Task 1: Harden the agent system prompt

**Files:**
- Modify: `.studio/agents/wiki-page-item.agent.yaml:28-30`

**Step 1: Open the file and read the current grounding instructions**

Lines 28-30 currently read:
```
- Use only the evidence and instructions contained in input["prompt"]
- Do not use any knowledge of the book series or author beyond what is provided in input["prompt"].
  If you recognize the series, ignore everything you know about it.
```

**Step 2: Replace with positive grounding constraints**

Replace those three lines with:
```yaml
  - This is a fictional world created for this exercise. All character names, facts, and events are defined solely by the excerpts in input["prompt"].
  - Every claim you write must be directly supported by a passage in input["prompt"]. If you cannot point to a supporting excerpt, do not write it.
  - Your training knowledge about any real-world book series, author, or publication is irrelevant and must be ignored entirely. Real-world dates, publication info, and series facts are forbidden.
```

**Step 3: Commit**

```bash
git add .studio/agents/wiki-page-item.agent.yaml
git commit -m "fix(wiki-generation): harden agent system prompt grounding (STU-284)"
```

---

### Task 2: Write failing test for fictional-world framing in `build_prompt()`

**Files:**
- Modify: `tests/test_generate_wiki_pages.py`

**Step 1: Write the failing test**

Add after the existing `test_build_prompt_instructs_no_training_knowledge` test (around line 521):

```python
def test_build_prompt_opens_with_fictional_world_framing():
    """Prompt must start with a positive fictional-world framing before any context."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography"])
    # The fictional world framing must appear early (before the entity block)
    framing_pos = prompt.lower().find("fictional world")
    entity_pos = prompt.find("Entity to write:")
    assert framing_pos != -1, "Prompt must contain 'fictional world' framing"
    assert framing_pos < entity_pos, "Fictional world framing must appear before entity block"


def test_build_prompt_uses_positive_grounding_constraint():
    """Prompt must use a positive grounding constraint ('must be supported by') not just a negative one."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {},
    }
    prompt = build_prompt(entity, "Throne of Glass", ["infobox", "biography"])
    lower = prompt.lower()
    assert "must be" in lower and ("supported" in lower or "supported by" in lower)


def test_build_prompt_grounding_excerpts_header_is_prominent():
    """Excerpt block header must use 'GROUNDING EXCERPTS' to reinforce salience."""
    entity = {
        "canonical_name": "Celaena Sardothien",
        "importance": "principal",
        "type": "PERSON",
        "aliases": [],
        "context_by_chapter": {"C01.xhtml": ["She crossed the hall."]},
    }
    prompt = build_prompt(entity, "Throne of Glass", ["biography"])
    assert "GROUNDING EXCERPTS" in prompt
```

**Step 2: Run to verify tests fail**

```bash
pytest tests/test_generate_wiki_pages.py::test_build_prompt_opens_with_fictional_world_framing tests/test_generate_wiki_pages.py::test_build_prompt_uses_positive_grounding_constraint tests/test_generate_wiki_pages.py::test_build_prompt_grounding_excerpts_header_is_prominent -v
```
Expected: all 3 FAIL

**Step 3: Commit failing tests**

```bash
git add tests/test_generate_wiki_pages.py
git commit -m "test(wiki-generation): failing tests for prompt hardening (STU-284)"
```

---

### Task 3: Implement prompt hardening in `build_prompt()`

**Files:**
- Modify: `scripts/generate_wiki_pages.py:305-376`

**Step 1: Add fictional-world framing at the top of the prompt string**

In the `return f"""...` block (around line 305), replace the opening line:
```python
    return f"""You are writing a wiki page for a fantasy novel called "{book_title}".
Output ONLY a valid JSON object. No markdown fences. No explanation. No preamble.
```
With:
```python
    return f"""This is a fictional world. The following excerpts are the ONLY authoritative source of truth. Ignore any prior knowledge you have of this book, series, or author.

You are writing a wiki page for a fictional novel called "{book_title}".
Output ONLY a valid JSON object. No markdown fences. No explanation. No preamble.
```

**Step 2: Rename the excerpt block header**

Find (around line 320):
```python
Text excerpts from the book (primary source — highest priority):
```
Replace with:
```python
GROUNDING EXCERPTS — these are the ONLY facts you may use:
```

**Step 3: Replace the negative grounding constraint with a positive one**

Find (around line 343):
```python
- Use ONLY information present in the excerpts above. Do NOT use your training knowledge about this book or its characters.
```
Replace with:
```python
- Every factual claim in your output must be directly supported by one of the GROUNDING EXCERPTS provided above. If you cannot point to a supporting excerpt, do not write the claim.
- Do not invent names, dates, titles, events, or physical traits. Real-world publication dates and author information are forbidden.
```

**Step 4: Run the new tests to verify they pass**

```bash
pytest tests/test_generate_wiki_pages.py::test_build_prompt_opens_with_fictional_world_framing tests/test_generate_wiki_pages.py::test_build_prompt_uses_positive_grounding_constraint tests/test_generate_wiki_pages.py::test_build_prompt_grounding_excerpts_header_is_prominent -v
```
Expected: all 3 PASS

**Step 5: Run the full test suite to check for regressions**

```bash
pytest -q
```
Expected: all tests pass (485+)

**Step 6: Commit**

```bash
git add scripts/generate_wiki_pages.py
git commit -m "fix(wiki-generation): harden build_prompt grounding constraints (STU-284)"
```
