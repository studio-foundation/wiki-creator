# Embedding Disambiguation Strategy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a semantic embedding merge strategy to alias-resolution that proposes merges lexical matching cannot reach (no char overlap) and vetoes ambiguous merges on dissimilar mention contexts.

**Architecture:** New pure module `wiki_creator/embedding_disambiguation.py` (numpy-only public path, sentence-transformers lazy). Two anchor points inside `scripts/alias_resolution.py:resolve_aliases`: a **veto** wrapping the ambiguous (reveal/role-symmetric) branch, and a **proposer** `_detect_embedding_alias` appended last in the detector ladder. Evidence flows to `MergeDecision(strategy="embedding_disambiguation")` unchanged via `Registry.from_artifacts` (reads the `alias_resolution.method` field verbatim).

**Tech Stack:** Python, numpy (already transitive via spaCy), sentence-transformers (`intfloat/multilingual-e5-small`, optional extra), pytest.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-07-12-embedding-disambiguation-strategy-design.md` (verbatim source of truth).
- **Backward-compat:** `resolve_aliases(..., judge=None)` MUST produce bit-identical output to today. The full existing `tests/test_alias_resolution.py` suite (1461 lines) MUST stay green.
- **Opt-in:** feature off by default (book YAML `embedding_disambiguation.enabled: false`). Missing deps + enabled → warn + degrade, never crash.
- **No hardcoded vocabulary** (repo invariant). Only numeric thresholds live in YAML/constants — no word lists.
- **numpy is always available** (spaCy pulls it) → the pure module's math path runs in CI. Only `sentence_transformers` is truly optional and MUST be imported lazily.
- Model: `intfloat/multilingual-e5-small`; e5 requires the `passage: ` prefix on each encoded text; embeddings L2-normalized.
- Device idiom mirrors `scripts/relationship_extraction.py:_resolve_coref_device` (cuda if available, else cpu).
- Default thresholds (constants, tuned in Task 5): `DEFAULT_PROPOSE_THRESHOLD = 0.86`, `DEFAULT_VETO_THRESHOLD = 0.80`.
- Run in the worktree `.claude/worktrees/stu-468` (branch `arianedguay/stu-468-...`). Commit after every task.

## File Structure

| File | Responsibility |
|---|---|
| `wiki_creator/embedding_disambiguation.py` | NEW. Pure logic: `cosine`, `entity_centroid`, `Verdict`, `EmbeddingJudge` (numpy-only) + `EmbeddingBackend` (lazy sentence-transformers). |
| `scripts/alias_resolution.py` | MODIFY. `judge` param on `resolve_aliases`; veto + proposer in ladder; `_detect_embedding_alias`; `main()` wiring. |
| `pyproject.toml` | MODIFY. Add optional extra `embeddings`. |
| `tests/_markers.py` | MODIFY. Add `requires_embeddings` skip marker. |
| `tests/test_embedding_disambiguation.py` | NEW. Unit tests, mocked backend (CI) + one real-model test (skipped without extra). |
| `tests/test_alias_resolution.py` | MODIFY. Add veto / proposer / backward-compat cases. |
| `tests/test_registry.py` | MODIFY. Add `strategy="embedding_disambiguation"` round-trip via `from_artifacts`. |
| `tests/fixtures/embedding_golden_pairs.json` | NEW. Labelled PERSON pairs from committed throne-of-glass data. |
| `scripts/tune_embedding_thresholds.py` | NEW. Dev-only threshold sweep over golden pairs. |
| book YAML (`library/.../01-throne-of-glass.yaml`) | MODIFY. Add opt-in `embedding_disambiguation` block. |

---

## Task 1: Pure module — cosine, centroid, EmbeddingJudge (mocked backend)

**Files:**
- Create: `wiki_creator/embedding_disambiguation.py`
- Test: `tests/test_embedding_disambiguation.py`

**Interfaces:**
- Consumes: nothing (numpy only).
- Produces:
  - `Verdict(decision: str, score: float, method: str = "embedding_disambiguation", confidence: str = "medium")` — frozen dataclass.
  - `cosine(a: np.ndarray, b: np.ndarray) -> float`
  - `_mean_pool_normalize(vecs: np.ndarray) -> np.ndarray` (module-private)
  - `entity_centroid(contexts: list[str], backend) -> np.ndarray | None` — `None` if 0 contexts.
  - `EmbeddingJudge(backend, propose_threshold: float, veto_threshold: float)` with:
    - `build_centroids(contexts_by_key: dict) -> dict` — key → centroid `np.ndarray` or `None`; encodes all contexts in ONE batch.
    - `propose(key_a, key_b, centroids) -> Verdict` — `merge` if cosine ≥ propose_threshold, else `abstain`; abstain if either centroid `None`.
    - `veto(key_a, key_b, centroids) -> bool` — `True` (block) if cosine < veto_threshold; `False` if either centroid `None` (cannot veto without evidence).
  - `DEFAULT_MODEL = "intfloat/multilingual-e5-small"`, `DEFAULT_PROPOSE_THRESHOLD = 0.86`, `DEFAULT_VETO_THRESHOLD = 0.80`.
- A test-only fake backend with `.encode(texts) -> np.ndarray` stands in for `EmbeddingBackend`.

- [ ] **Step 1: Write the failing test file**

```python
# tests/test_embedding_disambiguation.py
import numpy as np
import pytest

