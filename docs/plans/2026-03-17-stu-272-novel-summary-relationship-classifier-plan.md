# STU-272: Novel Summary Anchor for Relationship Classifier — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an optional `novel_summary` field to book YAMLs so the relationship classifier receives narrative context that guides it beyond the default `employeur/employé` type.

**Architecture:** `novel_summary` is read from `additional_context` alongside existing fields (`classify`, `llm_model`, etc.), passed as a new optional parameter to `classify_relationships()`, and prepended to each per-pair prompt. The agent YAML system prompt is also updated for consistency with the Studio pipeline path.

**Tech Stack:** Python, PyYAML, Ollama (qwen2.5), pytest

---

### Task 1: Tests — `novel_summary` in prompt when provided

**Files:**
- Modify: `tests/test_relationship_extraction.py` (after line ~458, in the STU-262 Task 3 section)

**Step 1: Write the failing test**

Add after `test_classify_relationships_keeps_null_on_per_pair_failure`:

```python
def test_classify_relationships_includes_novel_summary_in_prompt():
    """novel_summary is injected into each pair's prompt when provided."""
    captured_prompts = []

    def fake_call(prompt, model, url):
        captured_prompts.append(prompt)
        return {
            "relationship_type": "ami",
            "direction": "symétrique",
            "evolution": "ils deviennent amis",
            "key_moments": [],
        }

    with patch("scripts.relationship_extraction._check_ollama_available", return_value=True), \
         patch("scripts.relationship_extraction._call_ollama_classify_json", side_effect=fake_call):
        classify_relationships(
            _SAMPLE_RELS,
            model=_TEST_MODEL,
            ollama_url=_OLLAMA_URL,
            novel_summary="Celaena is an assassin. Chaol is her guard and friend.",
        )

    assert len(captured_prompts) == 1
    assert "Celaena is an assassin" in captured_prompts[0]


def test_classify_relationships_omits_summary_block_when_none():
    """When novel_summary is None, no 'Contexte du roman' block appears."""
    captured_prompts = []

    def fake_call(prompt, model, url):
        captured_prompts.append(prompt)
        return {
            "relationship_type": "ami",
            "direction": "symétrique",
            "evolution": "ils deviennent amis",
            "key_moments": [],
        }

    with patch("scripts.relationship_extraction._check_ollama_available", return_value=True), \
         patch("scripts.relationship_extraction._call_ollama_classify_json", side_effect=fake_call):
        classify_relationships(_SAMPLE_RELS, model=_TEST_MODEL, ollama_url=_OLLAMA_URL)

    assert "Contexte du roman" not in captured_prompts[0]
```

**Step 2: Run tests to confirm they fail**

```bash
pytest tests/test_relationship_extraction.py::test_classify_relationships_includes_novel_summary_in_prompt tests/test_relationship_extraction.py::test_classify_relationships_omits_summary_block_when_none -v
```
Expected: FAIL — `classify_relationships() got an unexpected keyword argument 'novel_summary'`

**Step 3: Commit the failing tests**

```bash
git add tests/test_relationship_extraction.py
git commit -m "test(STU-272): failing tests for novel_summary in classifier prompt"
```

---

### Task 2: Implementation — add `novel_summary` param to `classify_relationships()`

**Files:**
- Modify: `scripts/relationship_extraction.py:848-905`

**Step 1: Update the function signature and prompt**

Find `def classify_relationships(` at line ~848. Change:

```python
def classify_relationships(
    relationships: list[dict],
    *,
    model: str,
    ollama_url: str = _OLLAMA_URL,
) -> list[dict]:
```

To:

```python
def classify_relationships(
    relationships: list[dict],
    *,
    model: str,
    ollama_url: str = _OLLAMA_URL,
    novel_summary: str | None = None,
) -> list[dict]:
```

**Step 2: Inject summary into prompt**

Inside the loop, replace the `prompt = f"""Voici des extraits...` block with:

```python
summary_block = (
    f"Contexte du roman :\n{novel_summary}\n\n"
    if novel_summary
    else ""
)
prompt = f"""{summary_block}Voici des extraits d'un roman où deux personnages apparaissent ensemble.
Personnage A : {rel['entity_a']}
Personnage B : {rel['entity_b']}
Cooccurrences : {rel['cooccurrence_count']}

Extraits :
{contexts_text}

Classifie leur relation. Réponds en JSON uniquement, sans markdown :
{{
  "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre",
  "direction": "symétrique|A→B|B→A",
  "evolution": "en une phrase, comment la relation évolue",
  "key_moments": ["chXX: description courte"]
}}"""
```

**Step 3: Run the new tests**

```bash
pytest tests/test_relationship_extraction.py::test_classify_relationships_includes_novel_summary_in_prompt tests/test_relationship_extraction.py::test_classify_relationships_omits_summary_block_when_none -v
```
Expected: PASS

**Step 4: Run full test suite to check for regressions**

