# Alias Resolution LLM Pass Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Wire an optional Ollama-backed `llm_confirmer` into `alias_resolution.py` to resolve ambiguous alias pairs that deterministic heuristics cannot confirm.

**Architecture:** All changes are in `scripts/alias_resolution.py`. A `_pick_snippets` helper selects the 3 best context snippets per entity. `make_ollama_confirmer` builds a callable that formats a minimal prompt, calls Ollama, and parses JSON back. `main()` reads `use_llm` / `llm_model` from `additional_context` and passes the confirmer only if Ollama is reachable.

**Tech Stack:** Python stdlib `urllib`, `json`, `re`, `warnings`. No new dependencies. Ollama at `http://localhost:11434` (or `OLLAMA_URL` env var, already used in the repo).

---

## Task 1: `_pick_snippets` helper

**Files:**
- Modify: `scripts/alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

### Step 1: Write the failing test

Add to `tests/test_alias_resolution.py`:

```python
from scripts.alias_resolution import _pick_snippets

def test_pick_snippets_prioritises_canonical_name():
    entity = {
        "canonical_name": "Celaena",
        "aliases": ["Celaena"],
        "source_ids": ["e1"],
    }
    persons_full = {
        "e1": {
            "mentions_by_chapter": {
                "ch01": ["Someone entered.", "Celaena smiled.", "A guard stood."],
                "ch02": ["Celaena ran.", "Another person spoke."],
            }
        }
    }
    snippets = _pick_snippets(entity, persons_full, n=3)
    assert len(snippets) == 3
    # Snippets containing the name come first
    assert snippets[0] in ("Celaena smiled.", "Celaena ran.")
    assert snippets[1] in ("Celaena smiled.", "Celaena ran.")


def test_pick_snippets_falls_back_when_name_not_in_any_snippet():
    entity = {
        "canonical_name": "The Stranger",
        "aliases": [],
        "source_ids": ["e2"],
    }
    persons_full = {
        "e2": {
            "mentions_by_chapter": {
                "ch01": ["Someone appeared.", "A figure moved."],
            }
        }
    }
    snippets = _pick_snippets(entity, persons_full, n=3)
    assert len(snippets) == 2  # only 2 available


def test_pick_snippets_empty_when_no_source_ids():
    entity = {"canonical_name": "Ghost", "aliases": [], "source_ids": []}
    assert _pick_snippets(entity, {}, n=3) == []
```

### Step 2: Run to verify it fails

```bash
pytest tests/test_alias_resolution.py::test_pick_snippets_prioritises_canonical_name -v
```

Expected: `ImportError` or `AttributeError` — `_pick_snippets` not yet defined.

### Step 3: Implement `_pick_snippets`

Add after `_gather_contexts` in `scripts/alias_resolution.py`:

```python
def _pick_snippets(entity: dict, persons_full: dict, n: int = 3) -> list[str]:
    """Return up to n snippets for entity, prioritising those containing the canonical name."""
    all_snippets = _gather_contexts(entity, persons_full)
    name = (entity.get("canonical_name") or "").lower()
    with_name = [s for s in all_snippets if name and name in s.lower()]
    without_name = [s for s in all_snippets if s not in with_name]
    ordered = with_name + without_name
    return ordered[:n]
```

### Step 4: Run tests to verify they pass

```bash
pytest tests/test_alias_resolution.py::test_pick_snippets_prioritises_canonical_name tests/test_alias_resolution.py::test_pick_snippets_falls_back_when_name_not_in_any_snippet tests/test_alias_resolution.py::test_pick_snippets_empty_when_no_source_ids -v
```

Expected: all 3 PASS.

### Step 5: Run full suite to check no regression

```bash
pytest -q
```

Expected: same pass count as before (288 passed).

### Step 6: Commit

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-253): add _pick_snippets helper for LLM context selection"
```

---

## Task 2: `_check_ollama_available` helper

**Files:**
- Modify: `scripts/alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

### Step 1: Write the failing test

Add to `tests/test_alias_resolution.py`:

```python
import unittest.mock as mock
from scripts.alias_resolution import _check_ollama_available

def test_check_ollama_available_returns_true_on_success():
    with mock.patch("urllib.request.urlopen") as m:
        m.return_value.__enter__ = lambda s: s
        m.return_value.__exit__ = mock.Mock(return_value=False)
        assert _check_ollama_available("http://localhost:11434") is True


def test_check_ollama_available_returns_false_on_connection_error():
    import urllib.error
    with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert _check_ollama_available("http://localhost:11434") is False


def test_check_ollama_available_returns_false_on_timeout():
    import socket
    with mock.patch("urllib.request.urlopen", side_effect=socket.timeout()):
        assert _check_ollama_available("http://localhost:11434") is False
