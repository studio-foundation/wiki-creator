# STU-248 — Filter false entities Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate verbs, adjectives, and exclamative forms erroneously captured as named entities from the co-occurrence graph.

**Architecture:** Two independent filters: (1) a POS-based span validator added to `entity_extraction.py` that rejects spans whose head token is VERB/AUX/ADJ/ADV, preventing false positives from entering `persons_full.json`; (2) configurable co-occurrence thresholds (`min_cooccurrence`, `min_chapters_together`) added to `relationship_extraction.py` as a second line of defence for any false positives that survive extraction.

**Tech Stack:** Python 3.11+, spaCy (`fr_core_news_lg` / `en_core_web_sm`), pytest, existing `--test` / `--live` CLI flags.

---

### Task 1: POS filter in `entity_extraction.py`

**Files:**
- Modify: `scripts/entity_extraction.py`
- Test: `tests/test_entity_extraction.py` (create if absent)

**Step 1: Write the failing test**

```python
# tests/test_entity_extraction.py
import spacy
from scripts.entity_extraction import extract_entities

def test_pos_filter_rejects_verb_at_sentence_start():
    """Capitalized French verb at dialogue start must not appear as entity."""
    nlp = spacy.load("fr_core_news_lg")
    chapters = [
        {
            "id": "ch01",
            "content": (
                "Pedro Vidal tendit le manuscrit à Martín. "
                "— Regarde, il est là. "
                "— Avez-vous lu ce chapitre ? "
                "— Sériez-vous d'accord ?"
            ),
        }
    ]
    result = extract_entities(chapters, nlp)
    raw_mentions = [
        m
        for e in result["entities"].values()
        for m in e["raw_mentions"]
    ]
    assert "Regarde" not in raw_mentions
    assert "Avez" not in raw_mentions
    assert "Sériez" not in raw_mentions
    # True entities must survive
    assert any("Vidal" in m or "Martín" in m for m in raw_mentions)
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_entity_extraction.py::test_pos_filter_rejects_verb_at_sentence_start -v
```
Expected: FAIL — `Regarde` / `Avez` / `Sériez` are present in raw_mentions.

**Step 3: Add `_BAD_POS` constant and `_is_valid_span()` to `entity_extraction.py`**

Add after the existing `FALSE_POSITIVE_WORDS` block (around line 72):

```python
# POS tags that disqualify a span from being a named entity.
# Capitalized verb/adjective/adverb at sentence start is a common false positive
# in French dialogue (e.g. "— Regarde", "— Avez-vous", "— Sériez-vous").
_BAD_POS: frozenset[str] = frozenset({"VERB", "AUX", "ADJ", "ADV"})


def _is_valid_span(span) -> bool:
    """
    Return True if the spaCy span looks like a proper-noun entity.

    For mono-token spans: reject if the token's POS is a verb, aux, adjective, or adverb.
    For multi-token spans: use the syntactic head (span.root); reject if its POS is bad
    AND it is not tagged as PROPN or NOUN (multi-word proper nouns may have various heads).
    """
    tokens = list(span)
    if len(tokens) == 1:
        return tokens[0].pos_ not in _BAD_POS
    head = span.root
    if head.pos_ in _BAD_POS and head.pos_ not in {"PROPN", "NOUN"}:
        return False
    return True
```

**Step 4: Call `_is_valid_span` in `extract_entities`**

In `extract_entities`, find the block that calls `_is_valid_mention` (around line 205) and add the span check immediately after:

```python
            mention_text = _truncate_mention(ent)
            key = mention_text.lower().strip()
            if not key:
                continue
            if not _is_valid_mention(mention_text):
                continue
            if not _is_valid_span(ent):          # ← new line
                continue
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_entity_extraction.py::test_pos_filter_rejects_verb_at_sentence_start -v
```
Expected: PASS.

**Step 6: Run the existing test mode to confirm no regression**

```bash
python scripts/entity_extraction.py --test
```
Expected: prints entity count and 3-entity sample without errors.

**Step 7: Commit**

```bash
git add scripts/entity_extraction.py tests/test_entity_extraction.py
git commit -m "feat(stu-248): add POS filter in entity_extraction to reject verbs/adjectives"
```

