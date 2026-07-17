# STU-551 — `affiliation` as a per-tome scalar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the `affiliation` infobox slot — declared and inert since STU-504 — with the faction each PERSON belongs to at the end of the tome.

**Architecture:** A 1:1 mirror of STU-488's `entity_status`: a pre-step to `wiki-preparation` that sends the PERSON roster to one `studio run entity-affiliation-item` per book, caches the verdicts keyed on the roster rows, stamps them onto the batch entity, and renders them via `_extracted_fact_value`. Pure logic in `wiki_creator/entity_affiliation.py`, runner in `scripts/entity_affiliation.py`. Not a `wiki-resolution` stage: it changes no identity, and resolution is the chain `make golden` runs.

**Tech Stack:** Python 3.14, pytest, Studio CLI (`studio run`), PyYAML.

**Spec:** [docs/superpowers/specs/2026-07-16-stu-551-affiliation-design.md](../specs/2026-07-16-stu-551-affiliation-design.md) (commit `1115887`)

## Global Constraints

- **Worktree:** `/home/arianeguay/dev/src/wiki-creator-stu-551`, branch `arianedguay/stu-551-faction-change-as-a-dated-edge-affiliation-slot`, based on `origin/main` @ `4d0dda9`.
- **`PYTHONPATH` is mandatory for every python invocation in this worktree.** `pip install -e .` pins the main checkout, so without it `scripts/` here runs against `main`'s `wiki_creator/`. Prefix every command: `PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551`.
- **No hardcoded word lists in `.py`.** All vocabulary lives in `wiki_creator/cue_words/<lang>.json`. No fallback vocabulary constant — an absent key degrades to an empty collection.
- **English only in code.** No French string literals in `.py`. Reader-facing strings are data in `base.yaml`, read via helpers.
- **No `base.yaml` change.** The slot (line 56) and the mediawiki row (line 44) already exist.
- **Every failure path omits the slot.** `affiliation` is `OPT` with no declared fallback. The run never fails.
- **Commit trailer:** `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Goldens are out of reach** — the golden chain stops at `write-registry`. `make golden` / `make smoke` must stay LLM-free.

## File Structure

| File | Responsibility |
|---|---|
| `wiki_creator/roster.py` | **Create (Task 3).** The helpers `entity_status` and `entity_affiliation` share byte-for-byte: text normalization, marker matching, chapter sort, roster rendering, quote verification, cache read/write. |
| `wiki_creator/entity_status.py` | **Modify (Task 3).** Import the shared helpers instead of defining them. Behavior unchanged — pinned by its existing suite. |
| `wiki_creator/entity_affiliation.py` | **Create.** Pure logic: snippet selection, verdict parsing + the three rejection rules. Everything shared comes from `roster.py`. |
| `scripts/entity_affiliation.py` | **Create.** Runner: reads `registry.json`, builds the roster, shells out to `studio run`, writes the cache, reports to stderr. Never raises. |
| `.studio/agents/entity-affiliation.agent.yaml` | **Create.** The prompt. |
| `.studio/contracts/entity-affiliation-item.contract.yaml` | **Create.** `required_fields: [affiliation]`. |
| `.studio/pipelines/entity-affiliation-item.pipeline.yaml` | **Create.** One stage, `max_attempts: 3`. |
| `wiki_creator/cue_words/en.json`, `fr.json` | **Modify.** Add `affiliation_markers`. |
| `scripts/wiki_preparation.py` | **Modify.** `load_affiliation_verdicts` + stamp `affiliation` in `build_entity_bundle`. |
| `scripts/generate_wiki_pages.py:735-746` | **Modify.** One branch in `_extracted_fact_value`; drop `affiliation` from the docstring's "future slices". |
| `run_wiki.py:92-96` | **Modify.** Add the pre-step. |
| `tests/test_entity_affiliation.py` | **Create.** Unit + wiring tests. |
| `tests/test_generate_wiki_pages_binding.py:198` | **Modify.** An existing assertion pins the inert behavior and will fail. |

**Reuse, do not reimplement.** `normalize`'s typographic folding is the `99a6a71` fix — reimplementing it reintroduces a bug that silently dropped every verdict whose evidence sat in dialogue. Task 3 puts it, and every other helper the two stages share verbatim, in `wiki_creator/roster.py`.

**Pre-flight decision (approved): Option A-reduced.** The plan as first written duplicated four of `entity_status`'s seven functions verbatim into `entity_affiliation`. `render_roster`, `_is_quoted` and the two cache functions are byte-identical, so Task 3 extracts them. `roster_rows` stays duplicated in each stage: parameterising it by selector is speculative abstraction for two callers, and each stage's version is three lines. `_normalize`/`_latest_first`/`_has_marker` move to `roster.py` as well — leaving them in `entity_status` while `roster.py` needs them, and `entity_status` needs `roster.py`, is an import cycle.

---

### Task 1: Measure — does GLiNER produce a real faction roster?

**This task decides Task 5's prompt and Task 4's rule set. It writes no production code.**

The spec's A-vs-B choice is open because the measurement that would settle it was taken against artifacts that STU-560 (`4d0dda9`) has just invalidated: all three cached books rendered spaCy-typed entities while configured for GLiNER.

**Files:**
- Create: `docs/superpowers/specs/2026-07-16-stu-551-affiliation-design.md` — append a `## Measurement result` section (modify).

**Interfaces:**
- Produces: a decision, **A** or **B**, recorded in the spec. Task 3 and Task 4 read it.

- [ ] **Step 1: Check the GPU is free**

```bash
nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader
```

Expected: at least ~2.5 GB free. GLiNER large needs it. If other worktrees hold the GPU (`for p in $(pgrep -f entity_extraction); do readlink /proc/$p/cwd; done`), **wait** — do not fall back to CPU (hours) and do not truncate.

**Do NOT set `WIKI_MAX_CHAPTERS`.** A subset answers a different question — that is exactly how STU-539's premise came to be false.

- [ ] **Step 2: Re-extract Eragon under GLiNER**

`01_eragon.yaml` already declares `invented_names: true`. `processing_output/01_eragon/` in this worktree holds only `epub_data.json` and `section_filter.json` (the LLM stage, cached — it will not re-run).

```bash
cd /home/arianeguay/dev/src/wiki-creator-stu-551
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  studio run wiki-extraction --input-file library/christopher_paolini/inheritance/books/01_eragon.yaml
```

Expected: `✓ Pipeline completed`, and `factions_full.json` + `orgs_full.json` + `persons_full.json` in `library/christopher_paolini/inheritance/processing_output/01_eragon/`.

If it dies with `Error: write EPIPE`, that is the Studio CLI swallowing the python stage's stderr — a known defect (see the spec's follow-ups). Get the real error by running the stage directly:

```bash
python3 - <<'EOF' > /tmp/payload.json
import json, pathlib
base = pathlib.Path("library/christopher_paolini/inheritance/processing_output/01_eragon")
yaml = pathlib.Path("library/christopher_paolini/inheritance/books/01_eragon.yaml").read_text()
epub = json.loads((base/"epub_data.json").read_text())
sf   = json.loads((base/"section_filter.json").read_text())
print(json.dumps({"additional_context": yaml,
                  "previous_outputs": {"epub-parse": epub, "section-filter": sf},
                  "all_stage_outputs": {"epub-parse": epub, "section-filter": sf}}))
EOF
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python3 scripts/entity_extraction.py < /tmp/payload.json > /tmp/out.json
```

- [ ] **Step 3: Read the roster — then score**

**Read it before forming an expectation.** STU-488's prediction was wrong on both halves before contact with the artifact.