```

### Step 2: Run to verify it fails

```bash
pytest tests/test_alias_resolution.py::test_check_ollama_available_returns_true_on_success -v
```

Expected: `ImportError` — `_check_ollama_available` not defined.

### Step 3: Implement `_check_ollama_available`

Add near the top of `scripts/alias_resolution.py`, after imports, before `_PATTERN_TEMPLATES`:

```python
import socket
import urllib.error
import urllib.request
import warnings
```

Then add the function after `_empty_stats`:

```python
def _check_ollama_available(url: str, timeout: int = 2) -> bool:
    """Return True if Ollama is reachable at url/api/tags."""
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout):
            return True
    except (urllib.error.URLError, socket.timeout, OSError):
        return False
```

### Step 4: Run tests

```bash
pytest tests/test_alias_resolution.py::test_check_ollama_available_returns_true_on_success tests/test_alias_resolution.py::test_check_ollama_available_returns_false_on_connection_error tests/test_alias_resolution.py::test_check_ollama_available_returns_false_on_timeout -v
```

Expected: all 3 PASS.

### Step 5: Run full suite

```bash
pytest -q
```

### Step 6: Commit

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-253): add _check_ollama_available with graceful timeout handling"
```

---

## Task 3: `make_ollama_confirmer` factory

**Files:**
- Modify: `scripts/alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

### Step 1: Write the failing tests

Add to `tests/test_alias_resolution.py`:

```python
import unittest.mock as mock
from scripts.alias_resolution import make_ollama_confirmer

_ENTITY_A = {
    "canonical_name": "Celaena",
    "aliases": ["Celaena"],
    "source_ids": ["e1"],
    "type": "PERSON",
    "relevant": True,
}
_ENTITY_B = {
    "canonical_name": "Lillian",
    "aliases": ["Lillian"],
    "source_ids": ["e2"],
    "type": "PERSON",
    "relevant": True,
}
_PERSONS_FULL_LLM = {
    "e1": {"mentions_by_chapter": {"ch01": ["Celaena walked in."]}},
    "e2": {"mentions_by_chapter": {"ch01": ["Lillian watched her."]}},
}


def _mock_ollama_response(payload: dict) -> mock.MagicMock:
    body = json.dumps({"response": json.dumps(payload)}).encode()
    cm = mock.MagicMock()
    cm.__enter__ = lambda s: s
    cm.__exit__ = mock.Mock(return_value=False)
    cm.read.return_value = body
    return cm


def test_make_ollama_confirmer_returns_same_person_true():
    with mock.patch("urllib.request.urlopen", return_value=_mock_ollama_response(
        {"same_person": True, "confidence": "high", "evidence": "same person confirmed"}
    )):
        confirmer = make_ollama_confirmer("mistral", "http://localhost:11434", timeout=10)
        result = confirmer({
            "entity_a": _ENTITY_A,
            "entity_b": _ENTITY_B,
            "evidence": {"snippet": "her real name was Lillian"},
            "persons_full": _PERSONS_FULL_LLM,
        })
    assert result["same_person"] is True
    assert result["confidence"] == "high"


def test_make_ollama_confirmer_returns_same_person_false():
    with mock.patch("urllib.request.urlopen", return_value=_mock_ollama_response(
        {"same_person": False, "confidence": "low", "evidence": "different people"}
    )):
        confirmer = make_ollama_confirmer("mistral", "http://localhost:11434", timeout=10)
        result = confirmer({
            "entity_a": _ENTITY_A,
            "entity_b": _ENTITY_B,
            "evidence": {"snippet": "another name was mentioned"},
            "persons_full": _PERSONS_FULL_LLM,
        })
    assert result["same_person"] is False


def test_make_ollama_confirmer_handles_json_wrapped_in_prose():
    prose = 'Sure! Here is my answer: {"same_person": true, "confidence": "medium", "evidence": "yes"} Hope that helps.'
    body = json.dumps({"response": prose}).encode()
    cm = mock.MagicMock()
    cm.__enter__ = lambda s: s
    cm.__exit__ = mock.Mock(return_value=False)
    cm.read.return_value = body
    with mock.patch("urllib.request.urlopen", return_value=cm):
        confirmer = make_ollama_confirmer("mistral", "http://localhost:11434", timeout=10)
        result = confirmer({
            "entity_a": _ENTITY_A,
            "entity_b": _ENTITY_B,
            "evidence": {"snippet": "alias"},
            "persons_full": _PERSONS_FULL_LLM,
        })
    assert result is not None
    assert result["same_person"] is True


