# STU-262: Relationship Classification Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `relationship_type` non-null by wiring classify to Ollama and activating it in the book config.

**Architecture:** Three changes — (1) replace the Anthropic client in `classify_relationships()` with Ollama HTTP calls (same pattern as `alias_resolution.py`); (2) model is NEVER hardcoded — it must come from the book YAML (`llm_model`) or the agent YAML (`.studio/agents/relationship-classifier.agent.yaml`); (3) add `classify: true` to `01-throne-of-glass.yaml`.

**No hardcoded model defaults in Python.** If `llm_model` is absent from context, log `[ERROR]` and skip. In CLI test mode, require `--model` arg.

**Tech Stack:** Python stdlib `urllib`, Ollama `/api/generate`, `json`, `yaml`

---

### Task 1: Create `.studio/agents/relationship-classifier.agent.yaml`

**Files:**
- Create: `.studio/agents/relationship-classifier.agent.yaml`

**Step 1: Create the agent YAML**

```yaml
name: relationship-classifier
provider: ollama
model: qwen2.5
system_prompt: |
  Respond with ONLY a valid JSON object. No markdown fences, no explanation, no other text.

  You classify the relationship between two characters in a novel.

  You receive input with:
  - entity_a: name of character A
  - entity_b: name of character B
  - cooccurrence_count: number of times they appear together
  - sample_contexts: list of short text excerpts where both appear

  Return exactly:
  {
    "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre",
    "direction": "symétrique|A→B|B→A",
    "evolution": "one sentence describing how the relationship evolves",
    "key_moments": ["chXX: short description"]
  }

  Rules:
  - Base your answer only on the provided excerpts
  - Do not invent facts
  - Return valid JSON only
```

**Step 2: Verify YAML is valid**

```bash
python -c "import yaml; print(yaml.safe_load(open('.studio/agents/relationship-classifier.agent.yaml')))"
```
Expected: dict printed without error.

**Step 3: Commit**

```bash
git add .studio/agents/relationship-classifier.agent.yaml
git commit -m "feat(STU-262): add relationship-classifier agent YAML"
```

---

### Task 2: Add `_check_ollama_available` and `_call_ollama_classify_json` helpers to `relationship_extraction.py`

**Files:**
- Modify: `scripts/relationship_extraction.py` (around line 798, before `classify_relationships`)

**Step 1: Check imports**

```bash
grep -n "^import socket\|^import urllib" scripts/relationship_extraction.py
```
If `import socket` or `import urllib.request` are missing, add them near the top with the other stdlib imports.

**Step 2: Write the failing test**

Check if `tests/test_relationship_extraction.py` exists:
```bash
ls tests/test_relationship_extraction.py 2>/dev/null && echo "exists" || echo "missing"
```

If missing, create it. Add these tests:

```python
import urllib.error
from unittest.mock import patch, MagicMock
from scripts.relationship_extraction import _check_ollama_available, _call_ollama_classify_json


def test_check_ollama_available_returns_true_on_success():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert _check_ollama_available("http://localhost:11434") is True


def test_check_ollama_available_returns_false_on_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert _check_ollama_available("http://localhost:11434") is False


def test_call_ollama_classify_json_parses_response():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = b'{"response": "{\"relationship_type\": \"ami\", \"direction\": \"sym\\u00e9trique\", \"evolution\": \"ils deviennent amis\", \"key_moments\": [\"ch01: rencontre\"]}"}'
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _call_ollama_classify_json("some prompt", "qwen2.5", "http://localhost:11434", timeout=10)
    assert result["relationship_type"] == "ami"
    assert result["direction"] == "symétrique"


def test_call_ollama_classify_json_returns_none_on_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        result = _call_ollama_classify_json("prompt", "qwen2.5", "http://localhost:11434", timeout=10)
    assert result is None


def test_call_ollama_classify_json_returns_none_on_bad_json():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = b'{"response": "not json at all"}'
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _call_ollama_classify_json("prompt", "qwen2.5", "http://localhost:11434", timeout=10)
    assert result is None
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/test_relationship_extraction.py -v -k "ollama_available or ollama_classify_json"
```
Expected: ImportError or AttributeError.