```bash
cd /home/arianeguay/dev/src/wiki-creator-stu-551
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 python3 - <<'EOF'
import json, pathlib
base = pathlib.Path("library/christopher_paolini/inheritance/processing_output/01_eragon")
for kind in ("factions_full", "orgs_full"):
    d = json.loads((base/f"{kind}.json").read_text())
    items = d[kind] if isinstance(d, dict) and kind in d else d
    items = list(items.values()) if isinstance(items, dict) else items
    print(f"=== {kind}: {len(items)}")
    for e in items:
        print("   ", e.get("raw_mentions"), "count=", e.get("mention_count"))
EOF
```

- [ ] **Step 4: Decide, and record the decision in the spec**

The question: **is there a roster of real factions to bind a value to?**

- `Varden` / `Empire` / `Urgals` present and typed FACTION or ORG, with the spaCy junk (`Garrow`, `Utgard`, `ALFRED A. KNOPF`) gone → **A**. It dominates B: the roster check is free anti-hallucination, and the value becomes wikilinkable later without re-extraction.
- Roster still species-and-noise, or the real factions absent → **B**.

Also re-run the roster read for `01-throne-of-glass` (measured 0 ORG / 0 FACTION pre-STU-560). **A book that yields no vocabulary makes the slot a no-op there** — that is A's decisive cost, and throne-of-glass is the Makefile's default `BOOK`.

Append to the spec, replacing the "Open question" callout at its top:

```markdown
## Measurement result (Task 1)

Re-extracted `01_eragon` under GLiNER post-STU-560 on <date>.

FACTION: <the actual list>
ORG:     <the actual list>
throne-of-glass: <the actual list>

**Decision: <A|B>.** <One sentence on what the roster showed.>
```

- [ ] **Step 5: Commit**

```bash
cd /home/arianeguay/dev/src/wiki-creator-stu-551
git add docs/superpowers/specs/2026-07-16-stu-551-affiliation-design.md
git commit -m "docs(stu-551): record the post-STU-560 faction roster measurement

<A|B> chosen. <what the roster showed>.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `affiliation_markers` vocabulary

**Files:**
- Modify: `wiki_creator/cue_words/en.json`, `wiki_creator/cue_words/fr.json`
- Test: `tests/test_entity_affiliation.py` (create)

**Interfaces:**
- Produces: `affiliation_markers` key in each language's cue_words — a `list[str]`. Task 3's `select_affiliation_snippets` consumes it.

The markers **retrieve, they do not decide** (the STU-538 line). A marker missing means an affiliation is never retrieved, which means an omitted slot — the forgiving direction. So the list may be poor; it may not be a verdict.

- [ ] **Step 1: Write the failing test**

Create `tests/test_entity_affiliation.py`:

```python
"""STU-551: affiliation is the faction a character belongs to at the end of the tome."""
import json
from pathlib import Path

CUE_WORDS = Path(__file__).resolve().parents[1] / "wiki_creator" / "cue_words"


def test_both_languages_declare_affiliation_markers():
    # The vocabulary is data, never a constant in a .py (CLAUDE.md).
    for lang in ("en", "fr"):
        cues = json.loads((CUE_WORDS / f"{lang}.json").read_text(encoding="utf-8"))
        assert cues["affiliation_markers"], f"{lang} has no affiliation_markers"
        assert all(isinstance(m, str) and m for m in cues["affiliation_markers"])
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd /home/arianeguay/dev/src/wiki-creator-stu-551
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_affiliation.py -v
```

Expected: FAIL — `KeyError: 'affiliation_markers'`

- [ ] **Step 3: Add the vocabulary**

In `wiki_creator/cue_words/en.json`, add the key (keep the file's existing alphabetical ordering of keys):

```json
  "affiliation_markers": [
    "joined", "join", "joins", "joining", "rejoined",
    "member", "members", "belonged", "belongs", "belong",
    "served", "serves", "serve", "serving", "service",
    "loyal", "loyalty", "allegiance", "sworn", "swore", "oath", "pledged",
    "follower", "followers", "recruit", "recruited",
    "ranks", "band", "order", "guild", "army", "forces",
    "betrayed", "defected", "deserted", "renounced", "abandoned",
    "fought for", "fights for", "sided", "side"
  ],
```

In `wiki_creator/cue_words/fr.json`:

```json
  "affiliation_markers": [
    "rejoint", "rejoignit", "rejoindre", "rejoignirent",
    "membre", "membres", "appartient", "appartenait", "appartenir",
    "servi", "sert", "servir", "servait", "service",
    "loyal", "loyale", "loyauté", "allégeance", "serment", "juré", "jura",
    "partisan", "partisans", "recrue", "recruté",
    "rangs", "bande", "ordre", "guilde", "armée", "forces",
    "trahi", "trahit", "déserté", "renié", "abandonné",
    "combattu pour", "combat pour", "rallié", "camp"
  ],
```

- [ ] **Step 4: Run it to verify it passes**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_affiliation.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/cue_words/en.json wiki_creator/cue_words/fr.json tests/test_entity_affiliation.py
git commit -m "feat(stu-551): affiliation_markers vocabulary

The markers retrieve, they do not decide (STU-538): a marker in a snippet
picks which snippets the classifier reads, and the classifier reads which
faction the character belongs to. A marker missing from the vocabulary means
an affiliation is never surfaced, which means the slot is omitted.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Extract the helpers both stages share — `wiki_creator/roster.py`

**A pure refactor. No behavior changes. `entity_status`'s existing suite is the proof.**

Both stages send a PERSON roster to one `studio run`, verify the reply against the
snippets shown, and cache on the roster rows. That shared shape is real, not a
coincidence — STU-529, STU-539 and STU-488 all have it. Four functions are byte-identical
between them.

**Files:**
- Create: `wiki_creator/roster.py`
- Modify: `wiki_creator/entity_status.py` — delete the moved definitions, import them
- Test: `tests/test_entity_status.py` must pass **unchanged**. That is the whole safety net.

**Interfaces:**
- Produces, all consumed by Tasks 4 and 5:
  - `normalize(text: object) -> str` (was `entity_status._normalize`)
  - `has_marker(text: str, markers: list[str]) -> bool` (was `_has_marker`)
  - `latest_first(snippets: list[dict]) -> list[dict]` (was `_latest_first`)
  - `render_roster(rows: list[dict]) -> str`
  - `is_quoted(quote: str, snippets: list[dict]) -> bool` (was `_is_quoted`)
  - `load_cache(path: Path | str, rows: list[dict]) -> dict[str, dict] | None`
  - `save_cache(path: Path | str, rows: list[dict], verdicts: dict[str, dict]) -> None`
- `entity_status` keeps: `STATUS_VALUES`, `DEFAULT_STATUS`, `SNIPPETS_PER_ENTITY`, `SNIPPET_CHARS`, `select_status_snippets`, `roster_rows`, `parse_status_verdict`, `status_label`, and thin aliases `load_cached_status = load_cache`, `save_status_cache = save_cache` — `scripts/entity_status.py` and `tests/test_entity_status.py` import those names and must not change.

- [ ] **Step 1: Verify the baseline is green before touching anything**

```bash
cd /home/arianeguay/dev/src/wiki-creator-stu-551
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_status.py -q
```

Expected: all pass. Record the count — it must be identical at Step 4.

- [ ] **Step 2: Create the shared module**

Create `wiki_creator/roster.py` by **moving** these definitions out of
`wiki_creator/entity_status.py` verbatim (renamed to drop the leading underscore where
noted). Do not rewrite them — a rewrite is a behavior change with no test to catch it.

```python
"""What a roster-classifier stage does regardless of what it asks.

`entity_status` (STU-488) and `entity_affiliation` (STU-551) both send the PERSON
roster to one `studio run`, verify the reply against the snippets they showed, and
cache on the roster rows. The shape is STU-529's and STU-539's before them. What
differs is the question — which snippets to select, and what makes a verdict valid.
That stays in each stage; this is the rest.

`normalize`'s typographic folding is load-bearing (99a6a71): an EPUB's dialogue ships
curly quotes and the model echoes straight ones, so without folding both sides every
verdict whose evidence sat inside dialogue was silently dropped — in a novel, where
such facts are announced in dialogue.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_creator.chapters import chapter_number

_WHITESPACE_RE = re.compile(r"\s+")

# An EPUB's typesetting uses curly quotes/dashes; the model echoes the same
# sentence back in plain ASCII. Folding both to one form is what lets a
# verbatim quote inside dialogue still match its source snippet.
_TYPOGRAPHIC_TRANSLATION = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "′": "'",
        "″": '"',
        "…": "...",
        "–": "-",
        "—": "-",
        "‑": "-",
    }
)


def normalize(text: object) -> str:
    folded = str(text or "").translate(_TYPOGRAPHIC_TRANSLATION)
    return _WHITESPACE_RE.sub(" ", folded).strip().casefold()


def has_marker(text: str, markers: list[str]) -> bool:
    return any(
        re.search(r"\b" + re.escape(marker) + r"\b", text, re.IGNORECASE)
        for marker in markers
        if marker
    )


def latest_first(snippets: list[dict]) -> list[dict]:
    """Sorted by chapter, latest first. An unnumbered chapter (``Prologue``)
    sorts earliest. Stable, so same-chapter snippets keep source order."""
    return sorted(
        snippets,
        key=lambda snippet: chapter_number(snippet.get("chapter_id")) or 0,
        reverse=True,
    )


def render_roster(rows: list[dict]) -> str:
    """The roster block the classifier reads. Text only — the chapter is never
    shown or reported by the model."""
    blocks = []
    for row in rows:
        header = row["name"]
        if row["aliases"]:
            header += f" (also called: {', '.join(row['aliases'])})"
        lines = [f"## {header}"]
        lines.extend(f"- {snippet['text']}" for snippet in row["snippets"])
        if not row["snippets"]:
            lines.append("- (no snippet found for this character)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def is_quoted(quote: str, snippets: list[dict]) -> bool:
    """True iff ``quote`` is verbatim in one of the entity's own ``snippets``."""
    needle = normalize(quote)
    if not needle:
        return False
    return any(needle in normalize(snippet.get("text")) for snippet in snippets)


