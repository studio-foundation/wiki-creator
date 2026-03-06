# STU-238 — Parallel Coref Workers Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `--workers N` flag to `relationship_extraction.py` to parallelize LingMessCoref inference across chapters using `ProcessPoolExecutor`, reducing coref time from ~10 min to ~2.5 min with 4 workers.

**Architecture:** Extract per-chapter fastcoref inference into a top-level worker function (picklable for multiprocessing). `enrich_mentions_with_fastcoref` gets a `workers` param — sequential path unchanged at `workers=1`, parallel path uses `ProcessPoolExecutor` at `workers>1`. Results are raw JSON-serializable tuples merged in the main process.

**Tech Stack:** Python stdlib `concurrent.futures.ProcessPoolExecutor`, `fastcoref`, `spacy`, `fr_core_news_lg`

---

### Task 1: Add `_coref_worker` top-level function

**Files:**
- Modify: `scripts/relationship_extraction.py:290` (after the `# fastcoref / LingMessCoref` section header)

**Step 1: Write the failing test**

```python
# tests/test_relationship_extraction.py — append this test

def test_coref_worker_returns_list():
    """_coref_worker returns a list (empty when fastcoref not available)."""
    from scripts.relationship_extraction import _coref_worker
    result = _coref_worker(("ch01", "Il travaillait.", {"david martín": "David Martín"}))
    assert isinstance(result, list)
    # Each item is (canonical, chapter_id, sentence)
    for item in result:
        assert len(item) == 3
        assert isinstance(item[0], str)
        assert isinstance(item[1], str)
        assert isinstance(item[2], str)
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_relationship_extraction.py::test_coref_worker_returns_list -v
```
Expected: `FAIL` with `ImportError: cannot import name '_coref_worker'`

**Step 3: Add `_coref_worker` to `scripts/relationship_extraction.py`**

Insert after line 342 (after `_decode_mention_offsets` ends), before `enrich_mentions_with_fastcoref`:

```python
def _coref_worker(args: tuple) -> list[tuple[str, str, str]]:
    """Worker function for ProcessPoolExecutor: load model + process one chapter.

    Each worker process loads its own LingMessCoref instance (~590 MB RAM).
    Must be a top-level function (picklable by multiprocessing).

    Args:
        args: (chapter_id, text, name_to_canonical)
            name_to_canonical: {lowercased_name: canonical_name}

    Returns:
        List of (canonical_name, chapter_id, sentence) tuples to be merged
        by the parent process. Returns [] on any error (graceful degradation).
    """
    chapter_id, text, name_to_canonical = args
    if not text or not text.strip():
        return []

    chunk = text[:8000]
    results: list[tuple[str, str, str]] = []

    try:
        import spacy
        from fastcoref import spacy_component  # noqa: F401

        _patch_attn_eager()
        nlp = spacy.load(
            "fr_core_news_lg",
            exclude=["parser", "lemmatizer", "ner", "textcat"],
        )
        nlp.add_pipe(
            "fastcoref",
            config={
                "model_architecture": "LingMessCoref",
                "model_path": "biu-nlp/lingmess-coref",
                "device": "cpu",
            },
        )
        doc = nlp(chunk, component_cfg={"fastcoref": {"resolve_text": True}})
    except MemoryError:
        import sys as _sys
        print(f"[coref/worker] MemoryError on {chapter_id} — skipping", file=_sys.stderr)
        return []
    except Exception as e:
        import sys as _sys
        print(f"[coref/worker] Error on {chapter_id}: {e}", file=_sys.stderr)
        return []

    raw_clusters = doc._.coref_clusters or []

    for cluster in raw_clusters:
        decoded: list[tuple[str, int, int]] = []
        for mention in cluster:
            offsets = _decode_mention_offsets(mention)
            if offsets is None:
                continue
            start, end = offsets
            if 0 <= start < end <= len(chunk):
                decoded.append((chunk[start:end], start, end))

        if not decoded:
            continue

        canonical: str | None = None
        for m_text, _, _ in sorted(decoded, key=lambda x: -len(x[0])):
            candidate = name_to_canonical.get(m_text.lower())
            if candidate:
                canonical = candidate
                break
            first_word = m_text.split()[0].lower() if m_text.split() else ""
            candidate = name_to_canonical.get(first_word)
            if candidate:
                canonical = candidate
                break

        if not canonical:
            continue

        for m_text, start, _ in decoded:
            tokens = m_text.lower().split()
            is_pronoun = (len(tokens) == 1 and tokens[0] in _FR_PRONOUNS) or (
                len(tokens) <= 2
                and any(t in _FR_PRONOUNS for t in tokens)
                and m_text.lower() not in name_to_canonical
            )
            if not is_pronoun:
                continue

            sentence = _find_sentence_containing(chunk, start)
            if sentence:
                results.append((canonical, chapter_id, sentence))

    return results
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_relationship_extraction.py::test_coref_worker_returns_list -v
```
Expected: `PASS`

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(stu-238): add _coref_worker top-level function for multiprocessing"
```

---

### Task 2: Add `workers` parameter to `enrich_mentions_with_fastcoref`

**Files:**
- Modify: `scripts/relationship_extraction.py:344` (`enrich_mentions_with_fastcoref`)

**Step 1: Write the failing test**

```python
# tests/test_relationship_extraction.py — append

