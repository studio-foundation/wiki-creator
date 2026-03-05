# Narrator POV Detection Implementation Plan (STU-235)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect narrative POV + narrator reliability and have wiki-generation adapt its tone accordingly.

**Architecture:** Two layers — deterministic pronoun counting in `parse_epub.py` (outputs `pov_detection`), LLM narrator identification + reliability in `resolver.agent.yaml` (outputs `narrator` in entity-resolution). The `narrator` field is passed through by `relationship_extraction.py` and consumed by `writer.agent.yaml` for tone attribution.

**Tech Stack:** Python (re, Counter), spaCy already in place, Studio YAML config, Claude Sonnet via Studio agents.

---

### Task 1: `detect_pov()` in `parse_epub.py`

**Files:**
- Modify: `scripts/parse_epub.py`
- Test: `tests/test_parse_epub.py`

**Step 1: Write the failing tests**

Add to `tests/test_parse_epub.py`:

```python
from scripts.parse_epub import detect_pov


def test_detect_pov_first_person_high_confidence():
    """Dense first-person pronouns → first_person, high confidence."""
    # >1% first-person pronouns
    text = ("je marchais dans la rue. " * 20 +
            "Il faisait beau. " * 5)
    result = detect_pov(text)
    assert result["pov"] == "first_person"
    assert result["confidence"] == "high"
    assert result["first_person_count"] > 0
    assert result["total_tokens"] > 0


def test_detect_pov_first_person_medium_confidence():
    """Moderate first-person pronoun density → first_person, medium confidence."""
    # ~0.7% → medium (between 0.005 and 0.01)
    text = ("je marchais. " * 7 + "Il faisait beau. " * 93)
    result = detect_pov(text)
    assert result["pov"] == "first_person"
    assert result["confidence"] == "medium"


def test_detect_pov_not_first_person():
    """No first-person pronouns → not first_person."""
    text = "Il marchait dans la rue. Elle regardait par la fenêtre. " * 50
    result = detect_pov(text)
    assert result["pov"] != "first_person"


def test_detect_pov_output_shape():
    """Output always has required keys."""
    result = detect_pov("Some text here.")
    assert "pov" in result
    assert "first_person_count" in result
    assert "total_tokens" in result
    assert "confidence" in result


def test_parse_epub_output_includes_pov_detection(tmp_path):
    """parse_epub() output includes pov_detection key."""
    import ebooklib
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_title("Test")
    book.set_language("fr")
    item = epub.EpubHtml(uid="ch1", title="Ch1", file_name="ch1.xhtml", lang="fr")
    content = "<html><body><p>" + ("je marchais dans la rue. " * 30) + "</p></body></html>"
    item.set_content(content.encode())
    book.add_item(item)
    book.spine = [("ch1", True)]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub_path = str(tmp_path / "test.epub")
    epub.write_epub(epub_path, book)

    from scripts.parse_epub import parse_epub
    result = parse_epub(epub_path)
    assert "pov_detection" in result
    assert result["pov_detection"]["pov"] == "first_person"
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_parse_epub.py::test_detect_pov_first_person_high_confidence tests/test_parse_epub.py::test_detect_pov_output_shape -v
```

Expected: `ImportError` or `AttributeError` — `detect_pov` doesn't exist yet.

**Step 3: Implement `detect_pov()` in `parse_epub.py`**

Add before `MIN_CHAPTER_CHARS`:

```python
import re
from collections import Counter

# French first-person pronouns (word-boundary matched)
_FIRST_PERSON_RE = re.compile(
    r"\b(je|me|moi|m'|mon|ma|mes)\b",
    re.IGNORECASE,
)


def detect_pov(text: str) -> dict:
    """Detect narrative point of view from raw chapter text.

    Returns:
        {
            "pov": "first_person" | "third_limited" | "omniscient",
            "first_person_count": int,
            "total_tokens": int,
            "confidence": "high" | "medium" | "low",
        }
    """
    tokens = text.split()
    total_tokens = len(tokens)
    if total_tokens == 0:
        return {"pov": "omniscient", "first_person_count": 0, "total_tokens": 0, "confidence": "low"}

    first_person_count = len(_FIRST_PERSON_RE.findall(text))
    ratio = first_person_count / total_tokens

    if ratio > 0.01:
        confidence = "high"
        pov = "first_person"
    elif ratio > 0.005:
        confidence = "medium"
        pov = "first_person"
    else:
        confidence = "low" if ratio > 0 else "high"
        # Simple third-person heuristic: internal thought markers for one character
        thought_markers = re.findall(
            r"\b(il pensait|elle pensait|il savait|elle savait|il sentait|elle sentait)\b",
            text,
            re.IGNORECASE,
        )
        pov = "third_limited" if thought_markers else "omniscient"

    return {
        "pov": pov,
        "first_person_count": first_person_count,
        "total_tokens": total_tokens,
        "confidence": confidence,
    }
```