**Step 4: Implement the helpers**

Add these two functions right before `classify_relationships()` (around line 797). Also add `_OLLAMA_URL = "http://localhost:11434"` as a module-level constant near the top (after existing imports).

```python
_OLLAMA_URL = "http://localhost:11434"


def _check_ollama_available(url: str, timeout: int = 2) -> bool:
    """Return True if Ollama is reachable at url/api/tags."""
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, socket.timeout, OSError):
        return False


def _call_ollama_classify_json(
    prompt: str, model: str, ollama_url: str, timeout: int = 30
) -> dict | None:
    """Call Ollama and parse JSON response. Returns None on any failure."""
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        f"{ollama_url}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        raw = data.get("response", "")
        return json.loads(raw)
    except (urllib.error.URLError, socket.timeout, OSError, json.JSONDecodeError):
        return None
```

**Step 5: Run tests to verify they pass**

```bash
pytest tests/test_relationship_extraction.py -v -k "ollama_available or ollama_classify_json"
```
Expected: 5 PASS

**Step 6: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-262): add Ollama helpers to relationship_extraction"
```

---

### Task 3: Rewrite `classify_relationships()` to use Ollama — no hardcoded model

**Files:**
- Modify: `scripts/relationship_extraction.py:798-844`

**Step 1: Write the failing tests**

Add to `tests/test_relationship_extraction.py`:

```python
from scripts.relationship_extraction import classify_relationships, _OLLAMA_URL

_SAMPLE_RELS = [
    {
        "entity_a": "Celaena",
        "entity_b": "Chaol",
        "cooccurrence_count": 30,
        "chapters": ["ch01", "ch02"],
        "sample_contexts": ["Chaol escorted Celaena to the castle.", "Celaena sparred with Chaol."],
        "relationship_type": None,
        "direction": None,
        "evolution": None,
        "key_moments": [],
    }
]


def test_classify_relationships_populates_type_on_success():
    ollama_response = {
        "relationship_type": "antagoniste",
        "direction": "symétrique",
        "evolution": "ils apprennent à se respecter",
        "key_moments": ["ch01: première rencontre"],
    }
    with patch("scripts.relationship_extraction._check_ollama_available", return_value=True), \
         patch("scripts.relationship_extraction._call_ollama_classify_json", return_value=ollama_response):
        result = classify_relationships(_SAMPLE_RELS, model="qwen2.5", ollama_url=_OLLAMA_URL)
    assert result[0]["relationship_type"] == "antagoniste"
    assert result[0]["direction"] == "symétrique"
    assert result[0]["key_moments"] == ["ch01: première rencontre"]


def test_classify_relationships_returns_unchanged_when_ollama_unavailable():
    with patch("scripts.relationship_extraction._check_ollama_available", return_value=False):
        result = classify_relationships(_SAMPLE_RELS, model="qwen2.5", ollama_url=_OLLAMA_URL)
    assert result[0]["relationship_type"] is None
    assert len(result) == 1