from wiki_creator.embedding_disambiguation import (
    Verdict,
    cosine,
    entity_centroid,
    EmbeddingJudge,
    DEFAULT_PROPOSE_THRESHOLD,
    DEFAULT_VETO_THRESHOLD,
)


class FakeBackend:
    """Maps each exact context string to a fixed unit vector."""
    def __init__(self, table):
        self.table = table  # str -> list[float]
    def encode(self, texts):
        rows = []
        for t in texts:
            vec = np.asarray(self.table[t], dtype=np.float32)
            vec = vec / (np.linalg.norm(vec) or 1.0)
            rows.append(vec)
        return np.vstack(rows) if rows else np.zeros((0, 3), dtype=np.float32)


def test_cosine_identical_is_one():
    v = np.array([1.0, 2.0, 3.0])
    assert cosine(v, v) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert cosine(np.array([1.0, 0.0]), np.array([0.0, 1.0])) == pytest.approx(0.0)


def test_entity_centroid_none_on_empty():
    assert entity_centroid([], FakeBackend({})) is None


def test_entity_centroid_mean_pooled_and_normalized():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    c = entity_centroid(["a", "b"], backend)
    assert c is not None
    assert np.linalg.norm(c) == pytest.approx(1.0)          # normalized
    assert c[0] == pytest.approx(c[1])                       # symmetric mean


def test_build_centroids_single_batch_and_none_keys():
    backend = FakeBackend({"x": [1.0, 0.0, 0.0], "y": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, DEFAULT_PROPOSE_THRESHOLD, DEFAULT_VETO_THRESHOLD)
    centroids = judge.build_centroids({0: ["x", "y"], 1: []})
    assert centroids[1] is None
    assert np.linalg.norm(centroids[0]) == pytest.approx(1.0)


def test_propose_merges_above_threshold():
    backend = FakeBackend({"same1": [1.0, 0.0, 0.0], "same2": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["same1"], 1: ["same2"]})
    v = judge.propose(0, 1, centroids)
    assert isinstance(v, Verdict)
    assert v.decision == "merge"
    assert v.method == "embedding_disambiguation"


def test_propose_abstains_below_threshold():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: ["b"]})
    assert judge.propose(0, 1, centroids).decision == "abstain"


def test_propose_abstains_when_centroid_missing():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: []})
    assert judge.propose(0, 1, centroids).decision == "abstain"


def test_veto_blocks_dissimilar():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0], "b": [0.0, 1.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: ["b"]})
    assert judge.veto(0, 1, centroids) is True


def test_veto_allows_similar():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0], "b": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: ["b"]})
    assert judge.veto(0, 1, centroids) is False


