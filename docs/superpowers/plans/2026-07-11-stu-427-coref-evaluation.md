# STU-427 Coref Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the coref chapter cap configurable, build a committed 3-variant evaluation harness (`scripts/eval_coref.py`), run it on Throne of Glass, and produce the evidence for the enable-by-default decision.

**Architecture:** A small parameter change threads `max_chars` through the existing fastcoref path in `scripts/relationship_extraction.py`. A new standalone harness imports that module's functions directly (no pipeline files are written), spawns itself per variant under `/usr/bin/time -v` for isolated time/RSS measurement, and emits a metrics report plus a manual-review sample.

**Tech Stack:** Python 3, pytest, fastcoref/LingMessCoref (optional extra), GNU time.

**Spec:** `docs/superpowers/specs/2026-07-11-stu-427-coref-evaluation-design.md`

## Global Constraints

- Work in worktree `.claude/worktrees/stu-427`, branch `arianedguay/stu-427-activerevaluer-la-resolution-de-coreference-par-defaut`.
- All commands run from the worktree root (imports use the `scripts.` package form and need repo-root cwd).
- Default behavior of `relationship_extraction.py` must not change: cap default stays `8000`.
- Tests must stay hermetic: anything needing fastcoref or a spaCy model uses the markers in `tests/_markers.py` (`requires_fastcoref`, etc.); new unit tests must not download models.
- `pytest -q` baseline: 735 passed, 31 skipped. Must not regress.
- No `coref:` default is flipped in any book YAML in this plan (post-review checkpoint).
- No hardcoded vocabulary lists (repo invariant); not expected to arise here.
- Commit messages end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: `max_chars` parameter in the fastcoref path

**Files:**
- Modify: `scripts/relationship_extraction.py:567-616` (`_coref_worker`), `:619-752` (`enrich_mentions_with_fastcoref`)
- Test: `tests/test_relationship_extraction.py`

**Interfaces:**
- Produces: `enrich_mentions_with_fastcoref(chapters, entities, mentions_by_entity, workers=1, spacy_model="fr_core_news_lg", max_chars=8000)` — `max_chars=0` means no cap. `_coref_worker` now unpacks a **5-tuple** `(chapter_id, text, name_to_canonical, spacy_model, max_chars)`.

- [ ] **Step 1: Update the two existing worker-tuple tests to the 5-tuple and add signature tests (failing first)**

In `tests/test_relationship_extraction.py`, change `test_coref_worker_returns_list` (line ~164) and `test_coref_worker_accepts_4_tuple` (line ~333):

```python
def test_coref_worker_returns_list():
    """_coref_worker returns a list (empty when fastcoref not available)."""
    from scripts.relationship_extraction import _coref_worker
    result = _coref_worker(("ch01", "Il travaillait.", {"david martín": "David Martín"}, "fr_core_news_lg", 8000))
    assert isinstance(result, list)
    for item in result:
        assert len(item) == 3
        assert isinstance(item[0], str)
        assert isinstance(item[1], str)
        assert isinstance(item[2], str)
```

```python
def test_coref_worker_accepts_5_tuple():
    """_coref_worker must unpack (chapter_id, text, name_to_canonical, spacy_model, max_chars)."""
    from scripts.relationship_extraction import _coref_worker
    result = _coref_worker(("ch01", "", {}, "en_core_web_sm", 8000))
    assert result == []
```

(The old `test_coref_worker_accepts_4_tuple` is renamed/replaced by this.)

Add next to `test_enrich_fastcoref_accepts_workers_param` (line ~177):

```python
def test_enrich_fastcoref_accepts_max_chars_param():
    """enrich_mentions_with_fastcoref accepts max_chars with default 8000."""
    import inspect
    from scripts.relationship_extraction import enrich_mentions_with_fastcoref
    sig = inspect.signature(enrich_mentions_with_fastcoref)
    assert "max_chars" in sig.parameters
    assert sig.parameters["max_chars"].default == 8000
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_relationship_extraction.py -k "coref_worker or max_chars" -v`
Expected: `test_coref_worker_returns_list` and `test_coref_worker_accepts_5_tuple` FAIL (ValueError: not enough values to unpack — the worker unpacks 4), `test_enrich_fastcoref_accepts_max_chars_param` FAILS (no `max_chars` param).

- [ ] **Step 3: Implement `max_chars` in `_coref_worker`**

At `scripts/relationship_extraction.py:582-586`, replace:

```python
    chapter_id, text, name_to_canonical, spacy_model = args
    if not text or not text.strip():
        return []

    chunk = text[:8000]
```

with:

```python
    chapter_id, text, name_to_canonical, spacy_model, max_chars = args
    if not text or not text.strip():
        return []

    chunk = text[:max_chars] if max_chars > 0 else text
```

Update the docstring `Args:` line (`:574`) to `args: (chapter_id, text, name_to_canonical, spacy_model, max_chars)` and add `max_chars: character cap per chapter (0 = no cap)`.

- [ ] **Step 4: Implement `max_chars` in `enrich_mentions_with_fastcoref`**

Signature (`:619-625`) becomes:

```python
def enrich_mentions_with_fastcoref(
    chapters: dict[str, str],
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    workers: int = 1,
    spacy_model: str = "fr_core_news_lg",
    max_chars: int = 8000,
) -> dict[str, dict[str, list[str]]]:
```

Docstring: change the "first 8 000 chars" sentence (`:628`) to "For each chapter (first `max_chars` characters; 0 = full chapter), run LingMessCoref…" and add an Args line: `max_chars: character cap per chapter (default 8000, 0 = no cap).`

Sequential path (`:694`): replace `chunk = text[:8000]` with `chunk = text[:max_chars] if max_chars > 0 else text`.

Parallel path (`:717-721`): the items become 5-tuples:

```python
        chapter_items = [
            (cid, text, name_to_canonical, spacy_model, max_chars)
            for cid, text in chapters.items()
            if text and text.strip()
        ]
```

Fallback recursion (`:737`): add the kwarg:

```python
            return enrich_mentions_with_fastcoref(chapters, entities, mentions_by_entity, workers=1, spacy_model=spacy_model, max_chars=max_chars)
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_relationship_extraction.py -v`
Expected: all pass (some skipped per markers).

- [ ] **Step 6: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(coref): configurable per-chapter character cap (max_chars) (STU-427)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Wire `coref_max_chars` through executor path and CLI

**Files:**
- Modify: `scripts/relationship_extraction.py` — `run_test_mode` (`:755`), `run_live_mode` (`:1114`), executor parsing (`:1386-1436`), `main()` (`:1312-1368`)
- Test: `tests/test_relationship_extraction.py`

**Interfaces:**
- Consumes: `enrich_mentions_with_fastcoref(..., max_chars=...)` from Task 1.
- Produces: book YAML / `additional_context` key `coref_max_chars` (int, default 8000, 0 = no cap); CLI flag `--coref-max-chars N`; `run_test_mode(..., coref_max_chars=8000)` and `run_live_mode(..., coref_max_chars=8000)` keyword params.

- [ ] **Step 1: Write failing tests**

In `tests/test_relationship_extraction.py`, update the fake in `test_main_parses_workers_flag` (line ~193) so its signature stays compatible:

```python
    def fake_run_live(window_size, threshold, coref=False, workers=1, min_cooccurrence=None, min_chapters_together=2, coref_max_chars=8000):
        captured["workers"] = workers
```

Add:

```python
def test_main_parses_coref_max_chars_flag(monkeypatch):
    """--coref-max-chars N is parsed and passed through to run_live_mode."""
    import sys
    import scripts.relationship_extraction as rel

    captured = {}

    def fake_run_live(window_size, threshold, coref=False, workers=1, min_cooccurrence=None, min_chapters_together=2, coref_max_chars=8000):
        captured["coref_max_chars"] = coref_max_chars

    monkeypatch.setattr(rel, "run_live_mode", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["rel.py", "--live", "--coref", "--coref-max-chars", "0"])
    rel.main()

    assert captured["coref_max_chars"] == 0


def test_executor_parses_coref_max_chars(monkeypatch, tmp_path, capsys):
    """coref_max_chars in additional_context reaches enrich_mentions_with_fastcoref."""
    import io
    import json
    import sys
    from types import SimpleNamespace
    import scripts.relationship_extraction as rel

    (tmp_path / "chapters.json").write_text(json.dumps({"chapters": {"ch01": "Celaena walked. She smiled."}}), encoding="utf-8")

    captured = {}

    def fake_enrich(chapters, entities, mentions_by_entity, workers=1, spacy_model="fr_core_news_lg", max_chars=8000):
        captured["max_chars"] = max_chars
        return mentions_by_entity

    monkeypatch.setattr(rel, "enrich_mentions_with_fastcoref", fake_enrich)
    monkeypatch.setattr(rel, "_paths_from_payload", lambda payload: SimpleNamespace(processing=tmp_path))

    payload = {
        "previous_outputs": {
            "entity-resolution": {
                "entities": [{"canonical_name": "Celaena", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}],
            },
        },
        "additional_context": "coref: true\ncoref_max_chars: 4321\n",
    }
    monkeypatch.setattr(sys, "argv", ["rel.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rel.main()

    assert captured["max_chars"] == 4321
    out = capsys.readouterr().out
    assert json.loads(out)  # executor still emits valid JSON
```

- [ ] **Step 2: Run to verify failures**

Run: `pytest tests/test_relationship_extraction.py -k "coref_max_chars" -v`
Expected: both new tests FAIL (`--coref-max-chars`/`coref_max_chars` not wired; enrich called without `max_chars=4321`).

- [ ] **Step 3: Implement the wiring**

a) `run_test_mode` signature (`:755-762`): add `coref_max_chars: int = 8000,` after `min_chapters_together`. Its enrich call (`:856`) becomes:

```python
        mentions_by_entity = enrich_mentions_with_fastcoref(chapters_demo, entities, mentions_by_entity, workers=workers, max_chars=coref_max_chars)
```

b) `run_live_mode` signature (`:1114-1122`): add `coref_max_chars: int = 8000,` after `min_chapters_together`. Its enrich call (`:1246`) becomes:

```python
            mentions_by_entity = enrich_mentions_with_fastcoref(chapters, entities, mentions_by_entity, workers=workers, max_chars=coref_max_chars)
```

c) `main()` — after the `--workers` parsing block (`:1328-1331`), add:

```python
    coref_max_chars = 8000
    if "--coref-max-chars" in args:
        idx = args.index("--coref-max-chars")
        coref_max_chars = int(args[idx + 1])
```

Pass `coref_max_chars=coref_max_chars` to both `run_test_mode(...)` calls (`:1344`) and both `run_live_mode(...)` calls (`:1358`, `:1364`).

d) Executor path — with the other defaults before the `if raw_context:` block (`:1388-1396`), add `coref_max_chars = 8000`. Inside the `try:` (next to `do_coref`, `:1404`), add:

```python
            coref_max_chars = int(additional.get("coref_max_chars", 8000))
```

The executor enrich call (`:1434-1436`) becomes:

```python
            mentions_by_entity = enrich_mentions_with_fastcoref(
                chapters, entities, mentions_by_entity, workers=workers, spacy_model=spacy_model, max_chars=coref_max_chars
            )
```

Also update the CLI usage examples in the module docstring (`:42-45`) to include one `--coref-max-chars 0` example.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_relationship_extraction.py -v` then `pytest -q`
Expected: all pass, no regression vs the 735/31 baseline.

- [ ] **Step 5: Commit**

```bash
git add scripts/relationship_extraction.py tests/test_relationship_extraction.py
git commit -m "feat(coref): wire coref_max_chars through executor, CLI and run modes (STU-427)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Eval harness pure core (`scripts/eval_coref.py` — metrics, sampling, rendering)

**Files:**
- Create: `scripts/eval_coref.py`
- Create: `tests/test_eval_coref.py`

**Interfaces:**
- Produces (all pure, no I/O — Task 4 builds on these exact signatures):
  - `count_sentences(mentions: dict) -> int`
  - `compute_mention_deltas(baseline: dict, variant: dict) -> dict` → `{"total_added": int, "per_entity": [(name, added), ...] desc}`
  - `relationship_key(rel: dict) -> tuple[str, str]`
  - `compute_relationship_deltas(baseline: list[dict], variant: list[dict]) -> dict` → `{"added": [rel], "removed": [rel], "reweighted": [{"pair", "before", "after"}]}`
  - `new_sentences(baseline: dict, variant: dict) -> list[dict]` → `[{"entity", "chapter_id", "sentence"}]`
  - `sample_new_sentences(baseline: dict, variant: dict, n: int = 30, seed: int = 42) -> list[dict]`
  - `extract_context(chapter_text: str, sentence: str, radius: int = 200) -> str`
  - `parse_time_v(text: str) -> dict` → `{"peak_rss_kb": int | None}`
  - `render_report(book: str, results: dict) -> str` and `render_sample(samples: dict, chapters: dict) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_coref.py`:

```python
"""Unit tests for the coref evaluation harness (STU-427). Pure functions only."""
import scripts.eval_coref as ec

BASELINE_MENTIONS = {
    "Celaena": {"ch01": ["Celaena walked."], "ch02": ["Celaena fought."]},
    "Dorian": {"ch01": ["Dorian watched."]},
}
VARIANT_MENTIONS = {
    "Celaena": {"ch01": ["Celaena walked.", "She smiled."], "ch02": ["Celaena fought."]},
    "Dorian": {"ch01": ["Dorian watched.", "He laughed.", "He left."]},
    "Chaol": {"ch03": ["He trained."]},
}


def test_count_sentences():
    assert ec.count_sentences(BASELINE_MENTIONS) == 3
    assert ec.count_sentences(VARIANT_MENTIONS) == 7


def test_compute_mention_deltas():
    deltas = ec.compute_mention_deltas(BASELINE_MENTIONS, VARIANT_MENTIONS)
    assert deltas["total_added"] == 4
    assert deltas["per_entity"][0] == ("Dorian", 2)  # sorted desc by added
    assert ("Chaol", 1) in deltas["per_entity"]


def test_relationship_key_is_order_insensitive():
    a = {"entity_a": "Celaena", "entity_b": "Dorian"}
    b = {"entity_a": "Dorian", "entity_b": "Celaena"}
    assert ec.relationship_key(a) == ec.relationship_key(b)


def test_compute_relationship_deltas():
    base = [
        {"entity_a": "Celaena", "entity_b": "Dorian", "cooccurrence_count": 5},
        {"entity_a": "Celaena", "entity_b": "Nehemia", "cooccurrence_count": 3},
    ]
    var = [
        {"entity_a": "Dorian", "entity_b": "Celaena", "cooccurrence_count": 9},
        {"entity_a": "Celaena", "entity_b": "Chaol", "cooccurrence_count": 4},
    ]
    d = ec.compute_relationship_deltas(base, var)
    assert [ec.relationship_key(r) for r in d["added"]] == [("Celaena", "Chaol")]
    assert [ec.relationship_key(r) for r in d["removed"]] == [("Celaena", "Nehemia")]
    assert d["reweighted"] == [{"pair": ("Celaena", "Dorian"), "before": 5, "after": 9}]


def test_new_sentences_only_additions():
    added = ec.new_sentences(BASELINE_MENTIONS, VARIANT_MENTIONS)
    sentences = {a["sentence"] for a in added}
    assert sentences == {"She smiled.", "He laughed.", "He left.", "He trained."}
    for a in added:
        assert set(a) == {"entity", "chapter_id", "sentence"}


def test_sample_new_sentences_seeded_and_capped():
    s1 = ec.sample_new_sentences(BASELINE_MENTIONS, VARIANT_MENTIONS, n=2, seed=42)
    s2 = ec.sample_new_sentences(BASELINE_MENTIONS, VARIANT_MENTIONS, n=2, seed=42)
    assert s1 == s2
    assert len(s1) == 2
    everything = ec.sample_new_sentences(BASELINE_MENTIONS, VARIANT_MENTIONS, n=99, seed=1)
    assert len(everything) == 4


def test_extract_context_windows_around_sentence():
    text = "A" * 300 + " He laughed. " + "B" * 300
    ctx = ec.extract_context(text, "He laughed.", radius=50)
    assert "He laughed." in ctx
    assert len(ctx) <= 50 * 2 + len("He laughed.") + 2  # ellipsis margin


def test_extract_context_falls_back_when_absent():
    assert ec.extract_context("some chapter", "Missing sentence.") == "Missing sentence."


def test_parse_time_v():
    stderr = (
        "\tCommand being timed: \"python x\"\n"
        "\tMaximum resident set size (kbytes): 3145728\n"
        "\tExit status: 0\n"
    )
    assert ec.parse_time_v(stderr) == {"peak_rss_kb": 3145728}
    assert ec.parse_time_v("no match") == {"peak_rss_kb": None}


def test_render_report_contains_tables():
    results = {
        "coref-8k": {
            "wall_seconds": 62.1,
            "peak_rss_kb": 3145728,
            "pronoun_sentences_added": 4,
            "mention_deltas": {"total_added": 4, "per_entity": [("Dorian", 2), ("Celaena", 1), ("Chaol", 1)]},
            "relationship_deltas": {"added": [{"entity_a": "Celaena", "entity_b": "Chaol", "cooccurrence_count": 4}], "removed": [], "reweighted": []},
        },
    }
    report = ec.render_report("01-throne-of-glass", results)
    assert "coref-8k" in report
    assert "Dorian" in report
    assert "3.0 GB" in report


def test_render_sample_has_checkbox_column():
    samples = {"coref-8k": [{"entity": "Dorian", "chapter_id": "ch01", "sentence": "He laughed."}]}
    chapters = {"ch01": "Dorian watched. He laughed. He left."}
    md = ec.render_sample(samples, chapters)
    assert "He laughed." in md
    assert "✓/✗" in md
    assert "Dorian" in md
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_eval_coref.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.eval_coref'`.

- [ ] **Step 3: Implement the pure core**

Create `scripts/eval_coref.py`:

```python
#!/usr/bin/env python3
"""Coref evaluation harness (STU-427).

Runs relationship extraction in three variants on one book and reports the
impact of fastcoref coreference resolution:

    baseline    coref off
    coref-8k    coref on, current 8000-char per-chapter cap
    coref-full  coref on, no cap (max_chars=0)

Each variant runs in its own subprocess (under /usr/bin/time -v when
available) for isolated wall-time and peak-RSS measurement. The harness is
read-only with respect to pipeline state: it imports functions from
scripts.relationship_extraction and writes only under
<processing>/coref_eval/.

Usage (from repo root):
    python scripts/eval_coref.py --book library/.../01-throne-of-glass.yaml --workers 4
    python scripts/eval_coref.py --book <book.yaml> --sample 30 --seed 42

Outputs, under <processing_output>/<slug>/coref_eval/:
    <variant>/mentions.json, relationships.json, stats.json
    report.md                metrics tables per variant
    sample_for_review.md     random sample of new attributions for manual ✓/✗
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

VARIANTS = ("baseline", "coref-8k", "coref-full")
VARIANT_MAX_CHARS = {"coref-8k": 8000, "coref-full": 0}


# ---------------------------------------------------------------- pure core

def count_sentences(mentions: dict) -> int:
    """Total number of mention sentences across all entities and chapters."""
    return sum(len(sents) for by_ch in mentions.values() for sents in by_ch.values())


def compute_mention_deltas(baseline: dict, variant: dict) -> dict:
    """Per-entity count of sentences present in variant but not in baseline."""
    per_entity: list[tuple[str, int]] = []
    total = 0
    for entity, by_ch in variant.items():
        base_by_ch = baseline.get(entity, {})
        added = 0
        for chapter_id, sentences in by_ch.items():
            base_set = set(base_by_ch.get(chapter_id, []))
            added += sum(1 for s in sentences if s not in base_set)
        if added:
            per_entity.append((entity, added))
            total += added
    per_entity.sort(key=lambda t: (-t[1], t[0]))
    return {"total_added": total, "per_entity": per_entity}


def relationship_key(rel: dict) -> tuple[str, str]:
    """Order-insensitive identity of an edge."""
    return tuple(sorted((rel["entity_a"], rel["entity_b"])))  # type: ignore[return-value]


def compute_relationship_deltas(baseline: list[dict], variant: list[dict]) -> dict:
    """Edges added / removed / re-weighted in variant relative to baseline."""
    base_by_key = {relationship_key(r): r for r in baseline}
    var_by_key = {relationship_key(r): r for r in variant}
    added = [var_by_key[k] for k in sorted(var_by_key.keys() - base_by_key.keys())]
    removed = [base_by_key[k] for k in sorted(base_by_key.keys() - var_by_key.keys())]
    reweighted = []
    for k in sorted(base_by_key.keys() & var_by_key.keys()):
        before = base_by_key[k].get("cooccurrence_count", 0)
        after = var_by_key[k].get("cooccurrence_count", 0)
        if before != after:
            reweighted.append({"pair": k, "before": before, "after": after})
    return {"added": added, "removed": removed, "reweighted": reweighted}


def new_sentences(baseline: dict, variant: dict) -> list[dict]:
    """All (entity, chapter_id, sentence) attributions present only in variant."""
    out: list[dict] = []
    for entity in sorted(variant):
        base_by_ch = baseline.get(entity, {})
        for chapter_id in sorted(variant[entity]):
            base_set = set(base_by_ch.get(chapter_id, []))
            for sentence in variant[entity][chapter_id]:
                if sentence not in base_set:
                    out.append({"entity": entity, "chapter_id": chapter_id, "sentence": sentence})
    return out


def sample_new_sentences(baseline: dict, variant: dict, n: int = 30, seed: int = 42) -> list[dict]:
    """Reproducible random sample of the new attributions."""
    pool = new_sentences(baseline, variant)
    if len(pool) <= n:
        return pool
    return random.Random(seed).sample(pool, n)


def extract_context(chapter_text: str, sentence: str, radius: int = 200) -> str:
    """±radius characters around the sentence; the sentence alone if not found."""
    idx = chapter_text.find(sentence)
    if idx < 0:
        return sentence
    start = max(0, idx - radius)
    end = min(len(chapter_text), idx + len(sentence) + radius)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(chapter_text) else ""
    return f"{prefix}{chapter_text[start:end]}{suffix}"


def parse_time_v(text: str) -> dict:
    """Extract peak RSS from GNU `time -v` stderr output."""
    m = re.search(r"Maximum resident set size \(kbytes\): (\d+)", text)
    return {"peak_rss_kb": int(m.group(1)) if m else None}


def _fmt_rss(kb: int | None) -> str:
    return f"{kb / 1024 / 1024:.1f} GB" if kb else "n/a"


def render_report(book: str, results: dict) -> str:
    """Markdown metrics report; `results` maps variant -> metrics dict."""
    lines = [f"# Coref evaluation — {book}", ""]
    lines += ["| Variant | Wall time (s) | Peak RSS | Pronoun sentences added |",
              "|---|---|---|---|"]
    for variant, r in results.items():
        lines.append(
            f"| {variant} | {r.get('wall_seconds', 0):.1f} | {_fmt_rss(r.get('peak_rss_kb'))} "
            f"| {r.get('pronoun_sentences_added', 0)} |"
        )
    for variant, r in results.items():
        md = r.get("mention_deltas")
        rd = r.get("relationship_deltas")
        if md is None or rd is None:
            continue
        lines += ["", f"## {variant} vs baseline", "",
                  f"Mention sentences added: **{md['total_added']}**", "",
                  "| Entity | Sentences added |", "|---|---|"]
        lines += [f"| {name} | {added} |" for name, added in md["per_entity"][:20]]
        lines += ["", f"Relationship edges — added: {len(rd['added'])}, removed: {len(rd['removed'])}, re-weighted: {len(rd['reweighted'])}", ""]
        if rd["added"]:
            lines += ["| New edge | Co-occurrences |", "|---|---|"]
            lines += [f"| {' ↔ '.join(relationship_key(rel))} | {rel.get('cooccurrence_count', '?')} |" for rel in rd["added"]]
            lines.append("")
        if rd["reweighted"]:
            lines += ["| Re-weighted edge | Before | After |", "|---|---|---|"]
            lines += [f"| {' ↔ '.join(rw['pair'])} | {rw['before']} | {rw['after']} |" for rw in rd["reweighted"]]
            lines.append("")
    return "\n".join(lines) + "\n"


def render_sample(samples: dict, chapters: dict) -> str:
    """Manual-review sheet; `samples` maps variant -> sample_new_sentences() output."""
    lines = ["# Coref attributions — manual review", "",
             "For each row: is the claimed referent the correct antecedent of the",
             "pronoun(s) in the sentence? Mark ✓ or ✗ in the last column.", ""]
    for variant, rows in samples.items():
        lines += [f"## {variant}", "",
                  "| # | Claimed referent | Chapter | Sentence (context) | ✓/✗ |",
                  "|---|---|---|---|---|"]
        for i, row in enumerate(rows, 1):
            ctx = extract_context(chapters.get(row["chapter_id"], ""), row["sentence"])
            ctx = ctx.replace("|", "\\|").replace("\n", " ")
            sent = row["sentence"].replace("|", "\\|")
            lines.append(f"| {i} | {row['entity']} | {row['chapter_id']} | **{sent}** — {ctx} | |")
        lines.append("")
    return "\n".join(lines) + "\n"
```