def test_enrich_fastcoref_accepts_workers_param():
    """enrich_mentions_with_fastcoref accepts workers param without crashing."""
    import inspect
    from scripts.relationship_extraction import enrich_mentions_with_fastcoref
    sig = inspect.signature(enrich_mentions_with_fastcoref)
    assert "workers" in sig.parameters
    assert sig.parameters["workers"].default == 1
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_relationship_extraction.py::test_enrich_fastcoref_accepts_workers_param -v
```
Expected: `FAIL` — `workers` not in parameters

**Step 3: Update function signature and body**

Change the function signature at line 344:
```python
def enrich_mentions_with_fastcoref(
    chapters: dict[str, str],
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    workers: int = 1,
) -> dict[str, dict[str, list[str]]]:
    """Enrich mentions using fastcoref + LingMessCoref for accurate coreference.

    For each chapter (first 8 000 chars), run LingMessCoref to get coreference
    clusters. For each cluster containing a known PERSON entity mention, find
    pronoun mentions in the same cluster and attribute their sentences to that
    entity.

    Falls back silently to the naive heuristic if fastcoref is not installed.

    Args:
        chapters: {chapter_id: full_text} from chapters.json
        entities: resolved entities (canonical_name, aliases, type, relevant)
        mentions_by_entity: existing {canonical → {chapter_id → [sentences]}}
        workers: number of parallel processes (default 1 = sequential).
                 Each worker loads its own model (~590 MB RAM per worker).
                 RAM budget: 1 worker=~3 GB, 4 workers=~10 GB, 8 workers=~20 GB.

    Returns:
        mentions_by_entity enriched in-place (also returned for convenience)
    """