def load_cache(path: Path | str, rows: list[dict]) -> dict[str, dict] | None:
    """Cached verdicts for exactly this roster, or None.

    Keyed on the rows themselves: the roster changes with WIKI_MAX_CHAPTERS and
    with every upstream extraction fix, and a verdict returned for a different
    roster must not be replayed onto it.
    """
    try:
        cached = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("roster") != rows:
        return None
    verdicts = cached.get("verdicts")
    return verdicts if isinstance(verdicts, dict) else None


def save_cache(path: Path | str, rows: list[dict], verdicts: dict[str, dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"roster": rows, "verdicts": verdicts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 3: Rewire `entity_status.py`**

Delete from `wiki_creator/entity_status.py`: `_WHITESPACE_RE`, `_TYPOGRAPHIC_TRANSLATION`, `_normalize`, `_has_marker`, `_latest_first`, `_is_quoted`, `render_roster`, `load_cached_status`, `save_status_cache`, and the now-unused `import json` / `import re` / `chapter_number` import if nothing else uses them.

Replace with:

```python
from wiki_creator.roster import (
    has_marker,
    is_quoted,
    latest_first,
    load_cache,
    normalize,
    render_roster,
    save_cache,
)

# scripts/entity_status.py and tests/test_entity_status.py import these names.
load_cached_status = load_cache
save_status_cache = save_cache
```

Then update the internal call sites in `select_status_snippets` (`_has_marker` → `has_marker`, `_latest_first` → `latest_first`) and `parse_status_verdict` (`_is_quoted` → `is_quoted`).

`render_roster` is re-exported by the import above, so `scripts/entity_status.py`'s `from wiki_creator.entity_status import render_roster` keeps working.

- [ ] **Step 4: Prove nothing moved**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_status.py tests/test_entity_affiliation.py -q
```

Expected: the **same** pass count as Step 1, plus Task 2's test. Not one test edited — if a test needed changing, the refactor changed behavior and is wrong.

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 python -m pytest -q
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 mypy wiki_creator/
```

Expected: full suite green, no new mypy errors.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/roster.py wiki_creator/entity_status.py
git commit -m "refactor(stu-551): extract the helpers roster stages share

entity_status (STU-488) and entity_affiliation (STU-551) send a PERSON roster to
one studio run, verify the reply against the snippets shown, and cache on the
roster rows. Four functions were byte-identical between them; this moves them out
before the second copy exists rather than after.

What differs — which snippets to select, and what makes a verdict valid — stays
in each stage. roster_rows stays duplicated: parameterising it by selector is
speculative abstraction for two callers.

Pure move. tests/test_entity_status.py passes unchanged, which is the point.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Pure logic — `wiki_creator/entity_affiliation.py`

**Files:**
- Create: `wiki_creator/entity_affiliation.py`
- Test: `tests/test_entity_affiliation.py` (modify — append)

**Interfaces:**
- Consumes: `affiliation_markers` (Task 2); `wiki_creator.roster.{normalize, has_marker, latest_first, render_roster, is_quoted, load_cache, save_cache}` (Task 3).
- Produces:
  - `SNIPPETS_PER_ENTITY: int = 5`, `SNIPPET_CHARS: int = 300`
  - `select_affiliation_snippets(snippets: list[dict], markers: list[str]) -> list[dict]`
  - `roster_rows(entities: list[dict], contexts: dict[str, list[dict]], markers: list[str]) -> list[dict]`
  - `parse_affiliation_verdict(payload: object, rows: list[dict]) -> dict[str, dict]` → `{name: {"affiliation": str, "quote": str}}`

  Task 5 (`scripts/entity_affiliation.py`) and Task 6 (`wiki_preparation`) consume these names, plus `render_roster` / `load_cache` / `save_cache` straight from `wiki_creator.roster`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_affiliation.py`:

```python
import pytest

from wiki_creator.entity_affiliation import (
    SNIPPETS_PER_ENTITY,
    parse_affiliation_verdict,
    roster_rows,
    select_affiliation_snippets,
)
from wiki_creator.roster import load_cache, render_roster, save_cache

MARKERS = ["joined", "loyal", "betrayed"]


def _snip(text, chapter_id):
    return {"text": text, "chapter_id": chapter_id}


def test_only_marker_bearing_snippets_are_kept():
    """Single-source, unlike `status`: no sentence proves "no affiliation", so
    there is no `alive`-analogue proved by lateness. A snippet with no marker
    can only confirm the character exists."""
    chosen = select_affiliation_snippets(
        [_snip("Eragon joined the Varden.", "ch10"), _snip("Eragon ate bread.", "ch11")],
        MARKERS,
    )
    assert [s["text"] for s in chosen] == ["Eragon joined the Varden."]


def test_marker_snippets_are_latest_first():
    """Latest-first is what makes the scalar mean "end of tome" — it absorbs an
    intra-tome switch without dating it."""
    chosen = select_affiliation_snippets(
        [_snip("Eragon joined the Empire.", "ch2"), _snip("Eragon joined the Varden.", "ch30")],
        MARKERS,
    )
    assert chosen[0]["text"] == "Eragon joined the Varden."


def test_snippets_are_capped():
    chosen = select_affiliation_snippets(
        [_snip(f"joined {i}", f"ch{i}") for i in range(20)], MARKERS
    )
    assert len(chosen) == SNIPPETS_PER_ENTITY


def test_no_markers_selects_nothing():
    """CLAUDE.md: an absent cue_words key degrades to an empty collection. No
    markers → no snippets → the slot is omitted. It must not crash."""
    assert select_affiliation_snippets([_snip("Eragon joined the Varden.", "ch1")], []) == []


def _rows():
    return roster_rows(
        [{"canonical_name": "Eragon", "aliases": []}],
        {"Eragon": [_snip("Eragon joined the Varden.", "ch10")]},
        MARKERS,
    )


def test_a_verdict_must_quote_the_entitys_own_snippet():
    """STU-539's rule. These novels are in the model's training data: without it,
    a verdict from its memory of the plot and one from this run's text are
    indistinguishable afterwards."""
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Eragon", "affiliation": "Varden",
                          "quote": "Eragon was crowned king of the Varden."}]},
        _rows(),
    )
    assert verdicts == {}