def test_veto_false_when_centroid_missing():
    backend = FakeBackend({"a": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, 0.86, 0.80)
    centroids = judge.build_centroids({0: ["a"], 1: []})
    assert judge.veto(0, 1, centroids) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd .claude/worktrees/stu-468 && python -m pytest tests/test_embedding_disambiguation.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_creator.embedding_disambiguation'`

- [ ] **Step 3: Write the module**

```python
# wiki_creator/embedding_disambiguation.py
"""Semantic entity disambiguation via mention-context embeddings (STU-468).

Pure logic + a lazily-loaded sentence-transformers backend. Importing this
module pulls numpy only (always present via spaCy); sentence-transformers is
imported inside EmbeddingBackend.__init__ so the rest of the module — and its
unit tests — run without the optional `embeddings` extra.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_PROPOSE_THRESHOLD = 0.86
DEFAULT_VETO_THRESHOLD = 0.80


@dataclass(frozen=True)
class Verdict:
    decision: str  # "merge" | "abstain"
    score: float
    method: str = "embedding_disambiguation"
    confidence: str = "medium"


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _mean_pool_normalize(vecs: np.ndarray) -> np.ndarray:
    centroid = vecs.mean(axis=0)
    norm = float(np.linalg.norm(centroid))
    return centroid / norm if norm else centroid


def entity_centroid(contexts: list[str], backend) -> np.ndarray | None:
    if not contexts:
        return None
    return _mean_pool_normalize(backend.encode(contexts))


def _confidence_for(score: float, propose_threshold: float) -> str:
    if score >= 0.90:
        return "high"
    if score >= propose_threshold:
        return "medium"
    return "low"


class EmbeddingJudge:
    def __init__(self, backend, propose_threshold: float, veto_threshold: float):
        self.backend = backend
        self.propose_threshold = propose_threshold
        self.veto_threshold = veto_threshold

    def build_centroids(self, contexts_by_key: dict) -> dict:
        """Encode every context in a single batch, then mean-pool per key."""
        flat: list[str] = []
        spans: dict = {}
        for key, contexts in contexts_by_key.items():
            start = len(flat)
            flat.extend(contexts)
            spans[key] = (start, len(flat))
        vecs = self.backend.encode(flat) if flat else None
        out: dict = {}
        for key, (start, end) in spans.items():
            out[key] = None if end == start else _mean_pool_normalize(vecs[start:end])
        return out

    def propose(self, key_a, key_b, centroids) -> Verdict:
        ca, cb = centroids.get(key_a), centroids.get(key_b)
        if ca is None or cb is None:
            return Verdict("abstain", 0.0, confidence="low")
        score = cosine(ca, cb)
        if score >= self.propose_threshold:
            return Verdict("merge", score, confidence=_confidence_for(score, self.propose_threshold))
        return Verdict("abstain", score, confidence="low")

    def veto(self, key_a, key_b, centroids) -> bool:
        ca, cb = centroids.get(key_a), centroids.get(key_b)
        if ca is None or cb is None:
            return False  # no evidence → cannot veto
        return cosine(ca, cb) < self.veto_threshold
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd .claude/worktrees/stu-468 && python -m pytest tests/test_embedding_disambiguation.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Commit**

```bash
cd .claude/worktrees/stu-468
git add wiki_creator/embedding_disambiguation.py tests/test_embedding_disambiguation.py
git commit -m "feat(stu-468): pure embedding-disambiguation module (cosine, centroid, judge)"
```

---

## Task 2: EmbeddingBackend + optional extra + skip marker

**Files:**
- Modify: `wiki_creator/embedding_disambiguation.py`
- Modify: `pyproject.toml` (add `embeddings` extra)
- Modify: `tests/_markers.py` (add `requires_embeddings`)
- Test: `tests/test_embedding_disambiguation.py` (append backend tests)

**Interfaces:**
- Consumes: `Task 1` module.
- Produces:
  - `EmbeddingBackend(model_name: str = DEFAULT_MODEL, device: str | None = None)` with:
    - `resolve_device(explicit: str | None) -> str` — explicit, else `"cuda"` if `torch.cuda.is_available()`, else `"cpu"`.
    - `encode(texts: list[str]) -> np.ndarray` — prefixes `"passage: "`, L2-normalized, returns `(len(texts), dim)` numpy; `(0, dim)`-safe on empty.
  - `tests/_markers.py::requires_embeddings` pytest marker.

- [ ] **Step 1: Write the failing backend test (append to test file)**

```python
# tests/test_embedding_disambiguation.py  (append)
from wiki_creator.embedding_disambiguation import EmbeddingBackend
from tests._markers import requires_embeddings


def test_resolve_device_honors_explicit():
    # Constructing the model is heavy; test resolve_device without __init__.
    assert EmbeddingBackend.resolve_device(object.__new__(EmbeddingBackend), "cpu") == "cpu"


@requires_embeddings
def test_backend_encodes_normalized_vectors():
    backend = EmbeddingBackend(device="cpu")
    vecs = backend.encode(["Celaena drew her blade.", "The assassin moved silently."])
    assert vecs.shape[0] == 2
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-3)


@requires_embeddings
def test_backend_empty_returns_empty():
    backend = EmbeddingBackend(device="cpu")
    vecs = backend.encode([])
    assert vecs.shape[0] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `cd .claude/worktrees/stu-468 && python -m pytest tests/test_embedding_disambiguation.py -q`
Expected: FAIL — `ImportError: cannot import name 'EmbeddingBackend'` (the `@requires_embeddings` tests skip if the extra is absent; the `resolve_device` test still forces the import failure).

- [ ] **Step 3: Add `EmbeddingBackend` to the module**

Append to `wiki_creator/embedding_disambiguation.py`:

```python
class EmbeddingBackend:
    """sentence-transformers wrapper. Lazily imports the heavy deps so the
    rest of this module stays importable without the `embeddings` extra."""

    def __init__(self, model_name: str = DEFAULT_MODEL, device: str | None = None):
        from sentence_transformers import SentenceTransformer  # lazy: may ImportError

        self.device = self.resolve_device(device)
        self.model = SentenceTransformer(model_name, device=self.device)

    def resolve_device(self, explicit: str | None) -> str:
        if explicit:
            return explicit
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except Exception:
            pass
        return "cpu"

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.model.get_sentence_embedding_dimension()), dtype=np.float32)
        return self.model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
```

- [ ] **Step 4: Add the `embeddings` extra to `pyproject.toml`**

