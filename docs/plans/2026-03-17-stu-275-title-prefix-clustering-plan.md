# STU-275: Title-Prefix Clustering Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix "Captain Westfall" / "Chaol Westfall" being treated as distinct entities by wiring `person_cue_words` from `cue_words/{lang}.json` into both `entity_clustering.py` (dynamic `TITLE_PREFIXES`) and `alias_resolution.py` (auto-confirm title aliases without LLM).

**Architecture:** Two surgical changes share a single source of truth. `entity_clustering.py` merges `person_cue_words` into `TITLE_PREFIXES` at runtime so title-prefixed names strip correctly before subset matching. `alias_resolution.py` removes the LLM gate from `_detect_title_alias` and seeds `role_words` from `person_cue_words`.

**Tech Stack:** Python 3.12, pytest, `wiki_creator.lang.infer_language`, `wiki_creator.lang.load_lang_config`

---

### Task 1: Failing test — clustering merges "Captain Westfall" + "Chaol Westfall"

**Files:**
- Modify: `tests/test_entity_clustering.py`

**Step 1: Write the failing test**

Add to `tests/test_entity_clustering.py` (find a suitable place near other `should_cluster` tests):

```python
def test_captain_westfall_clusters_with_chaol_westfall():
    """STU-275: title-prefixed 'Captain Westfall' must cluster with 'Chaol Westfall'."""
    from scripts.entity_clustering import build_clusters

    entities = {
        "e1": {"type": "PERSON", "raw_mentions": ["Chaol Westfall"], "first_seen": "ch01"},
        "e2": {"type": "PERSON", "raw_mentions": ["Captain Westfall"], "first_seen": "ch02"},
        "e3": {"type": "PERSON", "raw_mentions": ["Westfall"], "first_seen": "ch03"},
    }
    clusters, unclustered = build_clusters(entities, language="en")
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}: {clusters}"
    assert len(unclustered) == 0
    mentions = set(clusters[0]["all_mentions"])
    assert "Captain Westfall" in mentions
    assert "Chaol Westfall" in mentions
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_entity_clustering.py::test_captain_westfall_clusters_with_chaol_westfall -v
```

Expected: `FAIL` — `build_clusters` doesn't accept a `language` parameter yet.

**Step 3: Commit the failing test**

```bash
git add tests/test_entity_clustering.py
git commit -m "test(STU-275): failing test — Captain Westfall clusters with Chaol Westfall"
```

---

### Task 2: Implement `load_title_prefixes` + `language` param in `entity_clustering.py`

**Files:**
- Modify: `scripts/entity_clustering.py`

**Context:** `wiki_creator/lang.py` exposes `load_lang_config(language)` which returns the parsed cue_words JSON dict. `person_cue_words` is the key we need. `infer_language(spacy_model)` maps model names to language codes.

**Step 1: Add `load_title_prefixes` helper after the `TITLE_PREFIXES` constant**

```python
def load_title_prefixes(language: str | None = None) -> frozenset[str]:
    """
    Return TITLE_PREFIXES extended with person_cue_words from cue_words/{lang}.json.
    Falls back to the hardcoded set if language is None or loading fails.
    """
    if not language:
        return TITLE_PREFIXES
    try:
        from wiki_creator.lang import load_lang_config
        lang_cfg = load_lang_config(language)
        extra = frozenset(w.lower() for w in lang_cfg.get("person_cue_words", []))
        return TITLE_PREFIXES | extra
    except Exception:
        return TITLE_PREFIXES
```

**Step 2: Add `language` parameter to `build_clusters`**

Change signature and pass prefixes into matching:

```python
def build_clusters(entities: dict, language: str | None = None) -> tuple[list[dict], dict]:
    """
    Cluster entities by name similarity using Union-Find.
    language: if provided, extends TITLE_PREFIXES with person_cue_words for that language.
    """
    title_prefixes = load_title_prefixes(language)
    # ... rest of function unchanged, BUT pass title_prefixes down to matching functions
```

**Step 3: Thread `title_prefixes` through matching helpers**

The matching chain is: `build_clusters` → `should_cluster` → `should_cluster_tokens` / `should_cluster_jw` → `tokenize_name`.

The cleanest approach is to pass `title_prefixes` into `tokenize_name` and `extract_leading_titles`:

```python
def tokenize_name(name: str, title_prefixes: frozenset[str] = TITLE_PREFIXES) -> list[str]:
    tokens = name.lower().strip().split()
    while tokens and tokens[0] in title_prefixes:
        tokens = tokens[1:]
    return [t for t in tokens if t]


def extract_leading_titles(name: str, title_prefixes: frozenset[str] = TITLE_PREFIXES) -> frozenset[str]:
    tokens = name.lower().strip().split()
    result = set()
    for t in tokens:
        if t in title_prefixes:
            result.add(t)
        else:
            break
    return frozenset(result)
```

And update `should_cluster_tokens`, `should_cluster_jw`, `should_cluster`, `has_conflicting_gender_title` to accept and forward `title_prefixes` with the same default.

Then in `build_clusters`, call `should_cluster(mi, mj, title_prefixes=title_prefixes)` in the inner loop.

**Step 4: Run the failing test — it should now pass**

```bash
pytest tests/test_entity_clustering.py::test_captain_westfall_clusters_with_chaol_westfall -v
```

Expected: `PASS`

**Step 5: Run the full test suite to check for regressions**

```bash
pytest tests/test_entity_clustering.py -v
```

Expected: all existing tests pass (default `title_prefixes` argument preserves existing behavior).

**Step 6: Commit**

```bash
git add scripts/entity_clustering.py
git commit -m "feat(STU-275): load title prefixes from person_cue_words at cluster time"
```

---