def test_the_value_must_appear_in_the_quote():
    """THE LOAD-BEARING RULE (STU-551). `status` returns an enum member, so
    verifying the quote verifies the verdict. `affiliation` returns a NAME, so
    the model can quote a real sentence and infer the wrong faction from it."""
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Eragon", "affiliation": "Empire",
                          "quote": "Eragon joined the Varden."}]},
        _rows(),
    )
    assert verdicts == {}


def test_a_grounded_verdict_survives():
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Eragon", "affiliation": "Varden",
                          "quote": "Eragon joined the Varden."}]},
        _rows(),
    )
    assert verdicts == {"Eragon": {"affiliation": "Varden", "quote": "Eragon joined the Varden."}}


def test_a_name_off_the_roster_is_rejected():
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Galbatorix", "affiliation": "Empire",
                          "quote": "Galbatorix led the Empire."}]},
        _rows(),
    )
    assert verdicts == {}


def test_typographic_quotes_match_a_straight_quoted_reply():
    """The 99a6a71 regression: the EPUB ships curly quotes, the model echoes
    straight ones. Inherited if _normalize is reimplemented instead of reused."""
    rows = roster_rows(
        [{"canonical_name": "Eragon", "aliases": []}],
        {"Eragon": [_snip("“I joined the Varden,” said Eragon.", "ch10")]},
        MARKERS,
    )
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Eragon", "affiliation": "Varden",
                          "quote": '"I joined the Varden," said Eragon.'}]},
        rows,
    )
    assert verdicts["Eragon"]["affiliation"] == "Varden"


@pytest.mark.parametrize("payload", ["not json", None, {}, {"affiliation": "a string"}, 42])
def test_unparseable_payloads_verdict_nothing(payload):
    assert parse_affiliation_verdict(payload, _rows()) == {}


def test_cache_is_keyed_on_the_roster_rows(tmp_path):
    """WIKI_MAX_CHAPTERS or any upstream extraction fix must not replay a verdict
    made for a different roster — STU-539's premise was measured false precisely
    because it was measured on a 5-chapter extraction."""
    cache = tmp_path / "entity_affiliation.json"
    verdicts = {"Eragon": {"affiliation": "Varden", "quote": "Eragon joined the Varden."}}
    save_cache(cache, _rows(), verdicts)
    assert load_cache(cache, _rows()) == verdicts

    other = roster_rows(
        [{"canonical_name": "Eragon", "aliases": []}],
        {"Eragon": [_snip("Eragon joined the Empire.", "ch10")]},
        MARKERS,
    )
    assert load_cache(cache, other) is None


def test_render_roster_shows_names_aliases_and_snippets():
    rendered = render_roster(
        roster_rows(
            [{"canonical_name": "Eragon", "aliases": ["Shadeslayer"]}],
            {"Eragon": [_snip("Eragon joined the Varden.", "ch10")]},
            MARKERS,
        )
    )
    assert "## Eragon (also called: Shadeslayer)" in rendered
    assert "- Eragon joined the Varden." in rendered
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_affiliation.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_creator.entity_affiliation'`

- [ ] **Step 3: Implement**

Create `wiki_creator/entity_affiliation.py`:

```python
"""Decide which faction a character belongs to at the end of this tome.

The `affiliation` infobox slot has been declared and inert since STU-504. STU-551
asked for a dated edge; it is a scalar. The wiki is per-tome and earlier tomes are
never regenerated, so "tome 3's faction on tome 3's page" is true by construction —
and STU-488 measured that dating a fact from the snippet that quotes it does not
work (3 of 4 derived chapters wrong: the place where the text states a fact is not
the place where the fact happens).

Snippet selection is single-source where `status` is two-source: no sentence proves
"no affiliation", so there is no `alive`-analogue proved by acting late. Marker-bearing
snippets, latest-first — which is what makes the scalar mean "end of tome" and absorbs
an intra-tome switch without dating it.

The marker vocabulary only **retrieves**; the classifier decides. STU-538 measured
that lesson at 340 fires and 0 true positives when a pattern *was* the verdict.

Every helper here fails toward an omitted slot. `affiliation` is OPT with no declared
fallback: a false affiliation puts a character in the wrong army on a page nobody will
reread, and reads as fact; an absent one says nothing.
"""

from __future__ import annotations

import json

from wiki_creator.roster import has_marker, is_quoted, latest_first, normalize

SNIPPETS_PER_ENTITY = 5
SNIPPET_CHARS = 300


def select_affiliation_snippets(snippets: list[dict], markers: list[str]) -> list[dict]:
    """Up to ``SNIPPETS_PER_ENTITY`` marker-bearing snippets, latest-first.

    Single-source, unlike `select_status_snippets`. `status` needs the latest
    snippets too because `alive` is proved by a character acting late; nothing
    proves the absence of an affiliation, so a snippet with no marker can only
    confirm the character exists.

    Snippets are ``{"text": str, "chapter_id": str}``.
    """
    marked = [
        snippet
        for snippet in snippets or []
        if has_marker(str(snippet.get("text") or ""), markers or [])
    ]
    return [
        {"text": str(s.get("text") or "")[:SNIPPET_CHARS], "chapter_id": s.get("chapter_id")}
        for s in latest_first(marked)[:SNIPPETS_PER_ENTITY]
    ]


def roster_rows(
    entities: list[dict], contexts: dict[str, list[dict]], markers: list[str]
) -> list[dict]:
    """One row per PERSON entity — the roster the classifier sees.

    ``contexts`` maps canonical_name -> that entity's snippets.
    """
    return [
        {
            "name": entity["canonical_name"],
            "aliases": sorted(a for a in (entity.get("aliases") or []) if a),
            "snippets": select_affiliation_snippets(
                contexts.get(entity["canonical_name"], []), markers
            ),
        }
        for entity in entities
    ]


def parse_affiliation_verdict(payload: object, rows: list[dict]) -> dict[str, dict]:
    """Map the classifier's reply to verified verdicts, keyed by roster name.

    A name absent from the result renders no slot; unparseable input verdicts
    nothing. A verdict survives three rules:

    1. its name is on the roster (the model hallucinates characters);
    2. its quote is verbatim in **that entity's own** snippets (STU-539: these
       novels are in the model's training data);
    3. **the affiliation is literally in the quote.** This is the rule `status`
       does not need. Its value is an enum member, so verifying the quote verifies
       the verdict; here the value is a name, so the model can quote a real
       sentence and infer the wrong faction from it.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("affiliation")
    if not isinstance(entries, list):
        return {}

    rows_by_name = {row["name"]: row for row in rows}
    verdicts: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        affiliation = str(entry.get("affiliation", "") or "").strip()
        quote = str(entry.get("quote", "") or "").strip()
        row = rows_by_name.get(name)
        if row is None or name in verdicts or not affiliation:
            continue
        if not is_quoted(quote, row["snippets"]):
            continue
        if normalize(affiliation) not in normalize(quote):
            continue
        verdicts[name] = {"affiliation": affiliation, "quote": quote}
    return verdicts
```