Under `[project.optional-dependencies]` (alongside the existing `coref` extra):

```toml
embeddings = ["sentence-transformers>=3", "numpy>=1.24"]
```

- [ ] **Step 5: Add the skip marker to `tests/_markers.py`**

```python
def sentence_transformers_available() -> bool:
    return importlib.util.find_spec("sentence_transformers") is not None


requires_embeddings = pytest.mark.skipif(
    not sentence_transformers_available(),
    reason="requires the embeddings extra (pip install -e '.[embeddings]')",
)
```

- [ ] **Step 6: Run tests**

Run: `cd .claude/worktrees/stu-468 && python -m pytest tests/test_embedding_disambiguation.py -q`
Expected: PASS. Backend model tests show as `s` (skipped) unless `.[embeddings]` is installed; `test_resolve_device_honors_explicit` PASSES.

- [ ] **Step 7: Commit**

```bash
cd .claude/worktrees/stu-468
git add wiki_creator/embedding_disambiguation.py pyproject.toml tests/_markers.py tests/test_embedding_disambiguation.py
git commit -m "feat(stu-468): EmbeddingBackend (e5-small, lazy) + embeddings extra + skip marker"
```

---

## Task 3: Wire judge into alias_resolution (veto + proposer)

**Files:**
- Modify: `scripts/alias_resolution.py` — `resolve_aliases` signature + ladder; new `_detect_embedding_alias`; `main()` wiring.
- Test: `tests/test_alias_resolution.py` (append cases).

**Interfaces:**
- Consumes: `EmbeddingJudge` from Task 1; `_gather_contexts`, `_merge_entities`, `resolve_aliases` (existing).
- Produces:
  - `resolve_aliases(..., judge=None)` — new trailing keyword param; `None` ⇒ current behavior unchanged.
  - `_detect_embedding_alias(index, candidate_index, judge, centroids) -> dict | None` — returns `{"method": "embedding_disambiguation", "confidence": <str>, "snippet": <str>}` on merge, else `None`.
  - Stats: `stats["merges_by_method"]["embedding_disambiguation"]`, `stats["embedding_vetoes"]`.

- [ ] **Step 1: Write failing integration tests (append to `tests/test_alias_resolution.py`)**

```python
# tests/test_alias_resolution.py  (append)
import numpy as np

from wiki_creator.embedding_disambiguation import EmbeddingJudge
from scripts.alias_resolution import resolve_aliases


class _StubBackend:
    """Encodes by looking up the first token of each context in a table."""
    def __init__(self, table, dim=3):
        self.table = table
        self.dim = dim
    def encode(self, texts):
        rows = []
        for t in texts:
            key = t.split()[0].lower() if t.split() else ""
            vec = np.asarray(self.table.get(key, [0.0] * self.dim), dtype=np.float32)
            n = np.linalg.norm(vec)
            rows.append(vec / n if n else vec)
        return np.vstack(rows) if rows else np.zeros((0, self.dim), dtype=np.float32)


def _person(idx, name, source_id):
    return {
        "id": f"e{idx}", "canonical_name": name, "type": "PERSON",
        "relevant": True, "aliases": [name], "source_ids": [source_id],
    }


def _persons_full(mapping):
    # mapping: source_id -> list[str] context sentences
    return {sid: {"mentions_by_chapter": {"c1": ctxs}, "mention_count": len(ctxs)}
            for sid, ctxs in mapping.items()}


def test_judge_none_is_backward_compatible():
    entities = [_person(0, "Celaena", "s0"), _person(1, "Nehemia", "s1")]
    pf = _persons_full({"s0": ["Celaena fought."], "s1": ["Nehemia ruled."]})
    without = resolve_aliases(list(entities), persons_full=pf, judge=None)
    baseline = resolve_aliases(list(entities), persons_full=pf)
    assert without == baseline


def test_embedding_proposer_merges_no_overlap_pair():
    # "Celaena" and "assassin" share no chars but share context direction.
    entities = [_person(0, "Celaena", "s0"), _person(1, "the assassin", "s1")]
    pf = _persons_full({"s0": ["Celaena drew steel."], "s1": ["assassin drew steel."]})
    backend = _StubBackend({"celaena": [1.0, 0.0, 0.0], "assassin": [1.0, 0.0, 0.0]})
    judge = EmbeddingJudge(backend, propose_threshold=0.86, veto_threshold=0.80)
    result = resolve_aliases(entities, persons_full=pf, judge=judge)
    assert len(result["entities"]) == 1
    assert result["stats"]["merges_by_method"]["embedding_disambiguation"] == 1


def test_embedding_veto_blocks_ambiguous_merge():
    # Reveal signal would fire, but dissimilar contexts must veto (no LLM call).
    entities = [_person(0, "Dorian", "s0"), _person(1, "Perrington", "s1")]
    pf = _persons_full({"s0": ["Dorian smiled warmly."], "s1": ["Perrington schemed coldly."]})
    reveal = ("revealed",)
    # Force a reveal signal by giving both a shared reveal context.
    pf["s0"]["mentions_by_chapter"]["c1"].append("revealed Dorian Perrington")
    pf["s1"]["mentions_by_chapter"]["c1"].append("revealed Dorian Perrington")
    backend = _StubBackend({"dorian": [1.0, 0.0, 0.0], "perrington": [0.0, 1.0, 0.0],
                            "revealed": [0.0, 0.0, 1.0]})
    judge = EmbeddingJudge(backend, propose_threshold=0.86, veto_threshold=0.80)

    def _llm(_payload):  # must never be called once vetoed
        raise AssertionError("LLM confirmer called despite veto")

    result = resolve_aliases(entities, persons_full=pf, reveal_words=reveal,
                             llm_confirmer=_llm, judge=judge)
    assert len(result["entities"]) == 2
    assert result["stats"]["embedding_vetoes"] >= 1
```

