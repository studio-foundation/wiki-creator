# STU-262: Relationship Classification Fix — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `relationship_type` non-null by wiring classify to Ollama and activating it in the book config.

**Architecture:** Two surgical changes — (1) replace the Anthropic client in `classify_relationships()` with Ollama HTTP calls (same pattern as `alias_resolution.py`), reading `llm_model`/`ollama_url` from the book YAML context; (2) add `classify: true` to `01-throne-of-glass.yaml`. No new files.

**Tech Stack:** Python stdlib `urllib`, Ollama `/api/generate`, `json`, `yaml`

---

### Task 1: Add `_check_ollama_available` and `_call_ollama_classify_json` helpers to `relationship_extraction.py`

**Files:**
- Modify: `scripts/relationship_extraction.py` (around line 798, before `classify_relationships`)

**Step 1: Write the failing test**

Add to `tests/test_relationship_extraction.py` (create the file if it doesn't exist — check first with `ls tests/`):

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
    mock_resp.read.return_value = b'{"response": "{\"relationship_type\": \"ami\", \"direction\": \"symétrique\", \"evolution\": \"ils deviennent amis\", \"key_moments\": [\"ch01: rencontre\"]}"}'
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

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_relationship_extraction.py -v -k "ollama_available or ollama_classify_json"
```
Expected: ImportError or AttributeError — `_check_ollama_available` and `_call_ollama_classify_json` don't exist yet.

**Step 3: Implement the helpers**

In `scripts/relationship_extraction.py`, add these two functions right before `classify_relationships()` (around line 797). Also add `import socket` near the top imports if not already present.

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

Check that `import socket` and `import urllib.request` are already at the top of the file (`grep -n "^import socket\|^import urllib" scripts/relationship_extraction.py`). Add if missing.

**Step 4: Run tests to verify they pass**

```bash
pytest tests/test_relationship_extraction.py -v -k "ollama_available or ollama_classify_json"
```
Expected: 5 PASS

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-262): add Ollama helpers to relationship_extraction"
```

---

### Task 2: Rewrite `classify_relationships()` to use Ollama

**Files:**
- Modify: `scripts/relationship_extraction.py:798-844` (the `classify_relationships` function)

**Step 1: Write the failing test**

Add to `tests/test_relationship_extraction.py`:

```python
from scripts.relationship_extraction import classify_relationships

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
        result = classify_relationships(_SAMPLE_RELS, model="qwen2.5", ollama_url="http://localhost:11434")
    assert result[0]["relationship_type"] == "antagoniste"
    assert result[0]["direction"] == "symétrique"
    assert result[0]["key_moments"] == ["ch01: première rencontre"]

def test_classify_relationships_returns_unchanged_when_ollama_unavailable():
    with patch("scripts.relationship_extraction._check_ollama_available", return_value=False):
        result = classify_relationships(_SAMPLE_RELS, model="qwen2.5", ollama_url="http://localhost:11434")
    assert result[0]["relationship_type"] is None
    assert len(result) == 1

def test_classify_relationships_keeps_null_on_per_pair_failure():
    with patch("scripts.relationship_extraction._check_ollama_available", return_value=True), \
         patch("scripts.relationship_extraction._call_ollama_classify_json", return_value=None):
        result = classify_relationships(_SAMPLE_RELS, model="qwen2.5", ollama_url="http://localhost:11434")
    assert result[0]["relationship_type"] is None
    assert len(result) == 1  # pair still included, not dropped
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_relationship_extraction.py -v -k "classify_relationships"
```
Expected: FAIL (current function uses anthropic, not the new helpers)

**Step 3: Replace `classify_relationships()`**

Replace the entire `classify_relationships` function (lines 798–844) with:

```python
def classify_relationships(
    relationships: list[dict],
    model: str = "qwen2.5",
    ollama_url: str = _OLLAMA_URL,
) -> list[dict]:
    """Classify relationships using Ollama. Fails gracefully per pair."""
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

**Step 4: Run tests**

```bash
pytest tests/test_relationship_extraction.py -v -k "classify_relationships"
```
Expected: 3 PASS

**Step 5: Run full test suite to check for regressions**

```bash
pytest -q
```
Expected: same pass count as before (288+)

**Step 6: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-262): rewrite classify_relationships to use Ollama instead of Anthropic"
```

---

### Task 3: Pass `llm_model` and `ollama_url` from pipeline context into `classify_relationships()`

**Files:**
- Modify: `scripts/relationship_extraction.py:1145-1199` (pipeline stdin block)

**Step 1: Write the failing test**

Add to `tests/test_relationship_extraction.py`:

```python
import json as _json
import io
from unittest.mock import patch

def _make_pipeline_payload(classify=True, llm_model="qwen2.5", ollama_url=None):
    additional = f"classify: {str(classify).lower()}\nllm_model: {llm_model}"
    if ollama_url:
        additional += f"\nollama_url: {ollama_url}"
    return {
        "additional_context": additional,
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

def test_pipeline_passes_llm_model_to_classify(tmp_path, monkeypatch):
    """classify_relationships receives the model from the book YAML context."""
    payload = _make_pipeline_payload(classify=True, llm_model="qwen2.5")
    captured = {}

    def fake_classify(rels, model="qwen2.5", ollama_url=_OLLAMA_URL):
        captured["model"] = model
        captured["ollama_url"] = ollama_url
        return rels

    monkeypatch.setattr("scripts.relationship_extraction.classify_relationships", fake_classify)

    # Run main() with mocked stdin/stdout
    import scripts.relationship_extraction as rel_mod
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    out = io.StringIO()
    monkeypatch.setattr("sys.stdout", out)
    # Patch file loading to return empty
    monkeypatch.setattr(rel_mod, "_load_mentions_from_files", lambda p: {})
    monkeypatch.setattr(rel_mod, "_paths_from_payload", lambda p: None)

    rel_mod.main()
    assert captured.get("model") == "qwen2.5"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_relationship_extraction.py -v -k "pipeline_passes_llm_model"
```
Expected: FAIL — `classify_relationships` is called without `model` kwarg currently.

**Step 3: Update the pipeline classify call**

In the pipeline stdin block, extend the context parsing (around line 1156) and update the classify call (line 1198):

```python
# In the additional_context parsing block, add:
llm_model = additional.get("llm_model", "qwen2.5")
ollama_url = additional.get("ollama_url", os.environ.get("OLLAMA_URL", _OLLAMA_URL))
```

And change line 1198 from:
```python
relationships = classify_relationships(relationships)
```
to:
```python
relationships = classify_relationships(relationships, model=llm_model, ollama_url=ollama_url)
```

Note: `llm_model` and `ollama_url` need default values before the `if raw_context:` block in case parsing is skipped:
```python
llm_model = "qwen2.5"
ollama_url = os.environ.get("OLLAMA_URL", _OLLAMA_URL)
```

**Step 4: Run tests**

```bash
pytest tests/test_relationship_extraction.py -v
pytest -q
```
Expected: all pass

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(STU-262): pass llm_model and ollama_url from context to classify_relationships"
```

---

### Task 4: Add `classify: true` to the Throne of Glass book YAML

**Files:**
- Modify: `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Step 1: Add the flag**

In `01-throne-of-glass.yaml`, after `use_llm: true` on line 10, add:

```yaml
classify: true
```

So lines 9–12 become:
```yaml
coref: false
use_llm: true
classify: true
llm_model: qwen2.5
```

**Step 2: Verify the YAML is valid**

```bash
python -c "import yaml; yaml.safe_load(open('library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml'))"
```
Expected: no output (no error)

**Step 3: Commit**

```bash
git add library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(STU-262): activate classify: true for Throne of Glass"
```

---

### Task 5: Smoke test — verify end-to-end with `--test --classify`

This confirms the Ollama path works before running the full pipeline.

**Step 1: Run the test mode with classify**

```bash
python scripts/relationship_extraction.py --test --classify
```
Expected output includes:
```
=== CLASSIFY MODE ===
Classified N/N relationships
  David Martín ↔ Pedro Vidal: <non-null type> (<direction>)
```
If Ollama isn't running: `[ERROR] Ollama not available` — start Ollama and retry.

**Step 2: No commit needed** — this is just validation.

---

### Task 6: Run full pipeline validation

**Step 1: Run resolution pipeline**

```bash
make run-resolution
```
Expected: completes without error; logs show `classified: N` where N > 0 in the stats.

**Step 2: Check output**

```bash
python -c "
import json
data = json.load(open('library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/relationships_full.json'))
typed = [r for r in data['relationships'] if r.get('relationship_type')]
print(f'{len(typed)}/{len(data[\"relationships\"])} classified')
for r in typed[:5]:
    print(f'  {r[\"entity_a\"]} ↔ {r[\"entity_b\"]}: {r[\"relationship_type\"]}')
"
```
Expected: at least Celaena↔Chaol and Celaena↔Dorian are classified.

(The output path may vary — check `wiki_creator/paths.py` if `relationships_full.json` isn't there; the file may be embedded in the pipeline stage output JSON.)
