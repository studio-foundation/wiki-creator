# STU-274 Evidence Field Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an `evidence` field to the relationship classification prompt and output to force grounded chain-of-thought reasoning and reduce hallucinated `evolution` values.

**Architecture:** Three-file change — update the LLM prompt in `scripts/relationship_extraction.py`, store the new field in the output dict, add the field to `RelationshipEntry` in `wiki_creator/types.py`, and update one test fixture.

**Tech Stack:** Python, pytest

---

### Task 1: Add `evidence` to `RelationshipEntry` type

**Files:**
- Modify: `wiki_creator/types.py:60-64`

**Step 1: Write the failing test**

In `tests/test_types.py`, add:

```python
def test_relationship_entry_has_evidence_field():
    from wiki_creator.types import RelationshipEntry
    r = RelationshipEntry(entity_a="A", entity_b="B")
    assert r.evidence is None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_types.py::test_relationship_entry_has_evidence_field -v
```
Expected: FAIL with `AttributeError` or similar.

**Step 3: Add field to `RelationshipEntry`**

In `wiki_creator/types.py`, after `direction: str | None = None` (currently line 62), add:

```python
evidence: str | None = None
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_types.py::test_relationship_entry_has_evidence_field -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add wiki_creator/types.py tests/test_types.py
git commit -m "feat(STU-274): add evidence field to RelationshipEntry"
```

---

### Task 2: Update prompt and output handling in `classify_relationships`

**Files:**
- Modify: `scripts/relationship_extraction.py:885-900`

**Step 1: Update existing test to include `evidence` in mock response**

In `tests/test_relationship_extraction.py`, find `test_classify_relationships_populates_type_on_success` (around line 433). The `ollama_response` dict currently has 4 keys. Add `evidence`:

```python
ollama_response = {
    "evidence": "Chaol escorts Celaena and they spar together.",
    "relationship_type": "antagoniste",
    "direction": "symétrique",
    "evolution": "ils apprennent à se respecter",
    "key_moments": ["ch01: première rencontre"],
}
```

Also add an assertion:

```python
assert result[0]["evidence"] == "Chaol escorts Celaena and they spar together."
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_relationship_extraction.py::test_classify_relationships_populates_type_on_success -v
```
Expected: FAIL — `evidence` not present in result.

**Step 3: Update prompt in `classify_relationships`**

In `scripts/relationship_extraction.py`, replace the prompt block (around lines 885–891):

```python
        prompt = f"""{summary_block}Voici des extraits d'un roman où deux personnages apparaissent ensemble.
Personnage A : {rel['entity_a']}
Personnage B : {rel['entity_b']}
Cooccurrences : {rel['cooccurrence_count']}

Extraits :
{contexts_text}

Classifie leur relation. Réponds en JSON uniquement, sans markdown :
{{
  "evidence": "une phrase : ce que dans les extraits justifie directement le relationship_type",
  "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre",
  "direction": "symétrique|A→B|B→A",
  "evolution": "en une phrase, comment la relation évolue",
  "key_moments": ["chXX: description courte"]
}}

Règles :
- evolution doit être directement inférable des extraits fournis, non inventée
- Si aucune évolution n'est observable, écris "relation stable dans les extraits fournis"
"""
```

**Step 4: Store `evidence` in the result dict**

In the same function, update the dict merge (around lines 895–900):

```python
            rel = {
                **rel,
                "evidence": classification.get("evidence"),
                "relationship_type": classification.get("relationship_type"),
                "direction": classification.get("direction"),
                "evolution": classification.get("evolution"),
                "key_moments": classification.get("key_moments", []),
            }
```

**Step 5: Run the updated test**

```bash
pytest tests/test_relationship_extraction.py::test_classify_relationships_populates_type_on_success -v
```
Expected: PASS

**Step 6: Run full suite**

```bash
pytest -q
```
Expected: all passing (288+).

**Step 7: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-274): add evidence field to classify prompt to reduce hallucinations"
```