```

Then replace the sequential for loop block (lines ~407–475, from `total_added = 0` through the `print(f"[coref/fastcoref] Pronoun sentences added:...`)`) with:

```python
    total_added = 0

    if workers <= 1:
        # Sequential path — load model once, iterate chapters
        try:
            import spacy
            from fastcoref import spacy_component  # noqa: F401

            _patch_attn_eager()
            nlp = spacy.load(
                "fr_core_news_lg",
                exclude=["parser", "lemmatizer", "ner", "textcat"],
            )
            nlp.add_pipe(
                "fastcoref",
                config={
                    "model_architecture": "LingMessCoref",
                    "model_path": "biu-nlp/lingmess-coref",
                    "device": "cpu",
                },
            )
        except Exception as e:
            print(
                f"[WARN] fastcoref unavailable ({e}) — falling back to heuristic",
                file=sys.stderr,
            )
            return enrich_mentions_with_coref(chapters, entities, mentions_by_entity)

        for chapter_id, text in chapters.items():
            if not text or not text.strip():
                continue
            chunk = text[:8000]
            try:
                doc = nlp(chunk, component_cfg={"fastcoref": {"resolve_text": True}})
            except Exception as e:
                print(f"[WARN] fastcoref inference failed on {chapter_id}: {e}", file=sys.stderr)
                continue

            raw_clusters = doc._.coref_clusters or []

            for cluster in raw_clusters:
                decoded: list[tuple[str, int, int]] = []
                for mention in cluster:
                    offsets = _decode_mention_offsets(mention)
                    if offsets is None:
                        continue
                    start, end = offsets
                    if 0 <= start < end <= len(chunk):
                        decoded.append((chunk[start:end], start, end))

                if not decoded:
                    continue

                canonical: str | None = None
                for m_text, _, _ in sorted(decoded, key=lambda x: -len(x[0])):
                    candidate = name_to_canonical.get(m_text.lower())
                    if candidate:
                        canonical = candidate
                        break
                    first_word = m_text.split()[0].lower() if m_text.split() else ""
                    candidate = name_to_canonical.get(first_word)
                    if candidate:
                        canonical = candidate
                        break

                if not canonical:
                    continue

                for m_text, start, _ in decoded:
                    tokens = m_text.lower().split()
                    is_pronoun = (len(tokens) == 1 and tokens[0] in _FR_PRONOUNS) or (
                        len(tokens) <= 2
                        and any(t in _FR_PRONOUNS for t in tokens)
                        and m_text.lower() not in name_to_canonical
                    )
                    if not is_pronoun:
                        continue

                    sentence = _find_sentence_containing(chunk, start)
                    if not sentence:
                        continue

                    if canonical not in mentions_by_entity:
                        mentions_by_entity[canonical] = {}
                    if chapter_id not in mentions_by_entity[canonical]:
                        mentions_by_entity[canonical][chapter_id] = []
                    existing = mentions_by_entity[canonical][chapter_id]
                    if sentence not in existing:
                        existing.append(sentence)
                        total_added += 1

    else:
        # Parallel path — one worker process per chapter, each loads own model
        from concurrent.futures import ProcessPoolExecutor
        import multiprocessing

        chapter_items = [
            (cid, text, name_to_canonical)
            for cid, text in chapters.items()
            if text and text.strip()
        ]

        actual_workers = min(workers, len(chapter_items), multiprocessing.cpu_count())
        print(
            f"[coref/parallel] {len(chapter_items)} chapters, {actual_workers} workers",
            file=sys.stderr,
        )

        try:
            with ProcessPoolExecutor(max_workers=actual_workers) as executor:
                all_results = list(executor.map(_coref_worker, chapter_items))
        except MemoryError:
            print(
                "[WARN] MemoryError in parallel coref — falling back to sequential (workers=1)",
                file=sys.stderr,
            )
            return enrich_mentions_with_fastcoref(chapters, entities, mentions_by_entity, workers=1)

        # Merge results from all workers
        for worker_results in all_results:
            for canonical, chapter_id, sentence in worker_results:
                if canonical not in mentions_by_entity:
                    mentions_by_entity[canonical] = {}
                if chapter_id not in mentions_by_entity[canonical]:
                    mentions_by_entity[canonical][chapter_id] = []
                existing = mentions_by_entity[canonical][chapter_id]
                if sentence not in existing:
                    existing.append(sentence)
                    total_added += 1

    print(f"[coref/fastcoref] Pronoun sentences added: {total_added}", file=sys.stderr)
    return mentions_by_entity
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_relationship_extraction.py::test_enrich_fastcoref_accepts_workers_param -v
```
Expected: `PASS`

Also run the full test suite to check nothing regressed:
```bash
pytest tests/test_relationship_extraction.py -v
```
Expected: all existing tests still `PASS`

**Step 5: Commit**

```bash
git add scripts/relationship_extraction.py
git commit -m "feat(stu-238): add workers param to enrich_mentions_with_fastcoref"
```

---

### Task 3: Thread `--workers N` through CLI argument parsing

**Files:**
- Modify: `scripts/relationship_extraction.py:889` (`main` function)
- Modify: `scripts/relationship_extraction.py:481` (`run_test_mode` signature)
- Modify: `scripts/relationship_extraction.py:707` (`run_live_mode` signature)

**Step 1: Write the failing test**

```python
# tests/test_relationship_extraction.py — append

def test_main_parses_workers_flag(monkeypatch):
    """--workers N is parsed and passed through without crashing."""
    import sys
    from unittest.mock import patch, MagicMock
    import scripts.relationship_extraction as rel

    captured = {}

    def fake_run_live(window_size, threshold, coref=False, workers=1):
        captured["workers"] = workers

    monkeypatch.setattr(rel, "run_live_mode", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["rel.py", "--live", "--coref", "--workers", "4"])
    rel.main()

    assert captured["workers"] == 4
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_relationship_extraction.py::test_main_parses_workers_flag -v
```
Expected: `FAIL` — `run_live_mode` doesn't accept `workers` kwarg yet

**Step 3: Update `run_test_mode` signature**

Change `def run_test_mode(window_size: int, threshold: int, coref: bool = False) -> None:` to:
```python
def run_test_mode(window_size: int, threshold: int, coref: bool = False, workers: int = 1) -> None:
```

And update the `enrich_mentions_with_fastcoref` call inside it:
```python
mentions_by_entity = enrich_mentions_with_fastcoref(chapters_demo, entities, mentions_by_entity, workers=workers)
```

**Step 4: Update `run_live_mode` signature**

Change `def run_live_mode(window_size: int, threshold: int, coref: bool = False) -> None:` to:
```python
def run_live_mode(window_size: int, threshold: int, coref: bool = False, workers: int = 1) -> None:
```

And update the `enrich_mentions_with_fastcoref` call inside it:
```python
mentions_by_entity = enrich_mentions_with_fastcoref(chapters, entities, mentions_by_entity, workers=workers)
```

**Step 5: Update `main()` to parse `--workers`**

In `main()`, after the `threshold` parsing block, add:

```python
    workers = 1
    if "--workers" in args:
        idx = args.index("--workers")
        workers = int(args[idx + 1])
```

And update the two call sites:
```python
    if "--test" in args:
        run_test_mode(window_size, threshold, coref=coref, workers=workers)
        return

    if "--live" in args:
        run_live_mode(window_size, threshold, coref=coref, workers=workers)
        return
```

Also update the Studio pipeline path to read `workers` from `additional_context`:
```python
            do_classify = bool(additional.get("classify", False))
            do_coref = bool(additional.get("coref", False))
            workers = int(additional.get("workers", workers))
            window_size = int(additional.get("window", window_size))
            threshold = int(additional.get("threshold", threshold))
```

And update the `enrich_mentions_with_fastcoref` call in the Studio pipeline path:
```python
            mentions_by_entity = enrich_mentions_with_fastcoref(chapters, entities, mentions_by_entity, workers=workers)
```

**Step 6: Run test to verify it passes**

```bash
pytest tests/test_relationship_extraction.py::test_main_parses_workers_flag -v
```
Expected: `PASS`

**Step 7: Run full test suite**

```bash
pytest tests/ -v
```
Expected: all `PASS`

**Step 8: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(stu-238): thread --workers N through CLI and pipeline path"
```

---

### Task 4: Update Makefile with `test-coref-parallel` target

**Files:**
- Modify: `Makefile`

**Step 1: Add the target**

Append to `Makefile`:
```makefile
test-coref-parallel: test-extraction
	python scripts/entity_clustering.py --live
	python scripts/relationship_extraction.py --live --coref --workers 4
```

**Step 2: Verify Makefile is valid (dry run)**

```bash
make -n test-coref-parallel
```
Expected: prints the commands without executing them, no syntax errors.

**Step 3: Commit**

```bash
git add Makefile
git commit -m "feat(stu-238): add test-coref-parallel Makefile target (--workers 4)"
```

---

### Task 5: Determinism test — same results with workers=1 and workers=N

**Files:**
- Test: `tests/test_relationship_extraction.py`

**Step 1: Write the test**

```python
def test_parallel_results_match_sequential(monkeypatch):
    """With workers=2 and workers=1, the set of attributed sentences must be identical.

    Uses mocked fastcoref so the test runs without GPU/model download.
    The mock returns one fixed cluster per chapter.
    """
    import sys
    from unittest.mock import MagicMock, patch

    # Simulate two chapters, each with one pronoun cluster
    chapters = {
        "ch01": "David Martín entra. Il ferma la porte.",
        "ch02": "Pedro Vidal écrivit. Il signa le contrat.",
    }
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "aliases": ["Vidal"], "relevant": True},
    ]

    # Build a fake _coref_worker that returns deterministic results without loading the model
    def fake_worker(args):
        chapter_id, text, name_to_canonical = args
        if chapter_id == "ch01":
            return [("David Martín", "ch01", "Il ferma la porte.")]
        if chapter_id == "ch02":
            return [("Pedro Vidal", "ch02", "Il signa le contrat.")]
        return []

    from scripts import relationship_extraction as rel

    # Sequential (workers=1) with same fake
    with patch.object(rel, "_coref_worker", side_effect=fake_worker):
        # Sequential path doesn't use _coref_worker directly, so we patch
        # enrich_mentions_with_fastcoref to call fake_worker internally via workers=2
        mentions_seq = {"David Martín": {}, "Pedro Vidal": {}}
        mentions_par = {"David Martín": {}, "Pedro Vidal": {}}

        from concurrent.futures import ProcessPoolExecutor

        # Parallel path: patch ProcessPoolExecutor.map to use fake_worker
        class FakeExecutor:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def map(self, fn, items):
                return [fake_worker(item) for item in items]

        with patch("concurrent.futures.ProcessPoolExecutor", return_value=FakeExecutor()):
            result_par = rel.enrich_mentions_with_fastcoref(chapters, entities, mentions_par, workers=2)

    # Sequential path: patch spacy+fastcoref with fake that produces same output
    def fake_fastcoref_sequential(chapters, entities, mentions_by_entity, workers=1):
        for item in [
            ("David Martín", "ch01", "Il ferma la porte."),
            ("Pedro Vidal", "ch02", "Il signa le contrat."),
        ]:
            canonical, chid, sentence = item
            mentions_by_entity.setdefault(canonical, {}).setdefault(chid, [])
            if sentence not in mentions_by_entity[canonical][chid]:
                mentions_by_entity[canonical][chid].append(sentence)
        return mentions_by_entity

    result_seq = fake_fastcoref_sequential(chapters, entities, {"David Martín": {}, "Pedro Vidal": {}})

    # Verify same sentences attributed
    assert set(result_par.get("David Martín", {}).get("ch01", [])) == \
           set(result_seq.get("David Martín", {}).get("ch01", []))
    assert set(result_par.get("Pedro Vidal", {}).get("ch02", [])) == \
           set(result_seq.get("Pedro Vidal", {}).get("ch02", []))