def test_classify_relationships_keeps_null_on_per_pair_failure():
    with patch("scripts.relationship_extraction._check_ollama_available", return_value=True), \
         patch("scripts.relationship_extraction._call_ollama_classify_json", return_value=None):
        result = classify_relationships(_SAMPLE_RELS, model="qwen2.5", ollama_url=_OLLAMA_URL)
    assert result[0]["relationship_type"] is None
    assert len(result) == 1  # pair still included, not dropped
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_relationship_extraction.py -v -k "classify_relationships"
```
Expected: FAIL (current function uses anthropic).

**Step 3: Replace `classify_relationships()`**

Replace the entire function (lines 798–844). Note: **no default value for `model`** — caller must always provide it.

```python
def classify_relationships(
    relationships: list[dict],
    *,
    model: str,
    ollama_url: str = _OLLAMA_URL,
) -> list[dict]:
    """Classify relationships using Ollama. Fails gracefully per pair.

    `model` is required — read it from the book YAML (llm_model) or the
    relationship-classifier agent YAML. Never hardcode it here.
    """
    if not _check_ollama_available(ollama_url):
        print(
            f"  [ERROR] Ollama not available at {ollama_url} — classification skipped.",
            file=sys.stderr,
        )
        return relationships

    result = []
    for rel in relationships:
        contexts_text = "\n".join(
            f'{i+1}. "{ctx}"' for i, ctx in enumerate(rel["sample_contexts"][:3])
        )
        prompt = f"""Voici des extraits d'un roman où deux personnages apparaissent ensemble.
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

        classification = _call_ollama_classify_json(prompt, model, ollama_url)
        if classification:
            rel = {
                **rel,
                "relationship_type": classification.get("relationship_type"),
                "direction": classification.get("direction"),
                "evolution": classification.get("evolution"),
                "key_moments": classification.get("key_moments", []),
            }
        else:
            print(
                f"  [WARN] classification failed for {rel['entity_a']}↔{rel['entity_b']}",
                file=sys.stderr,
            )
        result.append(rel)

    return result
```

**Step 4: Fix the CLI `--classify` path (around line 782)**

The test-mode block calls `classify_relationships(relationships)` without `model`. Update it to read model from `--model` arg:

```python
if "--classify" in sys.argv:
    # Require --model <name> when using --classify in CLI mode
    model_idx = sys.argv.index("--model") if "--model" in sys.argv else -1
    cli_model = sys.argv[model_idx + 1] if model_idx >= 0 else None
    if not cli_model:
        print(
            "[ERROR] --classify requires --model <model_name> (e.g. --model qwen2.5)",
            file=sys.stderr,
        )
        sys.exit(1)
    print("\n=== CLASSIFY MODE ===")
    relationships = classify_relationships(relationships, model=cli_model)
    classified_count = sum(1 for r in relationships if r.get("relationship_type"))
    print(f"Classified {classified_count}/{len(relationships)} relationships")
    for r in relationships[:5]:
        print(f"  {r['entity_a']} ↔ {r['entity_b']}: {r['relationship_type']} ({r['direction']})")
        if r.get("evolution"):
            print(f"    evolution: {r['evolution']}")
```

Also update the docstring at the top of the file to show updated CLI usage:
```
  python scripts/relationship_extraction.py --test --classify --model qwen2.5
```

**Step 5: Run tests**

```bash
pytest tests/test_relationship_extraction.py -v
pytest -q
```
Expected: all pass (288+).

**Step 6: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-262): rewrite classify_relationships to use Ollama, model always from config"
```

---

### Task 4: Pass `llm_model` and `ollama_url` from pipeline context — error if missing

**Files:**
- Modify: `scripts/relationship_extraction.py:1145-1199` (pipeline stdin block)

**Step 1: Write the failing test**

Add to `tests/test_relationship_extraction.py`:

```python
import json as _json
import io

def _make_pipeline_payload(classify=True, llm_model="qwen2.5", include_llm_model=True):
    additional_lines = [f"classify: {str(classify).lower()}"]
    if include_llm_model:
        additional_lines.append(f"llm_model: {llm_model}")
    return {
        "additional_context": "\n".join(additional_lines),
        "previous_outputs": {
            "merge-entities": {
                "entities": [
                    {"canonical_name": "Celaena", "type": "PERSON", "relevant": True, "aliases": [], "source_ids": []},
                    {"canonical_name": "Chaol", "type": "PERSON", "relevant": True, "aliases": [], "source_ids": []},
                ]
            }
        },
        "all_stage_outputs": {}
    }


def test_pipeline_passes_llm_model_to_classify(monkeypatch):
    import scripts.relationship_extraction as rel_mod
    captured = {}

    def fake_classify(rels, *, model, ollama_url):
        captured["model"] = model
        return rels

    monkeypatch.setattr(rel_mod, "classify_relationships", fake_classify)
    monkeypatch.setattr(rel_mod, "_load_mentions_from_files", lambda p: {})
    monkeypatch.setattr(rel_mod, "_paths_from_payload", lambda p: None)

    payload = _make_pipeline_payload(classify=True, llm_model="qwen2.5")
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", io.StringIO())

    rel_mod.main()
    assert captured.get("model") == "qwen2.5"


def test_pipeline_skips_classify_when_no_llm_model(monkeypatch, capsys):
    import scripts.relationship_extraction as rel_mod

    monkeypatch.setattr(rel_mod, "_load_mentions_from_files", lambda p: {})
    monkeypatch.setattr(rel_mod, "_paths_from_payload", lambda p: None)

    payload = _make_pipeline_payload(classify=True, include_llm_model=False)
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", io.StringIO())

    rel_mod.main()
    captured = capsys.readouterr()
    assert "[ERROR]" in captured.err
    assert "llm_model" in captured.err
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_relationship_extraction.py -v -k "pipeline_passes_llm_model or pipeline_skips_classify"
```
Expected: FAIL.

**Step 3: Update the pipeline classify block**

In the `additional_context` parsing block (around line 1156), add after the existing fields:

```python
llm_model = additional.get("llm_model")  # No default — must be explicit
ollama_url = additional.get("ollama_url", os.environ.get("OLLAMA_URL", _OLLAMA_URL))
```

Before the `if raw_context:` block, initialize them:

```python
llm_model: str | None = None
ollama_url = os.environ.get("OLLAMA_URL", _OLLAMA_URL)
```

Change the classify invocation (around line 1197):

```python
if do_classify:
    if not llm_model:
        print(
            "  [ERROR] classify: true is set but llm_model is missing from context — classification skipped.",
            file=sys.stderr,
        )
    else:
        relationships = classify_relationships(relationships, model=llm_model, ollama_url=ollama_url)
        stats["classified"] = sum(1 for r in relationships if r.get("relationship_type"))
```

**Step 4: Run tests**

```bash
pytest tests/test_relationship_extraction.py -v
pytest -q
```
Expected: all pass.

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-262): require llm_model from context, error if missing when classify: true"
```

---

### Task 5: Add `classify: true` to the Throne of Glass book YAML

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Step 1: Add the flag**

After `use_llm: true` on line 10, add:

```yaml
classify: true
```

Lines 9–12 should read:
```yaml
coref: false
use_llm: true
classify: true
llm_model: qwen2.5
```

**Step 2: Verify YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml'))"
```
Expected: no error.

**Step 3: Commit**

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(STU-262): activate classify: true for Throne of Glass"
```

---

### Task 6: Smoke test CLI mode

**Step 1: Run with --model flag**

```bash
python scripts/relationship_extraction.py --test --classify --model qwen2.5
```
Expected: `=== CLASSIFY MODE ===` output. If Ollama is running, relationships are classified. If not: `[ERROR] Ollama not available`.

**Step 2: Verify --classify without --model errors cleanly**

```bash
python scripts/relationship_extraction.py --test --classify 2>&1 | grep ERROR
```
Expected: `[ERROR] --classify requires --model <model_name>`

No commit needed — this is validation only.

---

### Task 7: Run full pipeline validation

**Step 1:**

```bash
make run-resolution
```
Expected: completes; stats show `classified: N` where N > 0.

**Step 2: Check at least two key pairs are classified**

```bash
python -c "
import json, glob, os
# Find the relationships output — may be in processing_output or a pipeline run file
for pattern in [
    'library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/relationships*.json',
    '.studio/runs/*/relationship-extraction/output.json',
]:
    for f in glob.glob(pattern):
        data = json.load(open(f))
        rels = data.get('relationships', [])
        typed = [r for r in rels if r.get('relationship_type')]
        print(f'{f}: {len(typed)}/{len(rels)} classified')
        for r in typed[:5]:
            print(f'  {r[\"entity_a\"]} ↔ {r[\"entity_b\"]}: {r[\"relationship_type\"]}')
"
```
Expected: Celaena↔Chaol and Celaena↔Dorian have non-null `relationship_type`.