- [ ] **Step 2: Run to verify failure**

Run: `cd .claude/worktrees/stu-468 && python -m pytest tests/test_alias_resolution.py -q -k "judge or embedding"`
Expected: FAIL — `TypeError: resolve_aliases() got an unexpected keyword argument 'judge'`

- [ ] **Step 3: Add `judge` param + precompute centroids in `resolve_aliases`**

In `scripts/alias_resolution.py`, extend the signature (append after `role_symmetric_min_shared`):

```python
def resolve_aliases(
    entities: list[dict],
    persons_full: dict,
    narrator=None,
    llm_confirmer=None,
    reveal_words: tuple[str, ...] = (),
    role_words: list[str] | None = None,
    connective_words: list[str] | None = None,
    pattern_templates: tuple[str, ...] = (),
    relationships: list[dict] | None = None,
    role_symmetric_min_shared: int = 2,
    judge=None,
) -> dict:
```

Immediately after `consumed: set[int] = set()` (before the role-symmetric precompute), add:

```python
    centroids: dict = {}
    if judge is not None:
        contexts_by_key = {i: _gather_contexts(e, persons_full) for i, e in enumerate(entities)}
        centroids = judge.build_centroids(contexts_by_key)
```

- [ ] **Step 4: Add the veto in the ambiguous branch**

In `resolve_aliases`, locate the block (currently ~line 797-803):

```python
            signal = reveal or role_sym
            if not signal:
                continue

            if llm_confirmer is None:
                stats["ambiguous_pairs"] += 1
                continue
```

Replace it with (veto first; proposer runs on the no-signal path):

```python
            signal = reveal or role_sym
            if not signal:
                if judge is not None:
                    emb = _detect_embedding_alias(index, candidate_index, judge, centroids)
                    if emb:
                        merged = _merge_entities(entity, candidate, emb, persons_full, role_words=role_words)
                        stats["merges_applied"] += 1
                        stats["merges_by_method"]["embedding_disambiguation"] = (
                            stats["merges_by_method"].get("embedding_disambiguation", 0) + 1
                        )
                        consumed.add(candidate_index)
                        break
                continue

            if judge is not None and judge.veto(index, candidate_index, centroids):
                stats["embedding_vetoes"] = stats.get("embedding_vetoes", 0) + 1
                stats["ambiguous_pairs"] += 1
                continue

            if llm_confirmer is None:
                stats["ambiguous_pairs"] += 1
                continue
```

- [ ] **Step 5: Add `_detect_embedding_alias` helper**

Place it next to the other `_detect_*` functions (e.g. just above `resolve_aliases`):

```python
def _detect_embedding_alias(index, candidate_index, judge, centroids) -> dict | None:
    """Semantic merge proposal for a pair with no lexical signal (STU-468).

    Returns an evidence dict in the same shape as the lexical detectors, or
    None to abstain. `method` flows verbatim into MergeDecision.strategy via
    Registry.from_artifacts.
    """
    verdict = judge.propose(index, candidate_index, centroids)
    if verdict.decision != "merge":
        return None
    return {
        "method": "embedding_disambiguation",
        "confidence": verdict.confidence,
        "snippet": f"context cosine={verdict.score:.3f} (embedding disambiguation)",
    }
```

- [ ] **Step 6: Wire the judge in `main()`**

In `scripts/alias_resolution.py:main()`, just before the `result = resolve_aliases(` call (~line 903), add:

```python
    emb_cfg = ctx.get("embedding_disambiguation", {}) or {}
    judge = None
    if emb_cfg.get("enabled"):
        try:
            from wiki_creator.embedding_disambiguation import (
                EmbeddingBackend,
                EmbeddingJudge,
                DEFAULT_MODEL,
                DEFAULT_PROPOSE_THRESHOLD,
                DEFAULT_VETO_THRESHOLD,
            )

            backend = EmbeddingBackend(
                model_name=emb_cfg.get("model", DEFAULT_MODEL),
                device=emb_cfg.get("device"),
            )
            judge = EmbeddingJudge(
                backend,
                propose_threshold=emb_cfg.get("propose_threshold", DEFAULT_PROPOSE_THRESHOLD),
                veto_threshold=emb_cfg.get("veto_threshold", DEFAULT_VETO_THRESHOLD),
            )
        except ImportError as exc:
            warnings.warn(
                f"embedding_disambiguation enabled but deps missing ({exc}); "
                f"install with pip install -e '.[embeddings]' — skipping.",
                stacklevel=1,
            )
            judge = None
```

Then add `judge=judge,` to the `resolve_aliases(...)` call arguments.

- [ ] **Step 7: Run the new tests, then the full alias-resolution suite**

Run: `cd .claude/worktrees/stu-468 && python -m pytest tests/test_alias_resolution.py -q`
Expected: PASS — new cases green AND all pre-existing cases (incl. Run 16 regression at line ~1315) still green.

- [ ] **Step 8: Commit**

```bash
cd .claude/worktrees/stu-468
git add scripts/alias_resolution.py tests/test_alias_resolution.py
git commit -m "feat(stu-468): wire embedding judge into alias-resolution (veto + proposer)"
```

---

## Task 4: Registry round-trip for the new strategy

**Files:**
- Test: `tests/test_registry.py` (append one test).

**Interfaces:**
- Consumes: `Registry.from_artifacts` (existing) — reads `alias_resolution.method` verbatim into `MergeDecision.strategy` (`wiki_creator/registry.py:346,364`).
- Produces: a regression test asserting `strategy="embedding_disambiguation"` survives reconstruction. No production change expected.

- [ ] **Step 1: Write the test**

Model it on the existing `from_artifacts` tests. An entity carrying an `alias_resolution` block with `method: "embedding_disambiguation"` and a `merged_from` alias must yield a `MergeDecision` whose `strategy == "embedding_disambiguation"`.

```python
# tests/test_registry.py  (append)
def test_from_artifacts_preserves_embedding_strategy():
    alias_output = {
        "entities": [
            {
                "canonical_name": "Celaena",
                "type": "PERSON",
                "aliases": ["Celaena", "the assassin"],
                "source_ids": ["s0", "s1"],
                "alias_resolution": {
                    "merged_from": ["the assassin"],
                    "method": "embedding_disambiguation",
                    "confidence": "high",
                    "evidence": [{"snippet": "context cosine=0.910 (embedding disambiguation)"}],
                },
            }
        ]
    }
    full = {
        "s0": {"mention_count": 5, "mentions_by_chapter": {"c1": ["Celaena fought."]}},
        "s1": {"mention_count": 3, "mentions_by_chapter": {"c1": ["The assassin fought."]}},
    }
    reg = Registry.from_artifacts(splits={}, alias_output=alias_output, full_registries=full)
    strategies = {d.strategy for d in reg.audit_log()}
    assert "embedding_disambiguation" in strategies
```

> Note: match the exact `from_artifacts(...)` keyword names used by the neighbouring tests in this file — adjust `splits` / `alias_output` / `full_registries` if the local signature differs.

- [ ] **Step 2: Run to verify (expected PASS if wiring is correct; FAIL localizes any gap)**

Run: `cd .claude/worktrees/stu-468 && python -m pytest tests/test_registry.py -q -k embedding_strategy`
Expected: PASS. If FAIL, inspect `from_artifacts` (`wiki_creator/registry.py:344-390`) — the `method` field must map into `strategy` for aliases in `merged_from`; fix there.

- [ ] **Step 3: Commit**

```bash
cd .claude/worktrees/stu-468
git add tests/test_registry.py
git commit -m "test(stu-468): assert embedding_disambiguation strategy round-trips through registry"
```

---

## Task 5: Golden pairs, tuning script, real-model acceptance test, book opt-in

**Files:**
- Create: `tests/fixtures/embedding_golden_pairs.json`
- Create: `scripts/tune_embedding_thresholds.py`
- Modify: `tests/test_embedding_disambiguation.py` (real-model acceptance test)
- Modify: book YAML `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`

**Interfaces:**
- Consumes: `EmbeddingBackend`, `EmbeddingJudge` (Tasks 1-2); committed `persons_full.json` under `library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/`.
- Produces: labelled fixture + a sweep script that prints precision/recall per threshold; an acceptance test gated by `@requires_embeddings`.

- [ ] **Step 1: Build the golden-pairs fixture from real committed data**

First inspect the committed persons data to get exact surface forms / source_ids:

Run: `cd .claude/worktrees/stu-468 && python -c "import json,glob; p=glob.glob('library/sarah_j_maas/throne-of-glass/processing_output/*/persons_full.json')[0]; d=json.load(open(p))['persons_full']; [print(k, (v.get('raw_mentions') or [])[:3]) for k,v in list(d.items())[:40]]"`

Using the surface forms found, create `tests/fixtures/embedding_golden_pairs.json`. Each entry names two persons by their `source_id` (or canonical surface) plus a `label`. Include the load-bearing pairs:

```json
{
  "processing_glob": "library/sarah_j_maas/throne-of-glass/processing_output/*/persons_full.json",
  "pairs": [
    {"a": "Celaena", "b": "the assassin", "label": "same", "note": "unlock: no char overlap"},
    {"a": "Dorian", "b": "the Crown Prince", "label": "same"},
    {"a": "Perrington", "b": "the Duke", "label": "same"},
    {"a": "Dorian", "b": "Perrington", "label": "different", "note": "ex-STU-430: Crown Prince vs Duke"},
    {"a": "Celaena", "b": "Chaol", "label": "different"}
  ]
}
```

> Adjust the `a`/`b` surface strings to the exact forms present in the inspected `persons_full.json` (e.g. capitalisation, presence of an article). Add a handful more real same/different pairs (target 15-25 total) using names you confirmed exist.

- [ ] **Step 2: Write the tuning script**

```python
# scripts/tune_embedding_thresholds.py
"""Dev-only: sweep propose/veto thresholds over the golden pairs (STU-468).

Not part of any pipeline stage. Requires the `embeddings` extra and the
committed throne-of-glass persons_full.json. Prints precision/recall per
threshold so the winning defaults can be baked into the module constants.

Usage: python scripts/tune_embedding_thresholds.py
"""
import glob
import json
from pathlib import Path

from wiki_creator.embedding_disambiguation import EmbeddingBackend, cosine, entity_centroid

FIXTURE = Path("tests/fixtures/embedding_golden_pairs.json")


def _contexts_for(surface, persons_full):
    for entry in persons_full.values():
        names = set(entry.get("raw_mentions") or [])
        if surface in names:
            out = []
            for ctxs in entry.get("mentions_by_chapter", {}).values():
                out.extend(c for c in ctxs if isinstance(c, str) and c.strip())
            return out
    return []


def main():
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pf_path = glob.glob(spec["processing_glob"])[0]
    persons_full = json.load(open(pf_path, encoding="utf-8"))["persons_full"]
    backend = EmbeddingBackend(device="cpu")

    scored = []
    for pair in spec["pairs"]:
        ca = entity_centroid(_contexts_for(pair["a"], persons_full), backend)
        cb = entity_centroid(_contexts_for(pair["b"], persons_full), backend)
        if ca is None or cb is None:
            print(f"SKIP (no context): {pair['a']} / {pair['b']}")
            continue
        scored.append((cosine(ca, cb), pair["label"], pair["a"], pair["b"]))

    for score, label, a, b in sorted(scored, reverse=True):
        print(f"{score:.3f}  {label:9s}  {a} / {b}")

    print("\nthreshold  precision(same)  recall(same)")
    for thr in [round(0.70 + 0.02 * i, 2) for i in range(16)]:
        tp = sum(1 for s, l, *_ in scored if s >= thr and l == "same")
        fp = sum(1 for s, l, *_ in scored if s >= thr and l == "different")
        fn = sum(1 for s, l, *_ in scored if s < thr and l == "same")
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        print(f"{thr:.2f}       {prec:.2f}             {rec:.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the sweep (local, requires the extra + model download)**

Run: `cd .claude/worktrees/stu-468 && pip install -e '.[embeddings]' && python scripts/tune_embedding_thresholds.py`
Expected: a per-pair cosine table + a precision/recall grid. Pick `propose_threshold` = lowest τ with precision(same)=1.00 (no `different` pair merged — Dorian/Perrington MUST stay below it), and `veto_threshold` ≤ the lowest `same`-pair score (so no true alias is vetoed). If the tuned values differ from the `0.86 / 0.80` defaults, update `DEFAULT_PROPOSE_THRESHOLD` / `DEFAULT_VETO_THRESHOLD` in `wiki_creator/embedding_disambiguation.py`.

- [ ] **Step 4: Write the real-model acceptance test**

```python
# tests/test_embedding_disambiguation.py  (append)
import glob
import json
from pathlib import Path

from wiki_creator.embedding_disambiguation import (
    EmbeddingBackend, entity_centroid, cosine,
    DEFAULT_PROPOSE_THRESHOLD, DEFAULT_VETO_THRESHOLD,
)

_FIXTURE = Path("tests/fixtures/embedding_golden_pairs.json")


def _contexts_for(surface, persons_full):
    for entry in persons_full.values():
        if surface in set(entry.get("raw_mentions") or []):
            out = []
            for ctxs in entry.get("mentions_by_chapter", {}).values():
                out.extend(c for c in ctxs if isinstance(c, str) and c.strip())
            return out
    return []