(The orchestration half — `run_variant`, `run_all`, `main` — is Task 4; the file is importable without it.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_eval_coref.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/eval_coref.py tests/test_eval_coref.py
git commit -m "feat(eval): coref eval harness pure core — deltas, sampling, rendering (STU-427)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Variant runner and orchestration

**Files:**
- Modify: `scripts/eval_coref.py` (append below the pure core)
- Modify: `tests/test_eval_coref.py`

**Interfaces:**
- Consumes: Task 3's pure functions; `book_paths_from_yaml` from `wiki_creator.paths`; `_load_mentions_from_files`, `enrich_mentions_with_fastcoref`, `build_cooccurrence_graph`, `DEFAULT_WINDOW`, `DEFAULT_THRESHOLD`, `DEFAULT_MIN_CHAPTERS_TOGETHER` from `scripts.relationship_extraction`.
- Produces: CLI `python scripts/eval_coref.py --book <yaml> [--workers N] [--sample N] [--seed N] [--variants a,b,c]`; internal child mode `--variant-run <name>`; outputs under `<processing>/coref_eval/`.

- [ ] **Step 1: Write failing tests for the orchestration seams**

Append to `tests/test_eval_coref.py`:

```python
def test_variant_output_dir_layout(tmp_path):
    d = ec.variant_dir(tmp_path, "coref-8k")
    assert d == tmp_path / "coref_eval" / "coref-8k"


def test_build_child_command_uses_time_v(monkeypatch):
    monkeypatch.setattr(ec.shutil, "which", lambda name: "/usr/bin/time" if name == "time" else None)
    cmd = ec.build_child_command("coref-8k", "book.yaml", workers=4)
    assert cmd[:2] == ["/usr/bin/time", "-v"]
    assert "--variant-run" in cmd and "coref-8k" in cmd
    assert cmd[cmd.index("--workers") + 1] == "4"


def test_build_child_command_without_gnu_time(monkeypatch):
    monkeypatch.setattr(ec.shutil, "which", lambda name: None)
    cmd = ec.build_child_command("baseline", "book.yaml", workers=1)
    assert cmd[0].endswith("python") or "python" in cmd[0]
    assert "/usr/bin/time" not in cmd
```

Run: `pytest tests/test_eval_coref.py -k "variant_output or child_command" -v`
Expected: FAIL — names not defined.

- [ ] **Step 2: Implement runner + orchestration**

Append to `scripts/eval_coref.py`:

```python
# ------------------------------------------------------------ orchestration

def variant_dir(processing: Path, variant: str) -> Path:
    return processing / "coref_eval" / variant


def build_child_command(variant: str, book_yaml: str, workers: int) -> list[str]:
    """Child invocation, wrapped in GNU time -v when available."""
    cmd = [sys.executable, str(Path(__file__).resolve()), "--variant-run", variant,
           "--book", str(book_yaml), "--workers", str(workers)]
    gnu_time = shutil.which("time")
    if gnu_time:
        cmd = [gnu_time, "-v"] + cmd
    return cmd


def _load_book(book_yaml: Path):
    """(paths, cfg, entities, chapters) for one book."""
    import yaml
    from wiki_creator.paths import book_paths_from_yaml

    paths = book_paths_from_yaml(book_yaml)
    with open(book_yaml, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    with open(paths.processing / "entities_classified.json", encoding="utf-8") as f:
        entities = json.load(f)["entities"]
    with open(paths.processing / "chapters.json", encoding="utf-8") as f:
        chapters = json.load(f).get("chapters", {})
    return paths, cfg, entities, chapters


def run_variant(book_yaml: Path, variant: str, workers: int) -> None:
    """Child mode: run one variant in-process and write its outputs."""
    from scripts.relationship_extraction import (
        DEFAULT_MIN_CHAPTERS_TOGETHER,
        DEFAULT_THRESHOLD,
        DEFAULT_WINDOW,
        _load_mentions_from_files,
        build_cooccurrence_graph,
        enrich_mentions_with_fastcoref,
    )

    paths, cfg, entities, chapters = _load_book(book_yaml)
    mentions = _load_mentions_from_files(paths.processing)
    sentences_before = count_sentences(mentions)

    if variant != "baseline":
        mentions = enrich_mentions_with_fastcoref(
            chapters, entities, mentions,
            workers=workers,
            spacy_model=cfg.get("spacy_model", "fr_core_news_lg"),
            max_chars=VARIANT_MAX_CHARS[variant],
        )

    min_cooc = cfg.get("min_cooccurrence")
    relationships, stats = build_cooccurrence_graph(
        entities, mentions,
        int(cfg.get("window", DEFAULT_WINDOW)),
        int(cfg.get("threshold", DEFAULT_THRESHOLD)),
        min_cooccurrence=int(min_cooc) if min_cooc is not None else None,
        min_chapters_together=int(cfg.get("min_chapters_together", DEFAULT_MIN_CHAPTERS_TOGETHER)),
    )
    stats["pronoun_sentences_added"] = count_sentences(mentions) - sentences_before

    out = variant_dir(paths.processing, variant)
    out.mkdir(parents=True, exist_ok=True)
    for name, data in (("mentions.json", mentions), ("relationships.json", relationships), ("stats.json", stats)):
        with open(out / name, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[eval/{variant}] wrote {out} — {stats['pronoun_sentences_added']} pronoun sentences added", file=sys.stderr)


def run_all(book_yaml: Path, workers: int, sample_n: int, seed: int, variants: tuple[str, ...] = VARIANTS) -> Path:
    """Parent mode: run every variant, compute deltas, write report + sample."""
    paths, _cfg, _entities, chapters = _load_book(book_yaml)
    eval_root = paths.processing / "coref_eval"
    results: dict[str, dict] = {}

    for variant in variants:
        print(f"[eval] running {variant}…", file=sys.stderr)
        t0 = time.monotonic()
        proc = subprocess.run(
            build_child_command(variant, str(book_yaml), workers),
            capture_output=True, text=True,
        )
        wall = time.monotonic() - t0
        sys.stderr.write(proc.stderr)
        if proc.returncode != 0:
            raise RuntimeError(f"variant {variant} failed (exit {proc.returncode})")
        with open(variant_dir(paths.processing, variant) / "stats.json", encoding="utf-8") as f:
            stats = json.load(f)
        results[variant] = {
            "wall_seconds": wall,
            "pronoun_sentences_added": stats.get("pronoun_sentences_added", 0),
            **parse_time_v(proc.stderr),
        }

    def _load(variant: str, name: str):
        with open(variant_dir(paths.processing, variant) / name, encoding="utf-8") as f:
            return json.load(f)

    base_mentions = _load("baseline", "mentions.json")
    base_rels = _load("baseline", "relationships.json")
    samples: dict[str, list[dict]] = {}
    for variant in variants:
        if variant == "baseline":
            continue
        var_mentions = _load(variant, "mentions.json")
        results[variant]["mention_deltas"] = compute_mention_deltas(base_mentions, var_mentions)
        results[variant]["relationship_deltas"] = compute_relationship_deltas(base_rels, _load(variant, "relationships.json"))
        samples[variant] = sample_new_sentences(base_mentions, var_mentions, n=sample_n, seed=seed)

    (eval_root / "report.md").write_text(render_report(paths.processing.name, results), encoding="utf-8")
    (eval_root / "sample_for_review.md").write_text(render_sample(samples, chapters), encoding="utf-8")
    print(f"[eval] report: {eval_root / 'report.md'}", file=sys.stderr)
    print(f"[eval] review sheet: {eval_root / 'sample_for_review.md'}", file=sys.stderr)
    return eval_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--book", required=True, help="path to the book .yaml")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--sample", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--variants", default=",".join(VARIANTS), help="comma-separated subset of variants")
    parser.add_argument("--variant-run", default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.variant_run:
        run_variant(Path(args.book), args.variant_run, args.workers)
        return
    run_all(Path(args.book), args.workers, args.sample, args.seed, tuple(args.variants.split(",")))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run unit tests**

Run: `pytest tests/test_eval_coref.py -v`
Expected: all PASS.

- [ ] **Step 4: Smoke-run the baseline variant on the real book**

Run (from worktree root — the library dir is shared via the main checkout; if `library/` is absent in the worktree, run this step from the main checkout with the branch's code):

```bash
python scripts/eval_coref.py \
  --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml \
  --variants baseline --workers 1
```

Expected: exits 0; `library/.../processing_output/01-throne-of-glass/coref_eval/baseline/{mentions,relationships,stats}.json` exist; `report.md` lists only `baseline`; `git status` inside `library/` shows only new `coref_eval/` files (nothing modified).

- [ ] **Step 5: Full suite + commit**

Run: `pytest -q` — expected: no regression vs 735/31 baseline.

```bash
git add scripts/eval_coref.py tests/test_eval_coref.py
git commit -m "feat(eval): coref eval variant runner and orchestration (STU-427)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Run the full evaluation on Throne of Glass — CHECKPOINT

**Files:**
- Read/produce: `library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/coref_eval/` (report + review sheet; not committed unless Ariane wants them)

**Interfaces:**
- Consumes: the harness CLI from Task 4.
- Produces: `report.md` (metrics for the decision) and `sample_for_review.md` (for Ariane's manual ✓/✗ pass).

- [ ] **Step 1: Verify the coref extra is importable**

Run: `python -c "import fastcoref, torch; print('coref extra OK')"`
Expected: `coref extra OK`. If it fails: `pip install -e ".[coref]"`.

- [ ] **Step 2: Run all three variants**

```bash
python scripts/eval_coref.py \
  --book library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml \
  --workers 4
```

Expected: three `[eval] running <variant>…` lines; first coref run downloads `biu-nlp/lingmess-coref` (~1.5 GB, one-time); total wall time tens of minutes for `coref-full` at 4 workers; ends with the two `[eval] report:` / `[eval] review sheet:` paths. Watch that `pronoun_sentences_added` is 0 for baseline and > 0 for both coref variants — if a coref variant reports 0, check stderr for the `[WARN] fastcoref unavailable` fallback before trusting the numbers.

- [ ] **Step 3: Sanity-check the report**

Read `coref_eval/report.md`: wall time and peak RSS present for all variants (RSS ~3–10 GB for coref runs), mention/relationship delta tables non-degenerate, `coref-full` ≥ `coref-8k` on sentences added.

- [ ] **Step 4: STOP — hand the review sheet to Ariane**

Post the report summary and the path to `sample_for_review.md`. Ariane marks ✓/✗ per row; precision = ✓/(✓+✗) per variant. **Do not proceed to Task 6's recommendation content until she reports the counts.** (Decision frame from the spec: recommend English-book default only if precision ≥ ~90% and meaningful new edges among relevant entities, within ~10 GB / minutes-scale cost.)

---

### Task 6: Documentation + Linear close-out (after manual review)

**Files:**
- Create: `docs/coref-evaluation.md`
- Modify: `docs/flow-audit.md` (gap §2, line ~152)
- External: summary comment on STU-427 (Linear MCP)

**Interfaces:**
- Consumes: `report.md` numbers + Ariane's precision counts from Task 5.

- [ ] **Step 1: Write `docs/coref-evaluation.md`**

Structure (fill every bracket from `report.md` and the review counts — no bracket may survive into the commit):

```markdown
# Évaluation coref — fastcoref/LingMessCoref (STU-427)

Évaluation empirique sur *Throne of Glass* (60 chapitres, ~643k caractères),
harnais : `scripts/eval_coref.py` (3 variantes : baseline / cap 8k / chapitre complet).

## Résultats

| Variante | Temps (4 workers) | RAM pic | Phrases pronominales ajoutées | Arêtes ajoutées | Précision (échantillon n=[N]) |
|---|---|---|---|---|---|
| baseline | [s] | [GB] | 0 | — | — |
| coref-8k | [s] | [GB] | [n] | [n] | [%] |
| coref-full | [s] | [GB] | [n] | [n] | [%] |

## Recommandation

[Enable-by-default pour les livres anglais : oui/non + justification chiffrée
selon le cadre de décision du spec (précision ≥ ~90 %, gain d'arêtes réel,
coût ≤ ~10 GB / quelques minutes).]

## Activation

- `pip install -e ".[coref]"` — extra requis depuis la relicence (tire torch,
  ~2 GB). Sans l'extra, le pipeline retombe silencieusement sur l'heuristique naïve.
- Livre YAML : `coref: true`, `workers: N` (~3 GB à 1 worker, ~10 GB à 4),
  `coref_max_chars: 0` pour lever le cap de 8 000 caractères par chapitre.
- Limitation : LingMessCoref est **anglais seulement** — laisser `coref: false`
  pour les livres français.
- Harnais réutilisable sur un autre livre :
  `python scripts/eval_coref.py --book <book.yaml> --workers 4`
```

- [ ] **Step 2: Update `docs/flow-audit.md` gap §2**

At the end of the paragraph at line ~152-153 (« …ne contribuent donc pas aux comptes de mentions ni aux relations. »), append:

```markdown
Évalué empiriquement dans le cadre de STU-427 — résultats et recommandation dans
[coref-evaluation.md](coref-evaluation.md) ; le cap de 8 000 caractères par chapitre
est désormais configurable (`coref_max_chars`).
```

- [ ] **Step 3: Commit**

```bash
git add docs/coref-evaluation.md docs/flow-audit.md
git commit -m "docs(coref): STU-427 evaluation results and activation guide

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Comment on STU-427**

Via Linear MCP (`save_comment` on STU-427): the results table, the recommendation, a pointer to `docs/coref-evaluation.md`, and the explicit note that flipping `coref:` defaults is a separate decision/commit.

- [ ] **Step 5: Final verification**

Run: `pytest -q` (expect ≥ 735 passed, 31 skipped, 0 failed) and `mypy wiki_creator/` (unchanged — no `wiki_creator/` files touched).

---

## Self-Review Notes

- Spec coverage: Component 1 → Tasks 1–2; Component 2 → Tasks 3–4; Component 3 → Task 5 checkpoint; Component 4 → Task 6. Out-of-scope items (default flip, per-tier gating, French models) appear in no task. ✓
- The `[bracket]` fields in Task 6 are deliverable templates filled from measured results at execution time, gated by the Task 5 STOP — not plan placeholders.
- Type consistency: `max_chars`/`coref_max_chars` naming is deliberate — `max_chars` on the enrich/worker API, `coref_max_chars` in YAML/CLI where the coref prefix disambiguates.
```