Then in `parse_epub()`, before the `return` statement, add:

```python
    # Concatenate all chapter text for POV detection
    full_text = " ".join(ch["content"] for ch in chapters)
    pov_detection = detect_pov(full_text)

    return {"title": title, "author": author, "chapters": chapters, "pov_detection": pov_detection}
```

**Step 4: Run tests**

```bash
pytest tests/test_parse_epub.py -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add scripts/parse_epub.py tests/test_parse_epub.py
git commit -m "feat(stu-235): add detect_pov() to parse_epub — deterministic POV detection"
```

---

### Task 2: Pipeline YAML + contracts

**Files:**
- Modify: `.studio/pipelines/wiki-pipeline.pipeline.yaml`
- Modify: `.studio/contracts/entity-resolution.contract.yaml`
- Modify: `.studio/contracts/relationship-extraction.contract.yaml`

No unit tests for YAML config — verification is by inspection.

**Step 1: Add `epub-parse` to entity-resolution context**

In `.studio/pipelines/wiki-pipeline.pipeline.yaml`, find the `entity-resolution` stage and change:

```yaml
  - name: entity-resolution
    kind: analysis
    agent: resolver
    contract: entity-resolution
    ralph:
      max_attempts: 3
    context:
      include:
        - input
        - previous_stage_output
```

to:

```yaml
  - name: entity-resolution
    kind: analysis
    agent: resolver
    contract: entity-resolution
    ralph:
      max_attempts: 3
    context:
      include:
        - input
        - epub-parse
        - previous_stage_output
```

**Step 2: Update entity-resolution contract**

In `.studio/contracts/entity-resolution.contract.yaml`, change to:

```yaml
name: entity-resolution
version: 1
schema:
  required_fields:
    - entities
  # narrator is nullable — omit or null for omniscient/third-person POV
  # narrator shape: { entity: str, pov: str, reliability: str, evidence: [str] }
```

**Step 3: Update relationship-extraction contract**

In `.studio/contracts/relationship-extraction.contract.yaml`, change to:

```yaml
name: relationship-extraction
version: 1
schema:
  required_fields:
    - entities
    - relationships
    - stats
  # narrator is passed through from entity-resolution (nullable)
```

**Step 4: Commit**

```bash
git add .studio/pipelines/wiki-pipeline.pipeline.yaml \
        .studio/contracts/entity-resolution.contract.yaml \
        .studio/contracts/relationship-extraction.contract.yaml
git commit -m "feat(stu-235): pipeline + contracts — narrator field, epub-parse context in entity-resolution"
```

---

### Task 3: `resolver.agent.yaml` — narrator identification

**Files:**
- Modify: `.studio/agents/resolver.agent.yaml`

**Step 1: Extend the resolver prompt**

In `.studio/agents/resolver.agent.yaml`, append to the `system_prompt` after the existing entity dedup instructions:

```yaml
  ## Narrator detection

  You also receive pov_detection from the epub-parse stage (in previous_outputs["epub-parse"]).

  If pov_detection.pov == "first_person":
  - Identify which PERSON entity is the narrator: the entity whose mention contexts contain
    the most first-person pronouns (je/me/moi/m') as subject or object.
  - Assess reliability: scan the mention contexts for contradictions between chapters,
    explicit hallucinations, or passages where the narrator admits uncertainty or delusion.
  - Set reliability to:
    * "unreliable" — clear contradictions or hallucinations present
    * "partial" — some subjective distortion but mostly consistent
    * "reliable" — no evidence of distortion

  Add a top-level "narrator" field to your JSON output:
  {
    "narrator": {
      "entity": "<canonical_name of narrator entity>",
      "pov": "first_person",
      "reliability": "unreliable" | "partial" | "reliable",
      "evidence": ["ch20: ...", "ch25: ..."]  // 1-3 most compelling pieces of evidence
    }
  }

  If pov_detection.pov is NOT "first_person", omit the "narrator" field or set it to null.

  Final output shape:
  {
    "entities": [{canonical_name, type, aliases, source_ids, relevant}],
    "narrator": { ... } | null
  }
```

**Step 2: Verify by inspection**

Read the full updated `resolver.agent.yaml` to confirm the prompt is coherent and no formatting issues.

**Step 3: Commit**

```bash
git add .studio/agents/resolver.agent.yaml
git commit -m "feat(stu-235): resolver agent — identify narrator entity + reliability"
```

---

### Task 4: `relationship_extraction.py` — narrator pass-through

**Files:**
- Modify: `scripts/relationship_extraction.py`
- Test: `tests/test_relationship_extraction.py`

**Step 1: Write the failing test**

Add to `tests/test_relationship_extraction.py`:

```python
def test_narrator_passthrough_in_output():
    """narrator from entity-resolution is passed through to output unchanged."""
    import json
    import subprocess
    import sys
    import os

    narrator = {
        "entity": "David Martín",
        "pov": "first_person",
        "reliability": "unreliable",
        "evidence": ["ch20: hallucinations"],
    }
    # Minimal entity-resolution output with narrator
    resolution_output = {
        "entities": [
            {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}
        ],
        "narrator": narrator,
    }
    payload = {
        "previous_outputs": {
            "entity-resolution": resolution_output,
            "epub-parse": {"title": "Test", "author": None, "chapters": [], "pov_detection": {"pov": "first_person", "first_person_count": 100, "total_tokens": 500, "confidence": "high"}},
        },
        "additional_context": "",
    }
    result = subprocess.run(
        [sys.executable, "scripts/relationship_extraction.py"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert "narrator" in output, "narrator key missing from output"
    assert output["narrator"] == narrator


def test_narrator_passthrough_null_when_absent():
    """If entity-resolution has no narrator, output narrator is None."""
    import json
    import subprocess
    import sys
    import os

    resolution_output = {
        "entities": [
            {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}
        ],
        # no narrator key
    }
    payload = {
        "previous_outputs": {
            "entity-resolution": resolution_output,
            "epub-parse": {"title": "Test", "author": None, "chapters": [], "pov_detection": {"pov": "omniscient", "first_person_count": 0, "total_tokens": 500, "confidence": "high"}},
        },
        "additional_context": "",
    }
    result = subprocess.run(
        [sys.executable, "scripts/relationship_extraction.py"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert output.get("narrator") is None
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_relationship_extraction.py::test_narrator_passthrough_in_output tests/test_relationship_extraction.py::test_narrator_passthrough_null_when_absent -v
```

Expected: FAIL — `narrator` key absent from output.

**Step 3: Implement pass-through in `relationship_extraction.py`**

Find the final `json.dump(...)` call (currently around line 765) and change it to:

```python
    narrator = resolution_output.get("narrator", None)

    json.dump({
        "entities": entities,
        "relationships": relationships,
        "stats": stats,
        "narrator": narrator,
    }, sys.stdout, ensure_ascii=False)
```

The `resolution_output` variable already exists in `main()` at line 725.

**Step 4: Run tests**

```bash
pytest tests/test_relationship_extraction.py -v
```

Expected: all tests PASS.

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(stu-235): relationship-extraction — pass through narrator field from entity-resolution"
```

---

### Task 5: `writer.agent.yaml` — tone adaptation

**Files:**
- Modify: `.studio/agents/writer.agent.yaml`

**Step 1: Add narrator context section to writer prompt**

In `.studio/agents/writer.agent.yaml`, append to `system_prompt` after the existing `## Relations section` block:

```yaml
  ## Narrator context and tone adaptation

  previous_stage_output["narrator"] contains narrator metadata (may be null or absent).

  If narrator is non-null AND reliability is "unreliable" or "partial":

  **Attribution rules:**
  - Descriptions of other characters filtered through the narrator's subjectivity
    (e.g. "il semblait", "je le voyais comme", "à mes yeux") → prefix with
    "Selon [narrator.entity], ..." or "D'après le récit de [narrator.entity], ..."
  - Observable facts (direct dialogue, physical actions described factually, dates, locations)
    → no attribution, write as direct statement
  - Contradictions between chapters → note both versions explicitly:
    "Au chapitre X, [narrator.entity] décrit... Cependant, au chapitre Y, ..."

  **Editorial note:**
  For PERSON pages where the character is described *almost exclusively* through the narrator
  (i.e. no direct dialogue or third-party observation available in the excerpts), add this
  note at the very top of the page, before the introduction:

  > **Note :** Les informations sur ce personnage proviennent principalement du récit de
  > [narrator.entity], dont la fiabilité est contestée ([narrator.evidence[0]]).

  If narrator is null or reliability is "reliable":
  - Write in standard encyclopedic tone. No attribution needed.
```

**Step 2: Verify by inspection**

Read the full updated `writer.agent.yaml` to confirm the prompt flows correctly from the existing sections.

**Step 3: Commit**

```bash
git add .studio/agents/writer.agent.yaml
git commit -m "feat(stu-235): writer agent — adapt tone based on narrator reliability"
```

---

## Manual end-to-end verification

After all tasks are complete, run the pipeline in mock mode to confirm the shape of intermediate outputs:

```bash
studio run wiki-pipeline --provider mock --live
studio logs
```

Verify:
1. `epub-parse` output contains `pov_detection` key
2. `entity-resolution` output contains `narrator` key (or null)
3. `relationship-extraction` output contains `narrator` key (passed through)
4. `wiki-generation` output — check a PERSON page to see if tone attribution is present when expected

On *Le Jeu de l'Ange*: descriptions of Corelli by Martín should include "Selon Martín, ..." attribution.