---

### Task 2: Co-occurrence thresholds in `relationship_extraction.py`

**Files:**
- Modify: `scripts/relationship_extraction.py`
- Test: `tests/test_relationship_extraction.py` (create if absent)

**Step 1: Write the failing test**

```python
# tests/test_relationship_extraction.py
from scripts.relationship_extraction import build_cooccurrence_graph

def _base_entities():
    return [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
        {"canonical_name": "Pedro Vidal",  "type": "PERSON", "aliases": ["Vidal"],  "relevant": True},
        {"canonical_name": "Regarde",      "type": "PERSON", "aliases": [],          "relevant": True},
    ]

def _base_mentions():
    return {
        "David Martín": {
            "ch01": ["Vidal tendit le manuscrit à Martín.", "Martín retrouva Vidal."],
            "ch02": ["Martín reçut une lettre.", "Vidal encouragea Martín."],
        },
        "Pedro Vidal": {
            "ch01": ["Vidal tendit le manuscrit à Martín.", "Martín retrouva Vidal."],
            "ch02": ["Vidal encouragea Martín."],
        },
        "Regarde": {
            "ch01": ["— Regarde, il est là."],
        },
    }


def test_false_entity_filtered_by_min_chapters():
    """'Regarde' only appears in 1 chapter — must be filtered with min_chapters_together=2."""
    rels, stats = build_cooccurrence_graph(
        _base_entities(),
        _base_mentions(),
        window_size=5,
        min_cooccurrence=2,
        min_chapters_together=2,
    )
    entity_names = {r["entity_a"] for r in rels} | {r["entity_b"] for r in rels}
    assert "Regarde" not in entity_names


def test_true_relation_survives_filter():
    """Martín ↔ Vidal appears in 2 chapters — must survive the filter."""
    rels, stats = build_cooccurrence_graph(
        _base_entities(),
        _base_mentions(),
        window_size=5,
        min_cooccurrence=2,
        min_chapters_together=2,
    )
    pairs = {(r["entity_a"], r["entity_b"]) for r in rels}
    assert ("David Martín", "Pedro Vidal") in pairs or ("Pedro Vidal", "David Martín") in pairs


def test_stats_include_new_fields():
    """Stats dict must expose min_cooccurrence and min_chapters_together."""
    _, stats = build_cooccurrence_graph(
        _base_entities(),
        _base_mentions(),
        window_size=5,
        min_cooccurrence=3,
        min_chapters_together=2,
    )
    assert stats["min_cooccurrence"] == 3
    assert stats["min_chapters_together"] == 2
```

**Step 2: Run tests to verify they fail**

```bash
pytest tests/test_relationship_extraction.py -v
```
Expected: FAIL — `build_cooccurrence_graph` doesn't accept `min_cooccurrence` / `min_chapters_together` yet.

**Step 3: Update `build_cooccurrence_graph` signature**

Replace the current signature (around line 65):

```python
def build_cooccurrence_graph(
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    window_size: int = DEFAULT_WINDOW,
    threshold: int = DEFAULT_THRESHOLD,
) -> tuple[list[dict], dict]:
```

With:

```python
DEFAULT_MIN_COOCCURRENCE = 3
DEFAULT_MIN_CHAPTERS_TOGETHER = 2

def build_cooccurrence_graph(
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    window_size: int = DEFAULT_WINDOW,
    threshold: int = DEFAULT_THRESHOLD,          # kept as alias for min_cooccurrence
    min_cooccurrence: int | None = None,
    min_chapters_together: int = DEFAULT_MIN_CHAPTERS_TOGETHER,
) -> tuple[list[dict], dict]:
    """
    Build weighted co-occurrence graph between PERSON entities.

    Args:
        entities: resolved entities with canonical_name, aliases, relevant, type
        mentions_by_entity: {canonical_name: {chapter_id: [sentence, ...]}}
        window_size: sliding window of N sentences
        threshold: alias for min_cooccurrence (legacy; overridden by min_cooccurrence)
        min_cooccurrence: minimum co-occurrence count to include (default 3)
        min_chapters_together: minimum distinct chapters for a pair to be included (default 2)

    Returns:
        (relationships list, stats dict)
    """
    effective_min_cooc = min_cooccurrence if min_cooccurrence is not None else threshold
```