```bash
pytest -q
```
Expected: all passing (same count as before + 2 new)

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py
git commit -m "feat(STU-272): add novel_summary param to classify_relationships prompt"
```

---

### Task 3: Wire `novel_summary` from `additional_context` to call site

**Files:**
- Modify: `scripts/relationship_extraction.py` — the stdin handler block (~line 1204)

**Step 1: Write the failing test**

In `tests/test_relationship_extraction.py`, find the `_make_pipeline_payload` helper and the pipeline integration tests (~line 470). Add:

```python
def test_pipeline_passes_novel_summary_to_classify(monkeypatch):
    """novel_summary from additional_context reaches classify_relationships."""
    import scripts.relationship_extraction as rel_mod

    captured = {}

    def fake_classify(rels, *, model, ollama_url, novel_summary=None):
        captured["novel_summary"] = novel_summary
        return rels

    monkeypatch.setattr(rel_mod, "classify_relationships", fake_classify)

    payload = {
        "additional_context": "classify: true\nllm_model: qwen2.5\nnovel_summary: Celaena is an assassin.\n",
        "previous_outputs": {
            "merge-entities": json.dumps({
                "entities": [],
                "narrator": None,
                "resolution_output": {},
            })
        },
        "all_stage_outputs": {},
    }
    stdin_data = json.dumps(payload)
    result = subprocess.run(
        ["python", "scripts/relationship_extraction.py"],
        input=stdin_data, capture_output=True, text=True
    )
    assert captured.get("novel_summary") == "Celaena is an assassin."
```

> Note: check how existing pipeline integration tests in this file invoke the script — they may use `importlib` or subprocess. Match that pattern exactly.

**Step 2: Run test to confirm it fails**

```bash
pytest tests/test_relationship_extraction.py::test_pipeline_passes_novel_summary_to_classify -v
```
Expected: FAIL

**Step 3: Read novel_summary in the `additional_context` block**

In `relationship_extraction.py`, inside the `if raw_context:` block (~line 1218), add after the existing field reads:

```python
novel_summary: str | None = additional.get("novel_summary") or None
```

Declare `novel_summary: str | None = None` just before the `if raw_context:` block.

**Step 4: Pass `novel_summary` at the call site**

Change the call at ~line 1267 from:

```python
relationships = classify_relationships(relationships, model=llm_model, ollama_url=ollama_url)
```

To:

```python
relationships = classify_relationships(
    relationships,
    model=llm_model,
    ollama_url=ollama_url,
    novel_summary=novel_summary,
)
```

**Step 5: Run new test**

```bash
pytest tests/test_relationship_extraction.py::test_pipeline_passes_novel_summary_to_classify -v
```
Expected: PASS

**Step 6: Full suite**

```bash
pytest -q
```
Expected: all passing

**Step 7: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-272): wire novel_summary from additional_context to classify_relationships"
```

---

### Task 4: Update `relationship-classifier.agent.yaml`

**Files:**
- Modify: `.studio/agents/relationship-classifier.agent.yaml`

**Step 1: Update system prompt**

The current system prompt lists input fields as: `entity_a`, `entity_b`, `cooccurrence_count`, `sample_contexts`. Add `novel_summary` as an optional field:

```yaml
system_prompt: |
  Respond with ONLY a valid JSON object. No markdown fences, no explanation, no other text.

  You classify the relationship between two characters in a novel.

  You receive input with:
  - entity_a: name of character A
  - entity_b: name of character B
  - cooccurrence_count: number of times they appear together
  - sample_contexts: list of short text excerpts where both appear
  - novel_summary: (optional) a short narrative summary of the novel for context

  When novel_summary is provided, use it to anchor your classification in the story's reality.

  Return exactly:
  {
    "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre",
    "direction": "symétrique|A→B|B→A",
    "evolution": "one sentence describing how the relationship evolves",
    "key_moments": ["chXX: short description"]
  }

  Rules:
  - Base your answer on the provided excerpts and novel_summary
  - Do not invent facts
  - Return valid JSON only
```

**Step 2: Commit**

```bash
git add .studio/agents/relationship-classifier.agent.yaml
git commit -m "feat(STU-272): update relationship-classifier agent to document novel_summary input"
```

---

### Task 5: Add `novel_summary` to book YAML

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Step 1: Add the field**

After `llm_model: qwen2.5`, add:

```yaml
novel_summary: |
  Celaena Sardothien is a legendary assassin serving as a slave in the salt mines of Endovier.
  Prince Dorian offers her freedom if she competes in a tournament to become the king's Champion.
  Captain Chaol Westfall escorts and trains her; he and Dorian are close friends.
  Duke Perrington serves as the king's enforcer and acts as an antagonist to Celaena.
  The king rules with an iron fist and is the primary antagonistic force of the story.
  The tournament pits competitors against each other in a series of deadly trials.
```

**Step 2: Commit**

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(STU-272): add novel_summary to throne-of-glass book YAML"
```

---

### Task 6: CLI path — also pass `novel_summary` (optional)

**Files:**
- Modify: `scripts/relationship_extraction.py` — CLI invocation at line ~799

**Step 1: Check the CLI path**

Look at ~line 799: `relationships = classify_relationships(relationships, model=cli_model)`. The CLI path has no `additional_context`, so `novel_summary` will naturally be `None` — no change needed there unless you want to support `--novel-summary` flag. **Skip this for now (YAGNI).**

---

## Final Verification

```bash
pytest -q
```
Expected: all tests pass, count ≥ previous + 3 new tests.