The cache is `roster.load_cache` / `roster.save_cache` — this module adds no cache of its
own. `render_roster` likewise comes from `roster`.

- [ ] **Step 4: Run to verify they pass**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_affiliation.py -v
```

Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/entity_affiliation.py tests/test_entity_affiliation.py
git commit -m "feat(stu-551): affiliation verdict parsing and snippet selection

Single-source snippet selection, latest-first — the scalar means "end of tome",
which is what absorbs an intra-tome switch without dating it (STU-488 measured
that dating from the quoting snippet does not work).

Three rejection rules. Two are STU-488's. The third is new and is the reason
this slot needs its own: `status` returns an enum member, so verifying the quote
verifies the verdict; `affiliation` returns a name, so the model can quote a real
sentence and infer the wrong faction from it. The value must be in the quote.

_normalize is imported, not reimplemented — its typographic folding is the
99a6a71 fix, without which every verdict quoted from dialogue is dropped.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Runner, agent, contract, pipeline

**Files:**
- Create: `scripts/entity_affiliation.py`, `.studio/agents/entity-affiliation.agent.yaml`, `.studio/contracts/entity-affiliation-item.contract.yaml`, `.studio/pipelines/entity-affiliation-item.pipeline.yaml`
- Test: `tests/test_entity_affiliation.py` (modify — append)

**Interfaces:**
- Consumes: everything Task 3 produces; `Registry.load_from_processing`, `book_paths_from_yaml`, `book_language`, `load_lang_config`, `studio_io`.
- Produces: `contexts_by_entity(registry) -> dict[str, list[dict]]`, `resolve_affiliation(rows, book_title, cache_path) -> dict[str, dict]`. Task 5 reads the artifact this writes.

**If Task 1 chose A**, the agent prompt gains a roster of allowed faction names and Task 4's `parse_affiliation_verdict` gains a fourth rule (value must be on the faction roster). **If B**, ship as written below.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_affiliation.py`:

```python
import json as _json
from unittest.mock import patch

from scripts.entity_affiliation import resolve_affiliation


def _ok_payload():
    class _Ok:
        returncode = 0
        stdout = _json.dumps({
            "stages": [{
                "name": "entity-affiliation-item",
                "output": {"affiliation": [
                    {"name": "Eragon", "affiliation": "Varden",
                     "quote": "Eragon joined the Varden."}
                ]},
            }]
        })
        stderr = ""
    return _Ok()


def test_resolve_caches_and_does_not_call_twice(tmp_path):
    cache = tmp_path / "entity_affiliation.json"
    with patch("scripts.entity_affiliation.subprocess.run", return_value=_ok_payload()):
        first = resolve_affiliation(_rows(), "Eragon", cache)
    assert first["Eragon"]["affiliation"] == "Varden"

    with patch("scripts.entity_affiliation.subprocess.run") as run:
        second = resolve_affiliation(_rows(), "Eragon", cache)
    run.assert_not_called()
    assert second == first


@pytest.mark.parametrize("boom", [FileNotFoundError, __import__("subprocess").TimeoutExpired("studio", 1)])
def test_every_failure_path_omits_the_slot_for_everyone(tmp_path, boom):
    """THE LOAD-BEARING TEST. A false affiliation puts a character in the wrong
    army on a page nobody will reread; an absent one says nothing. The run must
    never fail."""
    cache = tmp_path / "entity_affiliation.json"
    with patch("scripts.entity_affiliation.subprocess.run", side_effect=boom):
        assert resolve_affiliation(_rows(), "Eragon", cache) == {}


def test_a_nonzero_exit_omits_the_slot_for_everyone(tmp_path):
    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "boom"
    cache = tmp_path / "entity_affiliation.json"
    with patch("scripts.entity_affiliation.subprocess.run", return_value=_Fail()):
        assert resolve_affiliation(_rows(), "Eragon", cache) == {}


def test_a_stale_cache_from_another_roster_is_deleted_not_replayed(tmp_path):
    """wiki_preparation.load_affiliation_verdicts is roster-blind, so a give-up
    path that left the old artifact in place would let it replay a verdict made
    for a different roster."""
    cache = tmp_path / "entity_affiliation.json"
    save_cache(cache, _rows(), {"Eragon": {"affiliation": "Varden", "quote": "x"}})
    other = roster_rows(
        [{"canonical_name": "Murtagh", "aliases": []}],
        {"Murtagh": [_snip("Murtagh joined the Empire.", "ch40")]},
        MARKERS,
    )
    with patch("scripts.entity_affiliation.subprocess.run", side_effect=FileNotFoundError):
        assert resolve_affiliation(other, "Eragon", cache) == {}
    assert not cache.exists()
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_affiliation.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.entity_affiliation'`

- [ ] **Step 3: Create the runner**

Create `scripts/entity_affiliation.py`:

```python
#!/usr/bin/env python3
"""Pre-step: entity-affiliation — which faction does each character belong to?

Usage:
    python scripts/entity_affiliation.py --book library/.../book.yaml

Input:  processing_output/<slug>/registry.json
Output: processing_output/<slug>/entity_affiliation.json

Runs before wiki-preparation, which stamps the verdict onto the batch entity so
`generate_wiki_pages.py` can render the `affiliation` infobox slot.

A pre-step and not a wiki-resolution stage, for STU-488's reasons: it changes no
identity, and resolution is chained by `make golden`, which stays LLM-free by
construction.

Never fails a run: a book whose verdict cannot be obtained renders no slot at all,
loudly.
"""
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from wiki_creator import studio_io
from wiki_creator.entity_affiliation import (
    parse_affiliation_verdict,
    roster_rows,
)
from wiki_creator.roster import load_cache, render_roster, save_cache
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_SECONDS = 600


def contexts_by_entity(registry: Registry) -> dict[str, list[dict]]:
    """Per-PERSON context sentences with the chapter each came from.

    The chapter rides along because `select_affiliation_snippets` sorts by it.
    """
    contexts: dict[str, list[dict]] = {}
    for record in registry.entities:
        if record.entity_type != "PERSON":
            continue
        snippets = [
            {"text": mention.context.strip(), "chapter_id": mention.chapter_id}
            for mention in record.mentions
            if mention.context and mention.context.strip()
        ]
        if snippets:
            contexts[record.canonical_name] = snippets
    return contexts


def resolve_affiliation(rows: list[dict], book_title: str, cache_path: Path) -> dict[str, dict]:
    """Verified affiliation per character, from cache or one `studio run`.

    Never raises. Every failure path returns {} — every character then renders no
    `affiliation` slot, which is what an OPT slot with no value does.
    """
    cached = load_cache(cache_path, rows)
    if cached is not None:
        return cached
    # A verdict for another roster must not survive a failure below:
    # `wiki_preparation.load_affiliation_verdicts` is roster-blind and would
    # replay a stale artifact.
    Path(cache_path).unlink(missing_ok=True)

    item_input = {"book_title": book_title, "roster": render_roster(rows)}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "entity-affiliation-item", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        return _give_up("studio_cli_missing", rows)
    except subprocess.TimeoutExpired:
        return _give_up("studio_run_timeout", rows)
    finally:
        Path(input_path).unlink(missing_ok=True)

    if result.returncode != 0:
        return _give_up("studio_run_failed", rows)
    run_payload = studio_io.extract_first_json_object(result.stdout or "")
    if run_payload is None:
        return _give_up("studio_output_json_parse_error", rows)

    stage_output = studio_io.extract_stage_output_from_run_payload(
        run_payload, "entity-affiliation-item"
    )
    if stage_output is None:
        run_id = str(run_payload.get("id") or "").strip()
        if run_id:
            stage_output = studio_io.load_studio_stage_output(run_id, "entity-affiliation-item")
    if stage_output is None:
        return _give_up("studio_run_output_missing", rows)

    verdicts = parse_affiliation_verdict(stage_output, rows)
    save_cache(cache_path, rows, verdicts)
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-affiliation] WARNING: {error} — none of the {len(rows)} characters "
        "render an affiliation",
        file=sys.stderr,
    )
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Decide each character's faction for this book")
    parser.add_argument("--book", required=True, help="Path to the book YAML")
    args = parser.parse_args()

    book_cfg = yaml.safe_load(Path(args.book).read_text(encoding="utf-8")) or {}
    paths = book_paths_from_yaml(args.book)

    cache_path = paths.processing / "entity_affiliation.json"

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-affiliation] registry.json not found in {paths.processing} — "
            "no character renders an affiliation",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    lang_cfg = load_lang_config(book_language(book_cfg))
    markers = list(lang_cfg.get("affiliation_markers", []))
    if not markers:
        print(
            "[entity-affiliation] no `affiliation_markers` in this language's cue_words — "
            "no snippet can be selected, so no character renders an affiliation",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    contexts = contexts_by_entity(registry)
    persons = [
        {"canonical_name": record.canonical_name, "aliases": record.aliases}
        for record in registry.entities
        if record.entity_type == "PERSON" and record.canonical_name in contexts
    ]
    if not persons:
        print(
            "[entity-affiliation] no PERSON entity with context — nothing to decide",
            file=sys.stderr,
        )
        Path(cache_path).unlink(missing_ok=True)
        return

    rows = roster_rows(persons, contexts, markers)
    verdicts = resolve_affiliation(
        rows,
        book_title=str(book_cfg.get("title") or paths.processing.name),
        cache_path=cache_path,
    )

    print(
        f"[entity-affiliation] {len(verdicts)}/{len(rows)} characters have a faction; "
        "the rest render no slot",
        file=sys.stderr,
    )
    for name, verdict in sorted(verdicts.items()):
        print(f"[entity-affiliation]   {name}: {verdict['affiliation']}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create the agent prompt**

Create `.studio/agents/entity-affiliation.agent.yaml`:

```yaml
name: entity-affiliation
system_prompt: |
  Respond with ONLY a valid JSON object. No markdown fences, no explanation, no other text.

  You decide, for each character in a novel's roster, which faction they belong to
  at the END of this book.

  You receive input with:
  - book_title
  - roster: one block per character, formatted
    "## Name (also called: alias, alias)" followed by snippets from the book that
    mention that character

  Return exactly:
  {
    "affiliation": [ {"name": "...", "affiliation": "...", "quote": "..."} ]
  }

  "affiliation" is the faction's name, WRITTEN EXACTLY AS IT APPEARS IN YOUR QUOTE.
  "quote" is copied VERBATIM from a snippet shown above under THAT character's own
  "## " heading.

  A faction is a group a person can BELONG to and could leave: an army, an order,
  a guild, a rebellion, a kingdom's service, a criminal band.

  NOT a faction — never return these:
  - A species or race. "Human", "Elf", "Dwarf", "Faun", "Centaur" are what someone
    IS, not what they joined. Nobody defects from being human.
  - A family or bloodline. That is a relationship, not an allegiance.
  - A place. Living somewhere is not belonging to it.
  - A job or title held alone ("blacksmith", "king") with no group behind it.

  THE END OF THE BOOK IS WHAT COUNTS. A character who leaves the Empire to join the
  rebellion belongs to the rebellion. The latest snippets are shown first.

  List ONLY characters whose faction the snippets state. Every character you do not
  list renders nothing, which is the correct answer whenever the text shown does not
  settle it.

  THE TEST — do the snippets shown for THIS character say which group THEY belong to?

  A character who fights AGAINST a faction does not belong to it. A character who is
  captured by, hunted by, or bargains with a faction does not belong to it. A
  character present when a faction is discussed does not belong to it.
  "Eragon rode with the Varden against the Empire" names two factions and he belongs
  to ONE.

  NEVER list these:
  - A character whose allegiance you know because you have read this novel before.
    Your memory of the plot is not evidence. If the snippets shown do not say it, it
    is not here — this book may end before the change you remember.
  - An allegiance that is offered, refused, suspected, predicted, or feared. Only
    what is true of this character at the end of this book counts.
  - A character whose snippets show nothing about what they belong to. Leave them out.

  Grounding: the snippets are the only truth. Decide from them alone.

  WHEN IN DOUBT, LEAVE THE CHARACTER OUT. A wrong faction puts a character in the
  wrong army on a page nobody will reread. Rendering nothing is honest.

  Rules:
  - Never list a name that does not appear as a "## " heading in the roster
  - "quote" must be text you can find in a snippet under that character's own
    heading, character for character. A verdict whose quote is not there is discarded.
  - The faction name you return MUST appear inside the quote you cite, word for word.
    If your quote proves the allegiance without naming the group, find another quote
    or leave the character out.
  - Return {"affiliation": []} if the snippets settle nobody's faction
  - Do not return a string in place of the object
```

- [ ] **Step 5: Create the contract and pipeline**

Create `.studio/contracts/entity-affiliation-item.contract.yaml`:

```yaml
name: entity-affiliation-item
version: 1
schema:
  required_fields:
    - affiliation
# affiliation: list of {name: string, affiliation: string, quote: string} — the
# roster entries whose faction the snippets state.
# An empty list is valid and means the snippets settle nobody's faction; no
# character then renders the slot, which is what an OPT slot with no value does.
# Names absent from the roster, quotes absent from the snippets shown, and values
# absent from their own quote are discarded by the caller
# (scripts/entity_affiliation.py), not rejected here: a hallucinated verdict must
# not fail a run, it must render nothing.
```

Create `.studio/pipelines/entity-affiliation-item.pipeline.yaml`:

```yaml
name: entity-affiliation-item
description: Decide which faction each PERSON roster entry belongs to at the end of this book — one call per book
version: 1

stages:
  - name: entity-affiliation-item
    kind: analysis
    agent: entity-affiliation
    contract: entity-affiliation-item
    ralph:
      max_attempts: 3
    context:
      include:
        - input
```

- [ ] **Step 6: Run to verify they pass**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_affiliation.py -v
```

Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add scripts/entity_affiliation.py .studio/agents/entity-affiliation.agent.yaml \
        .studio/contracts/entity-affiliation-item.contract.yaml \
        .studio/pipelines/entity-affiliation-item.pipeline.yaml \
        tests/test_entity_affiliation.py
git commit -m "feat(stu-551): entity-affiliation pre-step

One studio run per book over the PERSON roster — the STU-529/539/488 shape, with
STU-488's asymmetry: every failure path renders no slot. affiliation is OPT with
no declared fallback, so a give-up costs an omitted slot, while a false verdict
puts a character in the wrong army and reads as fact.

The prompt refuses species, family, and place explicitly: FACTION's own
gliner_label asks for 'people, race, or order' and the taxonomy collects species,
so 'Human' is the failure this slot invites.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wire it — preparation, rendering, orchestrator

**Files:**
- Modify: `scripts/wiki_preparation.py` (add `load_affiliation_verdicts`; `build_entity_bundle` signature + body)
- Modify: `scripts/generate_wiki_pages.py:735-746`
- Modify: `run_wiki.py:92-96`
- Modify: `tests/test_generate_wiki_pages_binding.py:198` — **an existing assertion pins the inert behavior and WILL fail**
- Test: `tests/test_entity_affiliation.py` (modify — append)

**Interfaces:**
- Consumes: the verdict shape from Task 4; the artifact Task 5 writes.
- Produces: `load_affiliation_verdicts(processing_dir) -> dict[str, dict]`; `build_entity_bundle(..., affiliation_verdicts: dict[str, dict] | None = None)`.

The two wiring tests are the STU-512 lesson: *without them the whole feature was deletable with the suite green.*