**Step 4: Replace the output filter loop**

Find the section "Build output: filter by threshold" (around line 150) and replace:

```python
    # Build output: filter by min_cooccurrence and min_chapters_together, sort by count desc
    relationships = []
    for (a, b), data in cooc.items():
        if data["count"] >= effective_min_cooc and len(data["chapters"]) >= min_chapters_together:
            relationships.append({
                "entity_a": a,
                "entity_b": b,
                "cooccurrence_count": data["count"],
                "chapters": sorted(data["chapters"]),
                "sample_contexts": data["contexts"],
                "relationship_type": None,
                "direction": None,
                "evolution": None,
                "key_moments": [],
            })
```

**Step 5: Update stats dict**

Replace the stats block (around line 168):

```python
    pairs_above = len(relationships)
    stats = {
        "total_pairs_checked": total_pairs_checked,
        "pairs_above_threshold": pairs_above,
        "classified": 0,
        "window_size": window_size,
        "threshold": effective_min_cooc,       # legacy field, keep for compat
        "min_cooccurrence": effective_min_cooc,
        "min_chapters_together": min_chapters_together,
    }
```

**Step 6: Thread new params through callers**

In `main()`, update the YAML parsing block (around line 1057):

```python
        do_classify = bool(additional.get("classify", False))
        do_coref = bool(additional.get("coref", False))
        window_size = int(additional.get("window", window_size))
        threshold = int(additional.get("threshold", threshold))
        min_cooccurrence = additional.get("min_cooccurrence")
        if min_cooccurrence is not None:
            min_cooccurrence = int(min_cooccurrence)
        min_chapters_together = int(additional.get("min_chapters_together", DEFAULT_MIN_CHAPTERS_TOGETHER))
        workers = int(additional.get("workers", workers))
```

And pass them to `build_cooccurrence_graph` in `main()`:

```python
    relationships, stats = build_cooccurrence_graph(
        entities, mentions_by_entity, window_size, threshold,
        min_cooccurrence=min_cooccurrence,
        min_chapters_together=min_chapters_together,
    )
```

Do the same in `run_test_mode` and `run_live_mode` — add `min_cooccurrence` and `min_chapters_together` params and thread them through. For the `--test` / `--live` CLI flags, parse from `sys.argv`:

```python
    # in main(), alongside existing --window / --threshold parsing:
    min_cooccurrence = None
    if "--min-cooccurrence" in args:
        idx = args.index("--min-cooccurrence")
        min_cooccurrence = int(args[idx + 1])

    min_chapters_together = DEFAULT_MIN_CHAPTERS_TOGETHER
    if "--min-chapters" in args:
        idx = args.index("--min-chapters")
        min_chapters_together = int(args[idx + 1])
```

**Step 7: Run tests to verify they pass**

```bash
pytest tests/test_relationship_extraction.py -v
```
Expected: all 3 tests PASS.

**Step 8: Smoke test with existing `--test` mode**

```bash
python scripts/relationship_extraction.py --test
```
Expected: stats include `min_cooccurrence: 3`, `min_chapters_together: 2`. All expected pairs present. No obvious verbs in entity names.

**Step 9: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(stu-248): add min_cooccurrence and min_chapters_together filters to relationship_extraction"
```

---

### Task 3: Verify acceptance criteria end-to-end

**Step 1: Run full test suite**

```bash
pytest -v
```
Expected: all tests pass.

**Step 2: Run live validation (if `persons_full.json` available)**

```bash
python scripts/relationship_extraction.py --live
```
Check output: `Sériez`, `Auriez`, `Avez`, `Regarde`, `Félicitations` must not appear as `entity_a` or `entity_b`.

If `persons_full.json` is stale (pre-fix), regenerate first:
```bash
make test-extraction
```
Then re-run `--live`.

**Step 3: Final commit**

```bash
git add .
git commit -m "test(stu-248): verify acceptance criteria — no verbs in co-occurrence graph"
```