def test_make_ollama_confirmer_returns_none_on_unparseable_response():
    body = json.dumps({"response": "I cannot determine that."}).encode()
    cm = mock.MagicMock()
    cm.__enter__ = lambda s: s
    cm.__exit__ = mock.Mock(return_value=False)
    cm.read.return_value = body
    with mock.patch("urllib.request.urlopen", return_value=cm):
        confirmer = make_ollama_confirmer("mistral", "http://localhost:11434", timeout=10)
        result = confirmer({
            "entity_a": _ENTITY_A,
            "entity_b": _ENTITY_B,
            "evidence": {"snippet": "alias"},
            "persons_full": _PERSONS_FULL_LLM,
        })
    assert result is None
```

### Step 2: Run to verify it fails

```bash
pytest tests/test_alias_resolution.py::test_make_ollama_confirmer_returns_same_person_true -v
```

Expected: `ImportError` — `make_ollama_confirmer` not defined.

### Step 3: Implement `make_ollama_confirmer`

Add after `_check_ollama_available` in `scripts/alias_resolution.py`:

```python
_OLLAMA_URL = "http://localhost:11434"

_LLM_PROMPT_TEMPLATE = """\
Given two character entities from a novel, determine if they refer to the same person.

Entity A: "{name_a}"
Snippets:
{snippets_a}

Entity B: "{name_b}"
Snippets:
{snippets_b}

Signal: "{signal}"

Reply ONLY with valid JSON:
{{"same_person": true/false, "confidence": "high"/"medium"/"low", "evidence": "<one sentence>"}}"""