- [ ] **Step 1: Write the failing wiring tests**

Append to `tests/test_entity_affiliation.py`:

```python
from scripts.generate_wiki_pages import _extracted_fact_value
from scripts.wiki_preparation import build_entity_bundle, load_affiliation_verdicts


def test_the_binder_renders_affiliation_from_the_batch_entity():
    assert _extracted_fact_value({"affiliation": "Varden"}, "affiliation", "fr") == "Varden"


def test_an_unstamped_entity_renders_no_affiliation():
    # OPT with no declared fallback: _bind_batch_fields omits a falsy value.
    assert _extracted_fact_value({}, "affiliation", "fr") is None
    assert _extracted_fact_value({"affiliation": ""}, "affiliation", "fr") is None


def test_preparation_stamps_affiliation_onto_the_batch_entity():
    bundle = build_entity_bundle(
        entity={"canonical_name": "Eragon", "type": "PERSON", "importance": "principal"},
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={},
        affiliation_verdicts={"Eragon": {"affiliation": "Varden", "quote": "x"}},
    )
    assert bundle["affiliation"] == "Varden"


def test_preparation_stamps_nothing_for_an_undecided_character():
    bundle = build_entity_bundle(
        entity={"canonical_name": "Murtagh", "type": "PERSON", "importance": "secondary"},
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={},
        affiliation_verdicts={},
    )
    assert bundle["affiliation"] is None


def test_load_affiliation_verdicts_degrades_on_an_absent_artifact(tmp_path):
    # A book that never ran the stage is not an error.
    assert load_affiliation_verdicts(tmp_path) == {}


def test_person_declares_the_affiliation_slot():
    from wiki_creator.page_templates import load_base_template
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["affiliation"]["provenance"] == "extracted-fact"
    assert slots["affiliation"]["obligation"] == "OPT"
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 \
  python -m pytest tests/test_entity_affiliation.py -v
```

Expected: FAIL — `ImportError: cannot import name 'load_affiliation_verdicts'`

- [ ] **Step 3: Render the slot**

In `scripts/generate_wiki_pages.py`, replace `_extracted_fact_value` (lines 735-746):

```python
def _extracted_fact_value(entity: dict, token: str, lang: str) -> str | None:
    """Value for an extracted-fact infobox token, sourced from facts the pipeline
    produced into the batch entity. None when the fact is absent (slot omitted).
    The specific `type` is a future slice."""
    if token == "titles":
        titles = [t for t in (entity.get("titles") or []) if t]
        return ", ".join(titles) if titles else None
    if token == "status":
        # MIN with a declared fallback: an unstamped entity renders `unknown`
        # rather than dropping the slot (STU-488).
        return status_label(entity.get("status"), lang)
    if token == "affiliation":
        # OPT with no declared fallback: an undecided character drops the slot
        # (STU-551). Plain text — no infobox slot carries a wikilink today.
        return (entity.get("affiliation") or "").strip() or None
    return None
```

- [ ] **Step 4: Stamp it at preparation**

In `scripts/wiki_preparation.py`, add after `load_status_verdicts` (line ~371):

```python
def load_affiliation_verdicts(processing_dir: Path) -> dict[str, dict]:
    """Per-character faction decided by the entity-affiliation pre-step (STU-551).

    Absent or unreadable artifact -> {} -> no character renders the slot. A book
    that never ran the stage is not an error.
    """
    path = Path(processing_dir) / "entity_affiliation.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    verdicts = payload.get("verdicts") if isinstance(payload, dict) else None
    return verdicts if isinstance(verdicts, dict) else {}
```

Add the parameter to `build_entity_bundle` (after `status_verdicts`, line ~386):

```python
    status_verdicts: dict[str, dict] | None = None,
    affiliation_verdicts: dict[str, dict] | None = None,
```

Add the field to the returned dict (after `"status"`, line ~403):

```python
        "affiliation": (affiliation_verdicts or {}).get(canonical_name, {}).get("affiliation"),
```

In `main`, beside the `status_verdicts` load (line ~614):

```python
    affiliation_verdicts = load_affiliation_verdicts(paths.processing)
    print(
        f"wiki-preparation: {len(affiliation_verdicts)} character affiliation verdict(s) loaded",
        file=sys.stderr,
    )
```

and thread it at the `build_entity_bundle` call site (line ~684):

```python
            status_verdicts=status_verdicts,
            affiliation_verdicts=affiliation_verdicts,
```

- [ ] **Step 5: Add the pre-step**

In `run_wiki.py`, in `PRE_STEPS["wiki-preparation"]` (line 92):

```python
    "wiki-preparation": [
        ["python", "scripts/entity_status.py", "--book"],
        ["python", "scripts/entity_affiliation.py", "--book"],
        ["python", "scripts/classify_relationships.py", "--book"],
        ["python", "scripts/build_event_layer.py", "--book"],
    ],
```

- [ ] **Step 6: Fix the assertion that pins the inert behavior**

`tests/test_generate_wiki_pages_binding.py:198` currently asserts the slot never renders. It is now wrong:

```python
def test_extracted_fact_value_titles_and_unknown():
    assert gwp._extracted_fact_value({"titles": ["Captain", "Duke"]}, "titles", "fr") == "Captain, Duke"
    assert gwp._extracted_fact_value({"titles": []}, "titles", "fr") is None
    assert gwp._extracted_fact_value({"affiliation": "Varden"}, "affiliation", "fr") == "Varden"
    assert gwp._extracted_fact_value({}, "affiliation", "fr") is None
```

- [ ] **Step 7: Run the full suite**

```bash
cd /home/arianeguay/dev/src/wiki-creator-stu-551
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 python -m pytest -q
```

Expected: all pass. Baseline before this branch was `1604 passed, 1 skipped`; this adds ~20.

- [ ] **Step 8: Verify the golden chain is untouched**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 make golden
```

Expected: PASS with **no golden diff**. `wiki_preparation` is not in the golden chain — if a golden moved, something was wired into resolution by mistake.

- [ ] **Step 9: Type-check**

```bash
PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551 mypy wiki_creator/
```

Expected: no new errors.

- [ ] **Step 10: Commit**

```bash
git add scripts/wiki_preparation.py scripts/generate_wiki_pages.py run_wiki.py \
        tests/test_entity_affiliation.py tests/test_generate_wiki_pages_binding.py
git commit -m "feat(stu-551): render the affiliation slot

The slot and its mediawiki row have been declared and inert since STU-504; this
is the branch that fills them. Two wiring tests pin it — the STU-512 lesson:
without them the whole feature is deletable with the suite green.

test_generate_wiki_pages_binding.py asserted the slot never renders. It pinned
the inert behavior, so it changes here.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Measure the stage — the ship gate