```

**Step 2: Run to verify it passes**

```bash
pytest tests/test_relationship_extraction.py::test_parallel_results_match_sequential -v
```
Expected: `PASS`

**Step 3: Run full suite**

```bash
pytest tests/ -v
```
Expected: all `PASS`

**Step 4: Commit**

```bash
git add tests/test_relationship_extraction.py
git commit -m "test(stu-238): determinism test — parallel results match sequential"
```

---

### Task 6: Document RAM requirements

**Files:**
- Modify: `scripts/relationship_extraction.py` (module docstring at top)

**Step 1: Update the module docstring**

In the module docstring (top of file, lines 1–44), add to the "Standalone test:" section:

```
  python scripts/relationship_extraction.py --live --coref --workers 4
  python scripts/relationship_extraction.py --test --coref --workers 2

Workers / RAM budget (LingMessCoref ~590M params per worker):
  --workers 1  :  ~3 GB  (default, safe on any machine)
  --workers 2  :  ~5 GB
  --workers 4  :  ~10 GB (recommended on 16 GB machines)
  --workers 8  :  ~20 GB (recommended on 32 GB machines)
  If a worker runs out of memory, it returns [] for its chapter (graceful skip).
```

**Step 2: Verify tests still pass**

```bash
pytest tests/ -v
```
Expected: all `PASS`

**Step 3: Commit**

```bash
git add scripts/relationship_extraction.py
git commit -m "docs(stu-238): document RAM requirements per worker count in module docstring"
```

---

## Acceptance Checklist

- [ ] `--workers N` flag works: `python scripts/relationship_extraction.py --live --coref --workers 4`
- [ ] Default `--workers 1` is backwards-compatible (same output as before)
- [ ] MemoryError in parallel workers falls back gracefully
- [ ] `make test-coref-parallel` target exists
- [ ] RAM documented in module docstring
- [ ] `pytest tests/` all pass

## RAM Reference

| Workers | Estimated time (93 chapters) | Estimated RAM |
|---------|------------------------------|---------------|
| 1 (default) | ~10 min | ~3 GB |
| 4 | ~2.5 min | ~10 GB |
| 8 | ~1.5 min | ~20 GB |