def _parse_llm_response(text: str) -> dict | None:
    """Try json.loads, then regex extraction, then return None."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'\{[^{}]+\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def make_ollama_confirmer(model: str, url: str, timeout: int):
    """Return an llm_confirmer callable backed by Ollama."""

    def confirmer(candidate: dict):
        entity_a = candidate["entity_a"]
        entity_b = candidate["entity_b"]
        evidence = candidate["evidence"]
        persons_full = candidate.get("persons_full", {})

        snippets_a = _pick_snippets(entity_a, persons_full)
        snippets_b = _pick_snippets(entity_b, persons_full)

        def fmt_snippets(snippets: list[str]) -> str:
            if not snippets:
                return "- (no context available)"
            return "\n".join(f"- {s[:200]}" for s in snippets)

        prompt = _LLM_PROMPT_TEMPLATE.format(
            name_a=entity_a.get("canonical_name", ""),
            name_b=entity_b.get("canonical_name", ""),
            snippets_a=fmt_snippets(snippets_a),
            snippets_b=fmt_snippets(snippets_b),
            signal=evidence.get("snippet", "")[:300],
        )

        body = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 128},
        }).encode()
        req = urllib.request.Request(
            f"{url}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        raw = data.get("response", "")
        return _parse_llm_response(raw)

    return confirmer
```

### Step 4: Run tests

```bash
pytest tests/test_alias_resolution.py::test_make_ollama_confirmer_returns_same_person_true tests/test_alias_resolution.py::test_make_ollama_confirmer_returns_same_person_false tests/test_alias_resolution.py::test_make_ollama_confirmer_handles_json_wrapped_in_prose tests/test_alias_resolution.py::test_make_ollama_confirmer_returns_none_on_unparseable_response -v
```

Expected: all 4 PASS.

### Step 5: Run full suite

```bash
pytest -q
```

### Step 6: Commit

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-253): add make_ollama_confirmer with prompt template and JSON fallback parsing"
```

---

## Task 4: Wire `persons_full` into the confirmer call

**Context:** `resolve_aliases` calls `llm_confirmer({"entity_a": ..., "entity_b": ..., "evidence": ...})` — it does not currently pass `persons_full`. The confirmer needs it to call `_pick_snippets`. We need to update the call site so `persons_full` is available to the confirmer.

**Files:**
- Modify: `scripts/alias_resolution.py`

### Step 1: Verify the existing test still works (it uses a mock that ignores `persons_full`)

```bash
pytest tests/test_alias_resolution.py::test_medium_confidence_pair_requires_llm_confirmation -v
```

Expected: PASS (mock ignores the extra key, no regression).

### Step 2: Update the call site in `resolve_aliases`

In `resolve_aliases`, find the line:

```python
decision = llm_confirmer({
    "entity_a": entity,
    "entity_b": candidate,
    "evidence": reveal,
}) or {}
```

Change it to:

```python
decision = llm_confirmer({
    "entity_a": entity,
    "entity_b": candidate,
    "evidence": reveal,
    "persons_full": persons_full,
}) or {}
```

### Step 3: Run full suite

```bash
pytest -q
```

Expected: same pass count, no regression.

### Step 4: Commit

```bash
git add scripts/alias_resolution.py
git commit -m "feat(STU-253): pass persons_full to llm_confirmer for snippet selection"
```

---

## Task 5: Wire `make_ollama_confirmer` into `main()`

**Files:**
- Modify: `scripts/alias_resolution.py`
- Test: `tests/test_alias_resolution.py`

### Step 1: Write the failing test (stdin contract with `use_llm=true`, Ollama unavailable)

Add to `tests/test_alias_resolution.py`:

```python
def test_script_use_llm_false_by_default(tmp_path):
    """use_llm defaults to false — no llm_confirmer instantiated, no Ollama call."""
    book_yaml = tmp_path / "library" / "a" / "s" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n")
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(json.dumps({"persons_full": {}}))

    payload = {
        "previous_outputs": {"resolve-clusters": {"entities": [], "narrator": None}},
        "additional_context": f"file_path: {book_yaml}\n",
    }
    result = subprocess.run(
        [sys.executable, "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, result.stderr
    # No Ollama warning when use_llm is false
    assert "ollama" not in result.stderr.lower()


def test_script_use_llm_true_warns_when_ollama_unavailable(tmp_path):
    """use_llm=true but Ollama unreachable → warn + graceful skip."""
    book_yaml = tmp_path / "library" / "a" / "s" / "books" / "book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("title: Test\n")
    processing = tmp_path / "library" / "a" / "s" / "processing_output" / "book"
    processing.mkdir(parents=True)
    (processing / "persons_full.json").write_text(json.dumps({"persons_full": {}}))

    payload = {
        "previous_outputs": {"resolve-clusters": {"entities": [], "narrator": None}},
        "additional_context": f"file_path: {book_yaml}\nuse_llm: true\nllm_model: mistral\n",
    }
    # Point to a port that's definitely not listening
    env = {**os.environ, "OLLAMA_URL": "http://127.0.0.1:19999"}
    result = subprocess.run(
        [sys.executable, "scripts/alias_resolution.py"],
        input=json.dumps(payload),
        capture_output=True, text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert "ollama" in result.stderr.lower()
```

### Step 2: Run to verify the second test fails

```bash
pytest tests/test_alias_resolution.py::test_script_use_llm_true_warns_when_ollama_unavailable -v
```

Expected: FAIL — no warning currently emitted.

### Step 3: Update `main()` in `scripts/alias_resolution.py`

Replace the current `main()` body with:

```python
def main() -> None:
    payload = json.load(sys.stdin)
    previous_outputs = payload.get("previous_outputs", {})
    resolve_output = previous_outputs.get("resolve-clusters", {})
    entities = resolve_output.get("entities", [])
    narrator = resolve_output.get("narrator")

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    spacy_model = ctx.get("spacy_model", "en_core_web_lg")
    export_categories = ctx.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(spacy_model)
    reveal_words = tuple(load_lang_config(language).get("reveal_words", _REVEAL_WORDS))

    persons_full = {}
    try:
        paths = _paths_from_payload(payload)
        persons_full = _load_persons_full(paths.processing)
    except ValueError:
        persons_full = {}

    llm_confirmer = None
    use_llm = ctx.get("use_llm", False)
    if use_llm:
        ollama_url = os.environ.get("OLLAMA_URL", _OLLAMA_URL)
        llm_model = ctx.get("llm_model", "mistral")
        if _check_ollama_available(ollama_url):
            llm_confirmer = make_ollama_confirmer(llm_model, ollama_url, timeout=30)
        else:
            warnings.warn(
                f"Ollama not available at {ollama_url} — LLM alias confirmation skipped.",
                stacklevel=1,
            )

    result = resolve_aliases(
        entities, persons_full=persons_full, narrator=narrator,
        llm_confirmer=llm_confirmer, reveal_words=reveal_words,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)
```

Also add `import os` at the top of the file if not already present.

### Step 4: Run the two new tests

```bash
pytest tests/test_alias_resolution.py::test_script_use_llm_false_by_default tests/test_alias_resolution.py::test_script_use_llm_true_warns_when_ollama_unavailable -v
```

Expected: both PASS.

### Step 5: Run full suite

```bash
pytest -q
```

Expected: 291+ passed, 0 failed.

### Step 6: Commit

```bash
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(STU-253): wire make_ollama_confirmer into main() with use_llm flag and graceful skip"
```

---

## Task 6: Final verification

### Step 1: Run the full test suite one last time

```bash
pytest -q
```

Expected: all tests pass, count ≥ 291.

### Step 2: Quick smoke test of the script contract

```bash
echo '{"previous_outputs": {"resolve-clusters": {"entities": [], "narrator": null}}, "additional_context": ""}' \
  | python scripts/alias_resolution.py
```

Expected: `{"entities": [], "narrator": null, "stats": {...}}` with no errors.

### Step 3: Invoke finishing skill

Use `superpowers:finishing-a-development-branch` to decide on merge / PR.