**No code. Precision is the metric: 0 false positives or it does not ship** (STU-488's bar).

STU-538 fired 340 times for 0 true positives and nobody knew for months, because nobody counted.

**Files:**
- Modify: `docs/superpowers/specs/2026-07-16-stu-551-affiliation-design.md` — append the results.

- [ ] **Step 1: Run the stage on Eragon**

Needs `registry.json`, which Task 1's re-extraction plus resolution produce.

```bash
cd /home/arianeguay/dev/src/wiki-creator-stu-551
export PYTHONPATH=/home/arianeguay/dev/src/wiki-creator-stu-551
python run_wiki.py --book library/christopher_paolini/inheritance/books/01_eragon.yaml \
  --only wiki-resolution   # if the pipeline is not already through resolution
python scripts/entity_affiliation.py \
  --book library/christopher_paolini/inheritance/books/01_eragon.yaml
```

Expected on stderr: `[entity-affiliation] N/62 characters have a faction`, then one line per verdict.

- [ ] **Step 2: Read the roster, then score**

**Read the verdicts before forming an expectation.** STU-488 predicted "Brom and Garrow die, everything else is a false positive" and was wrong on both halves: Garrow was not on the PERSON roster at all, and five more roster characters really are dead.

For each verdict, open the quote's chapter and check by hand:
- Is the faction real, and does the character belong to it (not fight it, not get captured by it)?
- Is it a faction, and not a species/family/place?
- Is it their allegiance at the **end** of the book?

- [ ] **Step 3: Run it on Narnia — the red-flag check**

```bash
python scripts/entity_affiliation.py \
  --book library/c_w_lewis/narnia/books/01-the_lion_the_witch_and_the_wardrobe.yaml
```

**A high yield here is a failure, not a success.** Narnia has no factions; it has species. `Sons of Adam`, `Daughters of Eve`, `Humans`, `Fauns` are obvious affiliation candidates and every one belongs to the `species` slot. If they show up, the agent prompt's species rule is not working.

- [ ] **Step 4: Record the numbers in the spec and the MR**

```markdown
## Measurement result (Task 6)

`01_eragon`: N/62 decided. Hand-checked: <N true, N false>.
`narnia`: N/M decided. <Species leakage: yes/no>

Precision: <N>. <Ship / do not ship.>
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-07-16-stu-551-affiliation-design.md
git commit -m "docs(stu-551): measured affiliation on eragon and narnia

<numbers>

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Update the ticket, CLAUDE.md, and file the follow-ups

**Files:**
- Modify: `CLAUDE.md` — a Gotchas entry.

- [ ] **Step 1: Add the CLAUDE.md entry**

In `## Gotchas`, beside the STU-488 entry:

```markdown
- Affiliation is a scalar, not a dated edge (STU-551): the `affiliation` slot is
  filled by one `studio run entity-affiliation-item` per book over the PERSON
  roster — the STU-488 shape, a pre-step to wiki-preparation so resolution stays
  LLM-free. The ticket asked for a **dated edge** and three measurements refused
  it. (1) Its own acceptance test — tome 3's faction on tome 3's page, tome 1's on
  tome 1's — is true **by construction** under a per-tome wiki, exactly as for
  `status`. (2) The intra-tome date is what STU-488 measured unbuildable: its
  `death` slot derived the chapter from the snippet its verdict quoted and got 3
  of 4 wrong, because the place where the text states a fact is not the place
  where the fact happens; a dated edge has no other date source. (3) There is no
  edge to date — `relationship_extraction.py` filters the co-occurrence graph to
  `type == "PERSON"` in hard code, so no PERSON↔ORG edge exists in any artifact.
  Snippet selection is **single-source** where `status` is two-source: nothing
  proves the *absence* of an affiliation, so there is no `alive`-analogue proved
  by acting late. Marker-bearing snippets, latest-first — the latest-first is what
  makes the scalar mean "end of tome" and absorbs an intra-tome switch without
  dating it. **A third rejection rule exists here that `status` does not need**:
  `status` returns an enum member, so verifying the quote verifies the verdict;
  `affiliation` returns a **name**, so the model can quote a real sentence and
  infer the wrong faction from it. The rendered value must appear in the quote,
  verbatim. Every failure path **omits the slot** (OPT, no declared fallback,
  unlike `status`'s `MIN`/`fallback: unknown`): a false affiliation puts a
  character in the wrong army on a page nobody will reread and reads as fact.
  `_normalize` is imported from `entity_status`, not reimplemented — its
  typographic folding is the `99a6a71` fix, without which every verdict quoted
  from dialogue is silently dropped.
  **The taxonomy does not hold factions, and this slot is grounded despite it**:
  `FACTION`'s `gliner_label` is `"people, race, or order"` and collects species
  (Narnia: `Humans`, `Fauns`, `Centaurs`), while `ORG`'s is `"kingdom, empire, or
  government"` and collects the real ones. That is why the prompt refuses species,
  family and place by name, and why a high yield on Narnia is a red flag.
```

- [ ] **Step 2: Update the Linear ticket**

STU-551 is titled "Faction change as a dated edge (affiliation slot)" and estimated 5 points for a model this plan does not build. Update the title to "Faction as a per-tome scalar (affiliation slot)", re-estimate, and replace the description's "What this needs" section with a pointer to the spec — the dated-edge premise is refuted, and leaving it in the ticket invites the next person to rebuild it.

- [ ] **Step 3: File the follow-ups the spec surfaced**

Four, all out of scope, all with a measurement behind them (spec §"Follow-ups this surfaces"):

1. **The taxonomy does not hold factions** — `FACTION` collects species, `ORG` collects factions, PERSON's `species` slot is declared and empty while Narnia's FACTION entities are exactly its values. Re-measure post-STU-560 first. `repo:wiki-creator`, `architecture`.
2. **Studio swallows a dead stage's stderr** — a python stage that dies at startup crashes the node CLI with `Error: write EPIPE` and reports nothing. Three runs during this design reported `EPIPE` where the cause was a one-line `ImportError`. `bug`.
3. **`pip install -e .` pins the main checkout** — any worktree runs its `scripts/` against `main`'s `wiki_creator/`. Loud here only because STU-560 added a symbol; the silent case (same signature, changed behavior) lets a worktree go green testing `main`'s code. CLAUDE.md mandates a worktree per task and does not mention it. `bug`.
4. **GLiNER's device is hardcoded** — [gliner_ner.py:89](wiki_creator/nlp/gliner_ner.py#L89), no config key, so concurrent runs OOM each other on one 6 GB GPU with no way to place them. Same shape as the coref device bug. `bug`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(stu-551): record the affiliation slot in CLAUDE.md

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| What this ticket becomes (scalar, not dated edge) | 4 (docstring), 8 (CLAUDE.md) |
| Architecture (pre-step, mirror of entity_status) | 5, 6 |
| Why not folded into entity-status | 5 (separate pipeline/agent/contract) |
| Snippet selection — single source, latest-first | 2, 4 |
| Verdict + three rejection rules | 4 |
| Rendering (plain text, no base.yaml change) | 6 |
| The unresolved choice (A vs B) | **1** |
| Testing (8 unit + 2 wiring) | 2, 4, 5, 6 |
| Measurement — the ship gate | 7 |
| Acceptance | 7 |
| Follow-ups | 8 |
| Pre-flight: A-reduced, extract the shared helpers | **3** (added, not in the spec) |

No gaps.

**Placeholder scan:** The `<A|B>`, `<date>`, and `<numbers>` in Tasks 1, 7 are outputs of measurements the task performs — the task states exactly what to run and what decides the value. Every code step carries complete code.

**Type consistency:** `normalize`, `has_marker`, `latest_first`, `render_roster`, `is_quoted`, `load_cache`, `save_cache` (Task 3, in `wiki_creator.roster`) are the names Tasks 4 and 5 import. `select_affiliation_snippets`, `roster_rows`, `parse_affiliation_verdict` (Task 4) are what Task 5 imports from `entity_affiliation`. `resolve_affiliation`, `contexts_by_entity` (Task 5) match the tests. `load_affiliation_verdicts`, `affiliation_verdicts=` (Task 6) match. The verdict shape `{name: {"affiliation": str, "quote": str}}` is consistent across Tasks 4, 5, 6.

**Two risks the plan cannot remove:**

1. Task 1 may choose **A**, which changes Task 4's `parse_affiliation_verdict` (a fourth rule) and Task 5's prompt (a roster of allowed names). Task 5 flags this. If A is chosen, re-read Task 4 before implementing it.
2. Task 3 moves code out of `entity_status.py`, which shipped yesterday. Its safety net is that `tests/test_entity_status.py` must pass **unedited** — a refactor that needs a test changed is not a refactor. If Task 3's review finds behavior moved, revert it and duplicate instead (the pre-flight's Option B); nothing downstream depends on the extraction beyond import paths.