@requires_embeddings
def test_golden_pairs_precision_and_key_cases():
    spec = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    pf_path = glob.glob(spec["processing_glob"])[0]
    persons_full = json.load(open(pf_path, encoding="utf-8"))["persons_full"]
    backend = EmbeddingBackend(device="cpu")

    results = {}
    for pair in spec["pairs"]:
        ca = entity_centroid(_contexts_for(pair["a"], persons_full), backend)
        cb = entity_centroid(_contexts_for(pair["b"], persons_full), backend)
        if ca is None or cb is None:
            continue
        results[(pair["a"], pair["b"])] = (cosine(ca, cb), pair["label"])

    # No 'different' pair may reach the propose threshold (precision(same) == 1.0).
    for (a, b), (score, label) in results.items():
        if label == "different":
            assert score < DEFAULT_PROPOSE_THRESHOLD, f"{a}/{b} would wrongly merge ({score:.3f})"

    # The unlock case must clear the propose threshold.
    unlock = results.get(("Celaena", "the assassin"))
    if unlock is not None:
        assert unlock[0] >= DEFAULT_PROPOSE_THRESHOLD, f"unlock pair missed ({unlock[0]:.3f})"
```

> Adjust the `("Celaena", "the assassin")` key to the exact surfaces used in the fixture.

- [ ] **Step 5: Run the acceptance test**

Run: `cd .claude/worktrees/stu-468 && python -m pytest tests/test_embedding_disambiguation.py -q -k golden_pairs`
Expected: PASS (or `s` skipped where the extra is absent). If a `different` pair breaches the propose threshold, raise `DEFAULT_PROPOSE_THRESHOLD` per the Step 3 sweep and re-run.

- [ ] **Step 6: Add the opt-in block to the book YAML**

Append to `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`:

```yaml
embedding_disambiguation:
  enabled: false            # opt-in; flip to true to activate the semantic strategy
  model: intfloat/multilingual-e5-small
  device: null              # null = auto (cuda if available, else cpu)
  propose_threshold: 0.86   # keep in sync with tuned DEFAULT_PROPOSE_THRESHOLD
  veto_threshold: 0.80
```

- [ ] **Step 7: Commit**

```bash
cd .claude/worktrees/stu-468
git add tests/fixtures/embedding_golden_pairs.json scripts/tune_embedding_thresholds.py \
        tests/test_embedding_disambiguation.py \
        library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git commit -m "feat(stu-468): golden pairs, threshold tuner, real-model acceptance test, book opt-in"
```

---

## Final verification

- [ ] **Full suite** — `cd .claude/worktrees/stu-468 && python -m pytest -q`
  Expected: prior baseline (`735 passed, 31 skipped`) + new tests passing; embedding real-model tests skip cleanly unless `.[embeddings]` installed. No regressions.
- [ ] **Type check** — `cd .claude/worktrees/stu-468 && mypy wiki_creator/`
  Expected: clean (module is typed).
- [ ] **Backward-compat proof** — confirm `test_judge_none_is_backward_compatible` passes: `judge=None` output equals the no-judge call.

---

## Self-Review

**Spec coverage:**
- Proposeur → Task 3 (`_detect_embedding_alias` + ladder). ✓
- Veto → Task 3 (ambiguous-branch guard, LLM-skip). ✓
- e5-small, `passage:` prefix, L2-norm → Task 2. ✓
- Centroïde mean-pool → Task 1. ✓
- Single-batch encode → Task 1 `build_centroids`. ✓
- Device idiom → Task 2 `resolve_device`. ✓
- Optional extra + graceful degrade (3 levels: deps / enabled / no-context) → Tasks 2-3 (`main()` try/except, `judge=None`, `centroid None`). ✓
- `MergeDecision(strategy="embedding_disambiguation")` → Task 4. ✓
- Golden pairs + tuning + success criteria (Celaena/assassin merge, Dorian/Perrington stay apart, Run 16 green) → Tasks 3 & 5. ✓
- Book YAML opt-in → Task 5. ✓
- Non-goals (split, non-PERSON, hybrid, disk cache, LLM replacement) — none implemented. ✓

**Placeholder scan:** fixture surface strings and the `from_artifacts` keyword names are flagged as "confirm against real data / local signature" — these are verification instructions with concrete inspection commands, not unfilled blanks. All code steps contain complete code.

**Type consistency:** `EmbeddingJudge(backend, propose_threshold, veto_threshold)`, `build_centroids(contexts_by_key) -> dict`, `propose(key_a, key_b, centroids) -> Verdict`, `veto(...) -> bool`, `_detect_embedding_alias(index, candidate_index, judge, centroids) -> dict | None`, `Verdict(decision, score, method, confidence)` — consistent across Tasks 1, 3, 5.