### Task 3: Wire language into `entity_clustering.py` `main()`

**Files:**
- Modify: `scripts/entity_clustering.py`

**Step 1: Read language from payload in `main()`**

```python
def main() -> None:
    # ... existing payload loading ...

    import yaml as _yaml
    from wiki_creator.lang import infer_language
    ctx = _yaml.safe_load(payload.get("additional_context", "") or "") or {}
    spacy_model = ctx.get("spacy_model", "")
    language = ctx.get("language") or (infer_language(spacy_model) if spacy_model else None)

    clusters, unclustered = build_clusters(entities, language=language)
    # ... rest unchanged ...
```

**Step 2: Run full test suite**

```bash
pytest -q
```

Expected: `288 passed` (or more with new tests).

**Step 3: Commit**

```bash
git add scripts/entity_clustering.py
git commit -m "feat(STU-275): wire language into entity_clustering main() for dynamic title prefixes"
```

---

### Task 4: Failing test — alias_resolution auto-confirms title alias without LLM

**Files:**
- Modify: `tests/test_alias_resolution.py`

**Step 1: Write the failing test**

Add near existing `title_alias` tests (search for `_detect_title_alias` or `title_alias` in the test file):

```python
def test_title_alias_merges_without_llm_confirmer():
    """STU-275: _detect_title_alias must auto-confirm without requiring llm_confirmer."""
    from scripts.alias_resolution import resolve_aliases

    entities = [
        {
            "canonical_name": "Chaol Westfall",
            "type": "PERSON",
            "relevant": True,
            "aliases": ["Chaol Westfall", "Westfall"],
            "source_ids": ["e1"],
        },
        {
            "canonical_name": "Captain Westfall",
            "type": "PERSON",
            "relevant": True,
            "aliases": ["Captain Westfall"],
            "source_ids": ["e2"],
        },
    ]
    result = resolve_aliases(
        entities,
        persons_full={},
        narrator=None,
        llm_confirmer=None,  # no LLM — must still merge
        role_words=["captain"],
    )
    resolved = result["entities"]
    assert len(resolved) == 1, f"Expected 1 merged entity, got {len(resolved)}: {resolved}"
    names = {e["canonical_name"] for e in resolved}
    aliases = {a for e in resolved for a in e.get("aliases", [])}
    assert "Chaol Westfall" in names | aliases
    assert "Captain Westfall" in names | aliases
    assert result["stats"]["merges_by_method"]["title_alias"] == 1
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_alias_resolution.py::test_title_alias_merges_without_llm_confirmer -v
```

Expected: `FAIL` — merge is skipped when `llm_confirmer is None`.

**Step 3: Commit the failing test**

```bash
git add tests/test_alias_resolution.py
git commit -m "test(STU-275): failing test — title alias merges without LLM confirmer"
```

---

### Task 5: Remove LLM gate from `_detect_title_alias` branch in `alias_resolution.py`

**Files:**
- Modify: `scripts/alias_resolution.py`

**Step 1: Find the title_alias branch in `resolve_aliases()`**

It's around line 501:

```python
title = _detect_title_alias(entity, candidate, role_words)
if title:
    if llm_confirmer is None:
        stats["ambiguous_pairs"] += 1
        continue
    # ... llm call ...
```

**Step 2: Replace with auto-confirm**

```python
title = _detect_title_alias(entity, candidate, role_words)
if title:
    merged = _merge_entities(entity, candidate, title, persons_full)
    stats["merges_applied"] += 1
    stats["merges_by_method"]["title_alias"] += 1
    consumed.add(candidate_index)
    break
```

The `title` dict already has `method: "title_alias"` and `confidence: "medium"` — sufficient for audit trails.

**Step 3: Run the new test — should now pass**

```bash
pytest tests/test_alias_resolution.py::test_title_alias_merges_without_llm_confirmer -v
```

Expected: `PASS`

**Step 4: Run the full alias_resolution test suite**

```bash
pytest tests/test_alias_resolution.py -v
```

Expected: all pass.

**Step 5: Commit**

```bash
git add scripts/alias_resolution.py
git commit -m "feat(STU-275): auto-confirm title aliases without LLM gate"
```

---

### Task 6: Seed `role_words` from `person_cue_words` in `alias_resolution.py` `main()`

**Files:**
- Modify: `scripts/alias_resolution.py`

**Step 1: Merge `person_cue_words` into `role_words` in `main()`**

Find the line that reads `role_words` from ctx (around line 586):

```python
role_words: list[str] = list(ctx.get("role_words", []))
```

Replace with:

```python
role_words: list[str] = list(ctx.get("role_words", []))
lang_cfg = load_lang_config(language)
cue_role_words = [w.lower() for w in lang_cfg.get("person_cue_words", [])]
role_words = list(dict.fromkeys(role_words + cue_role_words))  # dedup, preserve order
```

(`load_lang_config` is already imported at the top of the file.)

**Step 2: Run full test suite**

```bash
pytest -q
```

Expected: all pass.

**Step 3: Commit**

```bash
git add scripts/alias_resolution.py
git commit -m "feat(STU-275): seed role_words from person_cue_words in alias_resolution"
```

---

### Task 7: Final validation

**Step 1: Run the complete test suite**

```bash
pytest -q
```

Expected: all tests pass (≥ 288 + new tests).

**Step 2: Quick smoke test with live data (optional, requires extraction output)**

```bash
python scripts/entity_clustering.py --live --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml 2>/dev/null | grep -i westfall
```

Expected: "Chaol Westfall" and "Captain Westfall" appear in the same cluster.

**Step 3: Final commit if any cleanup needed, then push**

```bash
git push -u origin arianedguay/stu-275-fix-ner-clustering-fusionner-captain-westfall-et-chaol
```
