# Entity Status Per Tome Implementation Plan

> **Executed and superseded — kept as the record of what was planned.** Read the
> spec (`docs/superpowers/specs/2026-07-16-stu-488-entity-status-design.md`) and
> CLAUDE.md for the shipped behavior. Three things below are not what shipped:
>
> 1. **The `death` slot was removed** (`9399cbe`). Every step here that adds it,
>    stamps `death_chapter`, or derives a chapter from the quoting snippet is dead
>    text. The measurement showed the derived chapter is wrong for 3 of 4 verdicts —
>    the place where the text states a fact is not the place where the fact happens.
>    The in-universe death circumstance is STU-552.
> 2. **`_normalize` folds typographic characters** (`99a6a71`). The plan's verbatim
>    check rejected every verdict evidenced inside dialogue, because the EPUB carries
>    curly quotes and the model echoes straight ones.
> 3. **Task 5's `base.yaml` step names a `mediawiki` key that does not exist** — the
>    real path is `entity_types.PERSON.export.infobox_source` (STU-505). Task 6's
>    wiring test as written passes with the wiring deleted; it was rewritten during
>    execution. The measurement section's prediction ("Brom and Garrow") was
>    falsified: Garrow is typed ORG and is not on the roster.
>
> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill the declared-but-inert `status` infobox slot with a per-tome death verdict.

**Architecture:** A new `entity_status.py` pre-step to `wiki-preparation` sends the book's PERSON roster to one `studio run entity-status-item` call, verifies each verdict against the snippets it was shown, and caches the result keyed on the roster. `wiki_preparation.py` stamps `status`/`death_chapter` onto the batch entity beside `titles`; `generate_wiki_pages.py::_extracted_fact_value` renders them. A 1:1 mirror of `alias_adjudication` (STU-539), with the same fail-toward-nothing asymmetry.

**Tech Stack:** Python 3.11+, pytest, Studio CLI (`studio run`), YAML config in `.studio/` and `wiki_creator/templates/base.yaml`.

**Spec:** `docs/superpowers/specs/2026-07-16-stu-488-entity-status-design.md`

## Global Constraints

- **English only in code.** No French (or any non-English) string literal in a `.py`. Reader-facing text lives in `wiki_creator/templates/base.yaml` keyed by language and is read via `chrome_label`. (CLAUDE.md)
- **No hardcoded word lists.** Detection vocabulary lives in `wiki_creator/cue_words/<lang>.json`. No script may define a fallback vocabulary constant — an absent key degrades to an empty collection. (CLAUDE.md)
- **Every failure path renders `unknown`.** Missing CLI, timeout, unparseable JSON, empty reply, off-roster name, non-verbatim quote, out-of-enum status: each drops the verdict and warns. The run never fails. A false `deceased` kills a living character; a false `unknown` says "we don't know".
- **A verdict must quote text we showed the model.** These novels are in the model's training data; without a verbatim check, a verdict from its memory of the plot and one from this run's text are indistinguishable afterwards.
- **The enum is exactly:** `alive | deceased | missing | unknown | undead`. `unknown` is the declared fallback, not an error.
- **PERSON only.** `status` is declared on PERSON in `base.yaml`; no other type has the slot.
- **The series registry does not carry status.** No field on `EntityRecord`, no change to `Registry.accumulate`.
- **Goldens must not move.** The golden chain stops at `write-registry`; nothing in this plan touches a stage inside it. If `make golden` reds, the change is in the wrong place.
- Work in the existing worktree `/home/arianeguay/dev/src/wt/stu-488`, branch `arianedguay/stu-488-entity-status`.
- Commit trailer on every commit: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| Create `wiki_creator/entity_status.py` | Pure logic: enum, snippet selection, roster rendering, verdict parsing + verification, cache. No LLM, no Registry import. (As shipped it also reads `base.yaml` via `chrome_label` for the enum's labels — the "no I/O beyond the cache file" claim was never true.) |
| Create `scripts/entity_status.py` | Runner: read registry.json → roster → one `studio run` → write `entity_status.json`. Owns every failure path. |
| Create `.studio/agents/entity-status.agent.yaml` | The prompt. |
| Create `.studio/contracts/entity-status-item.contract.yaml` | Output contract (`status` field required). |
| Create `.studio/pipelines/entity-status-item.pipeline.yaml` | One-stage pipeline. |
| Create `tests/test_entity_status.py` | Unit tests over the pure module + the runner's failure paths. |
| Modify `wiki_creator/cue_words/en.json`, `fr.json` | Add `status_markers`. |
| Modify `wiki_creator/templates/base.yaml` | `death` infobox slot + mediawiki row + `chrome` labels for the enum and the death line. |
| Modify `scripts/generate_wiki_pages.py` | `_extracted_fact_value` gains `status`/`death` branches and a `lang` parameter. |
| Modify `scripts/wiki_preparation.py` | Stamp `status`/`death_chapter` onto the batch entity. |
| Modify `run_wiki.py` | Register the pre-step. |
| Modify `CLAUDE.md` | Record the gotcha. |

---

### Task 1: Status vocabulary + snippet selection

The two-source selection is the heart of the design: marker-bearing snippets prove `deceased`/`missing`/`undead`; the latest snippets prove `alive`. Both are sorted latest-first, because status is the state at the *end* of the tome, so the latest evidence decides.

**Files:**
- Create: `wiki_creator/entity_status.py`
- Modify: `wiki_creator/cue_words/en.json`, `wiki_creator/cue_words/fr.json`
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: `wiki_creator.chapters.chapter_number(key) -> int | None`
- Produces:
  - `STATUS_VALUES: tuple[str, ...]` = `("alive", "deceased", "missing", "unknown", "undead")`
  - `DEFAULT_STATUS: str` = `"unknown"`
  - `SNIPPETS_PER_ENTITY: int` = `5`, `SNIPPET_CHARS: int` = `300`
  - `select_status_snippets(snippets: list[dict], status_markers: list[str]) -> list[dict]` — snippets are `{"text": str, "chapter_id": str}`; returns the same shape, text truncated.
  - `roster_rows(entities: list[dict], contexts: dict[str, list[dict]], status_markers: list[str]) -> list[dict]` — rows are `{"name": str, "aliases": list[str], "snippets": list[dict]}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_status.py`:

```python
"""STU-488: per-tome entity status (the `status` / `death` infobox slots)."""
from wiki_creator.entity_status import (
    DEFAULT_STATUS,
    SNIPPETS_PER_ENTITY,
    STATUS_VALUES,
    roster_rows,
    select_status_snippets,
)

MARKERS = ["died", "killed", "dead"]


def _snippet(text, chapter):
    return {"text": text, "chapter_id": f"chapter_{chapter}"}


def test_status_enum_is_the_fandom_vocabulary():
    assert STATUS_VALUES == ("alive", "deceased", "missing", "unknown", "undead")
    assert DEFAULT_STATUS == "unknown"


def test_marker_bearing_snippets_come_before_plain_ones():
    snippets = [
        _snippet("Brom rode north with Eragon.", 5),
        _snippet("Brom died at dawn.", 2),
    ]
    chosen = select_status_snippets(snippets, MARKERS)
    assert chosen[0]["text"] == "Brom died at dawn."


def test_plain_snippets_fill_up_latest_first():
    # No marker anywhere: this is the `alive` evidence path — the character acts
    # late in the book, so the latest snippets are the ones that show it.
    snippets = [_snippet(f"Eragon walks in chapter {n}.", n) for n in (1, 40, 12)]
    chosen = select_status_snippets(snippets, MARKERS)
    assert [s["chapter_id"] for s in chosen] == ["chapter_40", "chapter_12", "chapter_1"]


def test_marker_snippets_are_also_latest_first():
    # Status is the state at the END of the tome, so the latest death evidence wins.
    snippets = [_snippet("He was killed early.", 2), _snippet("He was killed later.", 30)]
    chosen = select_status_snippets(snippets, MARKERS)
    assert chosen[0]["text"] == "He was killed later."


def test_selection_caps_at_five():
    snippets = [_snippet(f"Eragon walks {n}.", n) for n in range(20)]
    assert len(select_status_snippets(snippets, MARKERS)) == SNIPPETS_PER_ENTITY


def test_marker_snippets_do_not_starve_the_cap():
    # 3 markers + 2 plain fills exactly 5 — the alive-evidence path stays open
    # even when some markers are present.
    marked = [_snippet(f"Someone died {n}.", n) for n in (1, 2, 3)]
    plain = [_snippet(f"Eragon walks {n}.", n) for n in (10, 11, 12)]
    chosen = select_status_snippets(marked + plain, MARKERS)
    assert len(chosen) == 5
    assert sum(1 for s in chosen if "died" in s["text"]) == 3


def test_empty_markers_still_selects_latest():
    # cue_words with no `status_markers` key degrades to an empty list: no marker
    # selection, no crash, latest snippets only.
    snippets = [_snippet("Brom died at dawn.", 2), _snippet("Eragon walks.", 9)]
    chosen = select_status_snippets(snippets, [])
    assert chosen[0]["chapter_id"] == "chapter_9"


def test_snippet_text_is_truncated_but_the_chapter_survives():
    long_text = "Brom died. " + "x" * 500
    [chosen] = select_status_snippets([_snippet(long_text, 7)], MARKERS)
    assert len(chosen["text"]) == 300
    assert chosen["chapter_id"] == "chapter_7"


def test_markers_match_whole_words_only():
    # "killed" must not fire on "skilled": if it did, the chapter-1 snippet would
    # count as marker-bearing and outrank the chapter-9 one.
    snippets = [_snippet("Eragon is a skilled rider.", 1), _snippet("Eragon rides.", 9)]
    chosen = select_status_snippets(snippets, ["killed"])
    assert chosen[0]["chapter_id"] == "chapter_9"


def test_roster_rows_carry_name_aliases_and_snippets():
    entities = [{"canonical_name": "Brom", "aliases": ["the storyteller"]}]
    contexts = {"Brom": [_snippet("Brom died at dawn.", 2)]}
    [row] = roster_rows(entities, contexts, MARKERS)
    assert row["name"] == "Brom"
    assert row["aliases"] == ["the storyteller"]
    assert row["snippets"][0]["text"] == "Brom died at dawn."


def test_roster_row_for_an_entity_with_no_context_is_empty_not_missing():
    entities = [{"canonical_name": "Ghost", "aliases": []}]
    [row] = roster_rows(entities, {}, MARKERS)
    assert row["snippets"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki_creator.entity_status'`

- [ ] **Step 3: Write the module**

Create `wiki_creator/entity_status.py`:

```python
"""Decide whether a character is dead by the end of this tome.

The `status` infobox slot has been declared and inert since STU-504. Filling it
needs the one thing a regex cannot give: who a sentence is *about*. STU-538
measured that lesson at 340 fires and 0 true positives — a pattern matched in one
entity's context was credited to whichever entity happened to be paired with it.
"Eragon watched Brom die" holds a death marker in both characters' contexts and
kills exactly one of them.

So the marker vocabulary only **retrieves**: it picks which snippets the
classifier reads. The classifier decides. A marker missing from the vocabulary
means a death is never surfaced, which means `unknown` — the forgiving direction.

Every helper here fails toward `unknown`. The asymmetry is STU-539's: a false
`deceased` kills a living character on a page nobody will reread, while a false
`unknown` renders the slot's own declared fallback.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from wiki_creator.chapters import chapter_number

STATUS_VALUES = ("alive", "deceased", "missing", "unknown", "undead")
DEFAULT_STATUS = "unknown"

SNIPPETS_PER_ENTITY = 5
SNIPPET_CHARS = 300

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: object) -> str:
    return _WHITESPACE_RE.sub(" ", str(text or "")).strip().casefold()


def _has_marker(text: str, status_markers: list[str]) -> bool:
    return any(
        re.search(r"\b" + re.escape(marker) + r"\b", text, re.IGNORECASE)
        for marker in status_markers
        if marker
    )


def _latest_first(snippets: list[dict]) -> list[dict]:
    """Sorted by chapter, latest first. An unnumbered chapter (``Prologue``)
    sorts earliest. Stable, so same-chapter snippets keep source order."""
    return sorted(
        snippets,
        key=lambda snippet: chapter_number(snippet.get("chapter_id")) or 0,
        reverse=True,
    )


def select_status_snippets(snippets: list[dict], status_markers: list[str]) -> list[dict]:
    """Up to ``SNIPPETS_PER_ENTITY`` snippets, marker-bearing first, then latest.

    Two verdicts need two kinds of evidence. `deceased`/`missing`/`undead` are
    proved by a sentence that says so — the marker-bearing snippets. `alive` is
    proved by the character acting late in the book — the latest snippets. Both
    groups are latest-first: status is the state at the end of the tome, so the
    latest evidence decides.

    Snippets are ``{"text": str, "chapter_id": str}``; the chapter rides along
    because the caller derives the `death` slot from it, never from the model.
    """
    marked, plain = [], []
    for snippet in snippets or []:
        text = str(snippet.get("text") or "")
        (marked if _has_marker(text, status_markers or []) else plain).append(snippet)

    chosen = _latest_first(marked)[:SNIPPETS_PER_ENTITY]
    chosen += _latest_first(plain)[: SNIPPETS_PER_ENTITY - len(chosen)]
    return [
        {"text": str(snippet.get("text") or "")[:SNIPPET_CHARS], "chapter_id": snippet.get("chapter_id")}
        for snippet in chosen
    ]


def roster_rows(
    entities: list[dict], contexts: dict[str, list[dict]], status_markers: list[str]
) -> list[dict]:
    """One row per PERSON entity — the roster the classifier sees.

    ``contexts`` maps canonical_name -> that entity's snippets.
    """
    return [
        {
            "name": entity["canonical_name"],
            "aliases": sorted(a for a in (entity.get("aliases") or []) if a),
            "snippets": select_status_snippets(
                contexts.get(entity["canonical_name"], []), status_markers
            ),
        }
        for entity in entities
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q`
Expected: PASS (11 passed)

- [ ] **Step 5: Add the marker vocabulary**

In `wiki_creator/cue_words/en.json`, add a top-level key (keep the file's existing key order style — append near the other detection vocabularies):

```json
  "status_markers": [
    "died", "dies", "die", "dying", "dead", "death", "killed", "kill", "slain",
    "slew", "murdered", "perished", "corpse", "grave", "buried", "funeral",
    "missing", "vanished", "disappeared", "undead", "revived", "resurrected"
  ],
```

In `wiki_creator/cue_words/fr.json`:

```json
  "status_markers": [
    "mort", "morte", "morts", "mourut", "meurt", "mourir", "mourant",
    "tué", "tuée", "tuer", "assassiné", "assassinée", "cadavre", "tombe",
    "enterré", "enterrée", "funérailles", "périt", "périr",
    "disparu", "disparue", "disparaît", "ressuscité", "revenant"
  ],
```

- [ ] **Step 6: Verify the lang packs still validate**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/ -q -k "lang or cue"`
Expected: PASS. (`status_markers` is a new optional key; `REQUIRED_KEYS` in `wiki_creator/lang.py` is not touched — a language pack without it degrades to no marker selection, per the Global Constraints.)

- [ ] **Step 7: Commit**

```bash
cd /home/arianeguay/dev/src/wt/stu-488
git add wiki_creator/entity_status.py tests/test_entity_status.py wiki_creator/cue_words/en.json wiki_creator/cue_words/fr.json
git commit -m "feat(entity-status): select the snippets a status verdict can be read from (STU-488)

The marker vocabulary retrieves; it never decides. STU-538 measured what
happens when a pattern is the verdict: 340 fires, 0 true positives.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Roster rendering, verdict verification, cache

The verbatim check and the `death` chapter are the same lookup: the snippet that contains the quote is both the proof and the date. A quote found in no snippet has no snippet, so it has no verdict.

**Files:**
- Modify: `wiki_creator/entity_status.py`
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: `STATUS_VALUES`, `DEFAULT_STATUS`, `_normalize`, `roster_rows` (Task 1)
- Produces:
  - `render_roster(rows: list[dict]) -> str`
  - `parse_status_verdict(payload: object, rows: list[dict]) -> dict[str, dict]` — maps name -> `{"status": str, "quote": str, "chapter": int | None}`. Names absent from the result are `unknown`.
  - `load_cached_status(path: Path | str, rows: list[dict]) -> dict[str, dict] | None`
  - `save_status_cache(path: Path | str, rows: list[dict], verdicts: dict[str, dict]) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_status.py`:

```python
import json

from wiki_creator.entity_status import (
    load_cached_status,
    parse_status_verdict,
    render_roster,
    save_status_cache,
)

BROM_QUOTE = "Brom's chest rose one last time, and then was still."


def _rows():
    return [
        {
            "name": "Brom",
            "aliases": ["the storyteller"],
            "snippets": [{"text": BROM_QUOTE, "chapter_id": "chapter_38"}],
        },
        {
            "name": "Eragon",
            "aliases": [],
            "snippets": [{"text": "Eragon rode on alone.", "chapter_id": "chapter_59"}],
        },
    ]


def _verdict(**overrides):
    entry = {"name": "Brom", "status": "deceased", "quote": BROM_QUOTE}
    entry.update(overrides)
    return {"status": [entry]}


def test_render_roster_shows_names_aliases_and_snippet_text():
    rendered = render_roster(_rows())
    assert "## Brom (also called: the storyteller)" in rendered
    assert f"- {BROM_QUOTE}" in rendered
    assert "## Eragon" in rendered


def test_render_roster_never_shows_the_chapter():
    # The chapter is derived by code from the quoted snippet. Showing it would
    # invite the model to report one instead of quoting.
    assert "chapter_38" not in render_roster(_rows())


def test_a_verified_deceased_verdict_carries_the_quoted_snippets_chapter():
    verdicts = parse_status_verdict(_verdict(), _rows())
    assert verdicts["Brom"]["status"] == "deceased"
    assert verdicts["Brom"]["chapter"] == 38


def test_a_json_string_payload_is_parsed():
    verdicts = parse_status_verdict(json.dumps(_verdict()), _rows())
    assert verdicts["Brom"]["status"] == "deceased"


def test_a_quote_not_verbatim_in_that_entitys_snippets_is_rejected():
    # The model has read this novel. Without the check, a verdict from its memory
    # of the plot and one from this run's text are indistinguishable afterwards.
    verdicts = parse_status_verdict(_verdict(quote="Brom died at Farthen Dur."), _rows())
    assert verdicts == {}


def test_a_quote_from_another_entitys_snippets_is_rejected():
    # "Eragon watched Brom die" is in BOTH characters' contexts and kills one.
    # A verdict must be grounded in the snippets shown for its OWN entity.
    verdicts = parse_status_verdict(
        _verdict(name="Eragon", quote=BROM_QUOTE), _rows()
    )
    assert verdicts == {}


def test_quote_matching_ignores_whitespace_and_case():
    verdicts = parse_status_verdict(
        _verdict(quote="  BROM'S CHEST ROSE   one last time,\nand then was still. "), _rows()
    )
    assert verdicts["Brom"]["status"] == "deceased"


def test_a_name_off_the_roster_is_rejected():
    verdicts = parse_status_verdict(_verdict(name="Durza"), _rows())
    assert verdicts == {}


def test_a_status_outside_the_enum_is_rejected():
    verdicts = parse_status_verdict(_verdict(status="martyred"), _rows())
    assert verdicts == {}


def test_an_explicit_unknown_verdict_is_dropped_not_stored():
    # `unknown` is the absence of a verdict, not a verdict. Storing it would make
    # the cache claim the model ruled on an entity it did not.
    verdicts = parse_status_verdict(_verdict(status="unknown", quote=BROM_QUOTE), _rows())
    assert verdicts == {}


def test_an_empty_quote_is_rejected():
    verdicts = parse_status_verdict(_verdict(quote=""), _rows())
    assert verdicts == {}


def test_alive_needs_a_quote_too():
    verdicts = parse_status_verdict(
        {"status": [{"name": "Eragon", "status": "alive", "quote": "Eragon rode on alone."}]},
        _rows(),
    )
    assert verdicts["Eragon"]["status"] == "alive"


def test_only_deceased_carries_a_death_chapter():
    # The slot's label is "Died". `missing` and `undead` have no death chapter.
    verdicts = parse_status_verdict(
        {"status": [{"name": "Eragon", "status": "alive", "quote": "Eragon rode on alone."}]},
        _rows(),
    )
    assert verdicts["Eragon"]["chapter"] is None


def test_a_deceased_verdict_quoted_from_an_unnumbered_chapter_keeps_its_status():
    rows = [{"name": "Brom", "aliases": [], "snippets": [{"text": BROM_QUOTE, "chapter_id": "Prologue"}]}]
    verdicts = parse_status_verdict(_verdict(), rows)
    assert verdicts["Brom"]["status"] == "deceased"
    assert verdicts["Brom"]["chapter"] is None


def test_unparseable_payloads_verdict_nothing():
    for payload in ["not json", None, [], {"merge": []}, {"status": "deceased"}, 42]:
        assert parse_status_verdict(payload, _rows()) == {}


def test_a_malformed_entry_does_not_sink_its_neighbours():
    payload = {
        "status": [
            "garbage",
            {"name": "Brom", "status": "deceased", "quote": BROM_QUOTE},
        ]
    }
    assert parse_status_verdict(payload, _rows())["Brom"]["status"] == "deceased"


def test_cache_round_trips(tmp_path):
    rows, verdicts = _rows(), {"Brom": {"status": "deceased", "quote": BROM_QUOTE, "chapter": 38}}
    path = tmp_path / "entity_status.json"
    save_status_cache(path, rows, verdicts)
    assert load_cached_status(path, rows) == verdicts


def test_a_changed_roster_misses_the_cache(tmp_path):
    # WIKI_MAX_CHAPTERS and every upstream extraction fix change the roster. A
    # verdict returned for a different roster must not be replayed onto it —
    # STU-539's premise was measured false against a 5-chapter extraction.
    path = tmp_path / "entity_status.json"
    save_status_cache(path, _rows(), {"Brom": {"status": "deceased", "quote": BROM_QUOTE, "chapter": 38}})
    other = _rows()
    other[0]["snippets"] = [{"text": "Brom rode north.", "chapter_id": "chapter_2"}]
    assert load_cached_status(path, other) is None


def test_a_missing_or_corrupt_cache_is_a_miss_not_a_crash(tmp_path):
    assert load_cached_status(tmp_path / "nope.json", _rows()) is None
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not json", encoding="utf-8")
    assert load_cached_status(corrupt, _rows()) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q`
Expected: FAIL — `ImportError: cannot import name 'render_roster' from 'wiki_creator.entity_status'`

- [ ] **Step 3: Write the implementation**

Append to `wiki_creator/entity_status.py`:

```python
def render_roster(rows: list[dict]) -> str:
    """The roster block the classifier reads. Text only — the chapter is derived
    by the caller from the snippet the verdict quotes, never reported by the model."""
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


def _quoted_snippet(quote: str, snippets: list[dict]) -> dict | None:
    """The entity's own snippet holding ``quote`` verbatim, or None.

    Verification and dating are one lookup: the snippet that proves the verdict
    is the snippet that dates it.
    """
    needle = _normalize(quote)
    if not needle:
        return None
    for snippet in snippets:
        if needle in _normalize(snippet.get("text")):
            return snippet
    return None


def parse_status_verdict(payload: object, rows: list[dict]) -> dict[str, dict]:
    """Map the classifier's reply to verified verdicts, keyed by roster name.

    A name absent from the result is `unknown`; unparseable input verdicts
    nothing. A verdict survives only when its name is on the roster, its status
    is in the enum and is not `unknown`, and its quote is verbatim in **that
    entity's own** snippets. The model has read these novels: without the quote
    check, a verdict from its memory of the plot and one from this run's text
    are indistinguishable afterwards.
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            return {}
    if not isinstance(payload, dict):
        return {}
    entries = payload.get("status")
    if not isinstance(entries, list):
        return {}

    rows_by_name = {row["name"]: row for row in rows}
    verdicts: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        status = str(entry.get("status", "")).strip().lower()
        quote = str(entry.get("quote", "") or "").strip()
        row = rows_by_name.get(name)
        if row is None or name in verdicts:
            continue
        if status not in STATUS_VALUES or status == DEFAULT_STATUS:
            continue
        snippet = _quoted_snippet(quote, row["snippets"])
        if snippet is None:
            continue
        verdicts[name] = {
            "status": status,
            "quote": quote,
            "chapter": chapter_number(snippet.get("chapter_id")) if status == "deceased" else None,
        }
    return verdicts


def load_cached_status(path: Path | str, rows: list[dict]) -> dict[str, dict] | None:
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


def save_status_cache(path: Path | str, rows: list[dict], verdicts: dict[str, dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"roster": rows, "verdicts": verdicts}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q`
Expected: PASS (30 passed)

- [ ] **Step 5: Type-check**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && mypy wiki_creator/entity_status.py`
Expected: `Success: no issues found in 1 source file`

- [ ] **Step 6: Commit**

```bash
cd /home/arianeguay/dev/src/wt/stu-488
git add wiki_creator/entity_status.py tests/test_entity_status.py
git commit -m "feat(entity-status): verify a verdict against the snippets we showed (STU-488)

Verification and dating are one lookup: the snippet that proves the
verdict dates it. A quote we never showed has no snippet, so no verdict.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The Studio stage (agent, contract, pipeline)

**Files:**
- Create: `.studio/agents/entity-status.agent.yaml`
- Create: `.studio/contracts/entity-status-item.contract.yaml`
- Create: `.studio/pipelines/entity-status-item.pipeline.yaml`

**Interfaces:**
- Consumes: the roster string from `render_roster` (Task 2), passed as the `roster` input field.
- Produces: a pipeline named `entity-status-item`, invoked as
  `studio run entity-status-item --input-file <yaml> --json`, whose stage output is
  `{"status": [{"name", "status", "quote"}]}` — the payload `parse_status_verdict` consumes.

- [ ] **Step 1: Write the agent**

Create `.studio/agents/entity-status.agent.yaml`:

```yaml
name: entity-status
system_prompt: |
  Respond with ONLY a valid JSON object. No markdown fences, no explanation, no other text.

  You decide, for each character in a novel's roster, whether they are alive at the
  end of this book.

  You receive input with:
  - book_title
  - roster: one block per character, formatted
    "## Name (also called: alias, alias)" followed by snippets from the book that
    mention that character

  Return exactly:
  {
    "status": [ {"name": "...", "status": "...", "quote": "..."} ]
  }

  "status" is exactly one of: alive, deceased, missing, undead
  "quote" is copied VERBATIM from a snippet shown above under THAT character's own
  "## " heading.

  List ONLY characters whose status the snippets state. Every character you do not
  list is recorded as unknown, which is the correct answer whenever the text shown
  does not settle it.

  THE TEST — do the snippets shown for THIS character state what became of them?

  - deceased: a snippet shows this character dying or dead.
  - missing: a snippet shows this character vanishing, with their fate left open.
  - undead: a snippet shows this character dead and still acting.
  - alive: a snippet shows this character acting, and no snippet shows them dead.

  WHO THE SENTENCE IS ABOUT IS THE WHOLE QUESTION.
  "Eragon watched Brom die" appears in the snippets of BOTH characters. It makes
  Brom deceased. It says nothing about Eragon except that he was there.
  A character who witnesses, mourns, avenges, buries, or is threatened with death
  is not dead. A character who kills is not dead.

  NEVER list these:
  - A character whose fate you know because you have read this novel before. Your
    memory of the plot is not evidence. If the snippets shown do not say it, it is
    not here — this book may end before the death you remember.
  - A death that is feared, predicted, dreamt, threatened, or told as a story about
    someone else. Only what happens to this character in this book counts.
  - A character whose snippets show nothing about their fate. Leave them out.

  Grounding: the snippets are the only truth. Decide from them alone.

  WHEN IN DOUBT, LEAVE THE CHARACTER OUT. Do not list a character you are unsure
  about. A wrong "deceased" kills a living character on a page nobody will reread.
  A missing verdict renders "unknown", which is honest.

  Rules:
  - Never list a name that does not appear as a "## " heading in the roster
  - "quote" must be text you can find in a snippet under that character's own
    heading, character for character. A verdict whose quote is not there is discarded.
  - Return {"status": []} if the snippets settle nobody's fate
  - Do not return a string in place of the object
```

- [ ] **Step 2: Write the contract**

Create `.studio/contracts/entity-status-item.contract.yaml`:

```yaml
name: entity-status-item
version: 1
schema:
  required_fields:
    - status
# status: list of {name: string, status: string, quote: string} — the roster
# entries whose fate the snippets state.
# An empty list is valid and means the snippets settle nobody's fate; every
# character then renders the slot's declared fallback, `unknown`.
# Names absent from the roster, statuses outside the enum, and quotes absent from
# the snippets shown are discarded by the caller (scripts/entity_status.py), not
# rejected here: a hallucinated verdict must not fail a run, it must render unknown.
```

- [ ] **Step 3: Write the pipeline**

Create `.studio/pipelines/entity-status-item.pipeline.yaml`:

```yaml
name: entity-status-item
description: Decide which PERSON roster entries are dead by the end of this book — one call per book
version: 1

stages:
  - name: entity-status-item
    kind: analysis
    agent: entity-status
    contract: entity-status-item
    ralph:
      max_attempts: 3
    context:
      include:
        - input
```

- [ ] **Step 4: Verify the YAML parses and the names line up**

Run:
```bash
cd /home/arianeguay/dev/src/wt/stu-488 && python - <<'PY'
import yaml
from pathlib import Path
pipe = yaml.safe_load(Path(".studio/pipelines/entity-status-item.pipeline.yaml").read_text())
agent = yaml.safe_load(Path(".studio/agents/entity-status.agent.yaml").read_text())
contract = yaml.safe_load(Path(".studio/contracts/entity-status-item.contract.yaml").read_text())
stage = pipe["stages"][0]
assert stage["agent"] == agent["name"], (stage["agent"], agent["name"])
assert stage["contract"] == contract["name"], (stage["contract"], contract["name"])
assert contract["schema"]["required_fields"] == ["status"]
print("OK")
PY
```
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /home/arianeguay/dev/src/wt/stu-488
git add .studio/agents/entity-status.agent.yaml .studio/contracts/entity-status-item.contract.yaml .studio/pipelines/entity-status-item.pipeline.yaml
git commit -m "feat(entity-status): the classifier that reads who the sentence is about (STU-488)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The runner pre-step

Owns every failure path. The registry is the source: `Mention` carries both `chapter_id` and `context`, which is exactly the roster + contexts + chapters this needs, from one artifact already on disk and already read by the sibling pre-step `classify_relationships.py`.

**Files:**
- Create: `scripts/entity_status.py`
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: `wiki_creator.entity_status.{roster_rows, render_roster, parse_status_verdict, load_cached_status, save_status_cache}` (Tasks 1–2); `wiki_creator.registry.Registry.load_from_processing`; `wiki_creator.paths.book_paths_from_yaml`; `wiki_creator.lang.{book_language, load_lang_config}`; `wiki_creator.studio_io`.
- Produces:
  - `contexts_by_entity(registry) -> dict[str, list[dict]]`
  - `resolve_status(rows, book_title, cache_path) -> dict[str, dict]` — never raises; returns `{}` on any failure.
  - The artifact `processing_output/<slug>/entity_status.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_status.py`:

```python
from unittest.mock import patch

from scripts.entity_status import contexts_by_entity, resolve_status
from wiki_creator.registry import EntityRecord, Mention, Registry


def _registry():
    return Registry(entities=[
        EntityRecord(
            entity_id="brom",
            canonical_name="Brom",
            entity_type="PERSON",
            aliases=["the storyteller"],
            mentions=[
                Mention(surface="Brom", chapter_id="chapter_38", context=BROM_QUOTE),
                Mention(surface="Brom", chapter_id="chapter_2", context=None),
                Mention(surface="Brom", chapter_id="chapter_2", context="   "),
            ],
        ),
        EntityRecord(
            entity_id="tronjheim",
            canonical_name="Tronjheim",
            entity_type="PLACE",
            mentions=[Mention(surface="Tronjheim", chapter_id="chapter_40", context="The city stood.")],
        ),
    ])


def test_contexts_come_from_person_mentions_with_their_chapter():
    contexts = contexts_by_entity(_registry())
    assert contexts["Brom"] == [{"text": BROM_QUOTE, "chapter_id": "chapter_38"}]


def test_non_person_entities_have_no_context():
    # `status` is declared on PERSON only; no other type has the slot.
    assert "Tronjheim" not in contexts_by_entity(_registry())


def test_every_studio_failure_leaves_the_roster_unknown(tmp_path):
    # Missing CLI, timeout, non-zero exit, unparseable output, missing stage
    # output: each renders `unknown`, which is the slot's declared fallback.
    # A false `deceased` kills a living character on a page nobody will reread.
    for error in [
        FileNotFoundError(),
        __import__("subprocess").TimeoutExpired(cmd="studio", timeout=1),
    ]:
        with patch("scripts.entity_status.subprocess.run", side_effect=error):
            assert resolve_status(_rows(), "Eragon", tmp_path / "s.json") == {}

    class _Result:
        returncode = 1
        stdout = ""
        stderr = "boom"

    with patch("scripts.entity_status.subprocess.run", return_value=_Result()):
        assert resolve_status(_rows(), "Eragon", tmp_path / "s.json") == {}

    class _Garbage:
        returncode = 0
        stdout = "not json at all"
        stderr = ""

    with patch("scripts.entity_status.subprocess.run", return_value=_Garbage()):
        assert resolve_status(_rows(), "Eragon", tmp_path / "s.json") == {}


def test_a_failed_run_is_not_cached(tmp_path):
    # Caching a failure would make the next run replay it silently.
    cache = tmp_path / "s.json"
    with patch("scripts.entity_status.subprocess.run", side_effect=FileNotFoundError()):
        resolve_status(_rows(), "Eragon", cache)
    assert not cache.exists()


def test_a_successful_verdict_is_cached_and_replayed(tmp_path):
    cache = tmp_path / "s.json"
    stage_output = {"status": [{"name": "Brom", "status": "deceased", "quote": BROM_QUOTE}]}

    class _Ok:
        returncode = 0
        stdout = json.dumps({"id": "run-1", "stages": {"entity-status-item": {"output": stage_output}}})
        stderr = ""

    with patch("scripts.entity_status.subprocess.run", return_value=_Ok()) as run:
        first = resolve_status(_rows(), "Eragon", cache)
    assert first["Brom"]["status"] == "deceased"
    assert first["Brom"]["chapter"] == 38

    with patch("scripts.entity_status.subprocess.run") as run:
        second = resolve_status(_rows(), "Eragon", cache)
    run.assert_not_called()
    assert second == first
```

Note: `_Ok.stdout` mirrors whatever `studio_io.extract_stage_output_from_run_payload` accepts. Before writing the implementation, read `wiki_creator/studio_io.py` and shape this fixture to that function's real contract — if the run-payload shape differs, fix the fixture, not the helper.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.entity_status'`

- [ ] **Step 3: Write the runner**

Create `scripts/entity_status.py`:

```python
#!/usr/bin/env python3
"""Pre-step: entity-status — is each character alive at the end of this book?

Usage:
    python scripts/entity_status.py --book library/.../book.yaml

Input:  processing_output/<slug>/registry.json
Output: processing_output/<slug>/entity_status.json

Runs before wiki-preparation, which stamps the verdict onto the batch entity so
`generate_wiki_pages.py` can render the `status` / `death` infobox slots.

It is a pre-step and not a wiki-resolution stage on purpose. `alias-adjudication`
sits inside resolution because it changes identity — entity-classification reads
its output. This changes no identity; it only decorates the batch entity. And
resolution is chained by `make golden`, which stays LLM-free by construction.

Never fails a run: a book whose verdict cannot be obtained renders `unknown` for
every character, loudly.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from wiki_creator import studio_io
from wiki_creator.entity_status import (
    load_cached_status,
    parse_status_verdict,
    render_roster,
    roster_rows,
    save_status_cache,
)
from wiki_creator.lang import book_language, load_lang_config
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_SECONDS = 600


def contexts_by_entity(registry: Registry) -> dict[str, list[dict]]:
    """Per-PERSON context sentences with the chapter each came from.

    The chapter rides along because the `death` slot is derived from the snippet
    the verdict quotes — the model is never asked for a chapter.
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


def resolve_status(rows: list[dict], book_title: str, cache_path: Path) -> dict[str, dict]:
    """Verified status per character, from cache or one `studio run`.

    Never raises. Every failure path returns {} — every character then renders
    the slot's declared fallback, `unknown`.
    """
    cached = load_cached_status(cache_path, rows)
    if cached is not None:
        return cached

    item_input = {"book_title": book_title, "roster": render_roster(rows)}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "entity-status-item", "--input-file", input_path, "--json"]
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

    stage_output = studio_io.extract_stage_output_from_run_payload(run_payload, "entity-status-item")
    if stage_output is None:
        run_id = str(run_payload.get("id") or "").strip()
        if run_id:
            stage_output = studio_io.load_studio_stage_output(run_id, "entity-status-item")
    if stage_output is None:
        return _give_up("studio_run_output_missing", rows)

    verdicts = parse_status_verdict(stage_output, rows)
    save_status_cache(cache_path, rows, verdicts)
    return verdicts


def _give_up(error: str, rows: list[dict]) -> dict[str, dict]:
    print(
        f"[entity-status] WARNING: {error} — all {len(rows)} characters stay `unknown`",
        file=sys.stderr,
    )
    return {}


def main() -> None:
    parser = argparse.ArgumentParser(description="Decide each character's status for this book")
    parser.add_argument("--book", required=True, help="Path to the book YAML")
    args = parser.parse_args()

    book_cfg = yaml.safe_load(Path(args.book).read_text(encoding="utf-8")) or {}
    paths = book_paths_from_yaml(args.book)

    registry = Registry.load_from_processing(paths.processing)
    if registry is None:
        print(
            f"[entity-status] registry.json not found in {paths.processing} — "
            "every character stays `unknown`",
            file=sys.stderr,
        )
        return

    lang_cfg = load_lang_config(book_language(book_cfg))
    status_markers = list(lang_cfg.get("status_markers", []))
    if not status_markers:
        print(
            "[entity-status] no `status_markers` in this language's cue_words — "
            "selecting the latest snippets only",
            file=sys.stderr,
        )

    contexts = contexts_by_entity(registry)
    persons = [
        {"canonical_name": record.canonical_name, "aliases": record.aliases}
        for record in registry.entities
        if record.entity_type == "PERSON" and record.canonical_name in contexts
    ]
    if not persons:
        print("[entity-status] no PERSON entity with context — nothing to decide", file=sys.stderr)
        return

    rows = roster_rows(persons, contexts, status_markers)
    verdicts = resolve_status(
        rows,
        book_title=str(book_cfg.get("title") or paths.processing.name),
        cache_path=paths.processing / "entity_status.json",
    )

    decided = {name: v["status"] for name, v in verdicts.items()}
    print(
        f"[entity-status] {len(decided)}/{len(rows)} characters decided "
        f"({sum(1 for s in decided.values() if s == 'deceased')} deceased); "
        f"the rest render `unknown`",
        file=sys.stderr,
    )
    for name, verdict in sorted(verdicts.items()):
        chapter = f" (chapter {verdict['chapter']})" if verdict["chapter"] is not None else ""
        print(f"[entity-status]   {name}: {verdict['status']}{chapter}", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q`
Expected: PASS (36 passed)

If `test_a_successful_verdict_is_cached_and_replayed` fails on the `_Ok.stdout` shape, fix the fixture to match `studio_io.extract_stage_output_from_run_payload`'s real contract — do not change the helper.

- [ ] **Step 5: Commit**

```bash
cd /home/arianeguay/dev/src/wt/stu-488
git add scripts/entity_status.py tests/test_entity_status.py
git commit -m "feat(entity-status): one call per book over the PERSON roster (STU-488)

Every failure path renders \`unknown\`. A false \`deceased\` kills a living
character on a page nobody will reread; a false \`unknown\` is honest.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Rendering — the `death` slot, the labels, the binder

**Files:**
- Modify: `wiki_creator/templates/base.yaml` (PERSON `mediawiki` source ~line 44, PERSON `infobox` list ~line 54, `chrome` ~line 368)
- Modify: `wiki_creator/entity_status.py`
- Modify: `scripts/generate_wiki_pages.py:733-760` (`_extracted_fact_value`, `_bind_batch_fields`)
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: `STATUS_VALUES`, `DEFAULT_STATUS` (Task 1); `wiki_creator.page_templates.chrome_label`.
- Produces:
  - `status_label(status: str | None, lang: str) -> str` — the localized enum label; an absent/unknown status renders the `unknown` label.
  - `death_label(chapter: int | None, lang: str) -> str | None` — `None` when chapter is `None`.
  - Batch entity keys read by the binder: `entity["status"]` (enum string) and `entity["death_chapter"]` (int | None).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_status.py`:

```python
from scripts.generate_wiki_pages import _extracted_fact_value
from wiki_creator.entity_status import death_label, status_label
from wiki_creator.page_templates import load_base_template


def test_every_enum_value_has_a_label_in_both_languages():
    # No French string literal may live in a .py — the labels are data.
    chrome = load_base_template()["chrome"]
    for status in STATUS_VALUES:
        entry = chrome[f"status_{status}"]
        assert entry["fr"] and entry["en"]


def test_status_label_is_localized():
    assert status_label("deceased", "en") == "Deceased"
    assert status_label("deceased", "fr") == "Décédé"


def test_an_absent_status_renders_the_declared_fallback():
    # base.yaml declares `fallback: unknown` on the slot; MIN means it renders.
    assert status_label(None, "en") == status_label("unknown", "en")
    assert status_label("", "en") == status_label("unknown", "en")


def test_death_label_carries_the_chapter():
    assert "12" in death_label(12, "en")
    assert "12" in death_label(12, "fr")


def test_death_label_is_none_without_a_chapter():
    assert death_label(None, "fr") is None


def test_the_binder_renders_status_from_the_batch_entity():
    entity = {"status": "deceased", "death_chapter": 38}
    assert _extracted_fact_value(entity, "status", "fr") == "Décédé"
    assert "38" in _extracted_fact_value(entity, "death", "fr")


def test_the_binder_renders_unknown_for_an_unstamped_entity():
    # A book that never ran the stage, and a verdict that was rejected, render
    # the same thing.
    assert _extracted_fact_value({}, "status", "en") == status_label("unknown", "en")


def test_the_death_slot_is_omitted_without_a_chapter():
    assert _extracted_fact_value({"status": "alive"}, "death", "fr") is None


def test_titles_still_binds():
    assert _extracted_fact_value({"titles": ["Roi"]}, "titles", "fr") == "Roi"


def test_person_declares_both_slots():
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["status"]["provenance"] == "extracted-fact"
    assert slots["death"]["provenance"] == "extracted-fact"
    assert slots["death"]["obligation"] == "OPT"
    assert "{{{death|}}}" in person["mediawiki"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q -k "label or binder or slots or titles"`
Expected: FAIL — `ImportError: cannot import name 'death_label'`

- [ ] **Step 3: Add the labels to base.yaml**

In `wiki_creator/templates/base.yaml`, add to the `chrome:` block (after `evolution:`):

```yaml
  # STU-488: the `status` / `death` infobox slots. Reader-facing chrome, so the
  # enum's labels are data — the enum itself lives in wiki_creator/entity_status.py.
  status_alive:    {fr: "Vivant",   en: "Alive"}
  status_deceased: {fr: "Décédé",   en: "Deceased"}
  status_missing:  {fr: "Disparu",  en: "Missing"}
  status_unknown:  {fr: "Inconnu",  en: "Unknown"}
  status_undead:   {fr: "Mort-vivant", en: "Undead"}
  death_chapter:   {fr: "Chapitre {chapter}", en: "Chapter {chapter}"}
```

In the PERSON `mediawiki` source, add a row after `Affiliation`:

```
        |-
        | '''Décès''' || {{{death|}}}
```

In the PERSON `infobox` list, add after the `status` line:

```yaml
      - {token: death,       group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [figurant, secondary, principal]}
```

- [ ] **Step 4: Add the label helpers**

Append to `wiki_creator/entity_status.py`:

```python
from wiki_creator.page_templates import chrome_label


def status_label(status: str | None, lang: str) -> str:
    """The localized enum label. An absent or unrecognized status renders the
    slot's declared fallback (`unknown`) — a book that never ran the stage and a
    verdict that was rejected must render the same thing."""
    value = str(status or "").strip().lower()
    if value not in STATUS_VALUES:
        value = DEFAULT_STATUS
    return chrome_label(f"status_{value}", lang)


def death_label(chapter: int | None, lang: str) -> str | None:
    """The localized death line, or None when there is no chapter to name."""
    if chapter is None:
        return None
    return chrome_label("death_chapter", lang).format(chapter=chapter)
```

Move the `from wiki_creator.page_templates import chrome_label` line up to the module's import block.

- [ ] **Step 5: Teach the binder**

In `scripts/generate_wiki_pages.py`, replace `_extracted_fact_value` (line ~733):

```python
def _extracted_fact_value(entity: dict, token: str, lang: str) -> str | None:
    """Value for an extracted-fact infobox token, sourced from facts the pipeline
    produced into the batch entity. None when the fact is absent (slot omitted).
    `affiliation` and the specific `type` are future slices."""
    if token == "titles":
        titles = [t for t in (entity.get("titles") or []) if t]
        return ", ".join(titles) if titles else None
    if token == "status":
        # MIN with a declared fallback: an unstamped entity renders `unknown`
        # rather than dropping the slot (STU-488).
        return status_label(entity.get("status"), lang)
    if token == "death":
        return death_label(entity.get("death_chapter"), lang)
    return None
```

In `_bind_batch_fields`, pass the language through:

```python
        elif slot.provenance == "extracted-fact":
            value = _extracted_fact_value(entity, slot.token, lang)
```

Add the import beside the other `wiki_creator` imports:

```python
from wiki_creator.entity_status import death_label, status_label
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q`
Expected: PASS (46 passed)

- [ ] **Step 7: Verify no other caller of `_extracted_fact_value` broke**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && rg -n "_extracted_fact_value" scripts/ tests/ && pytest tests/ -q -k "generate_wiki_pages or template or infobox or export"`
Expected: every call site passes three arguments; tests PASS.

- [ ] **Step 8: Commit**

```bash
cd /home/arianeguay/dev/src/wt/stu-488
git add wiki_creator/templates/base.yaml wiki_creator/entity_status.py scripts/generate_wiki_pages.py tests/test_entity_status.py
git commit -m "feat(entity-status): render the status and death infobox slots (STU-488)

The status slot has been declared MIN with a fallback since STU-504 and
never populated. death renders the chapter, ungated — apparition already
renders a tome reference in every stance mode.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Wire it — stamping and the pre-step

Two wiring tests, because of STU-512's lesson: without them the whole feature is deletable with the suite green.

**Files:**
- Modify: `scripts/wiki_preparation.py:383-395` (the batch entity dict), `:512+` (`main`)
- Modify: `run_wiki.py:87-90` (`PRE_STEPS`)
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: `entity_status.json` written by Task 4; `wiki_creator.entity_status.load_cached_status` is NOT used here (the file is read as a plain artifact — preparation has no roster to key on).
- Produces: batch entities carrying `status` and `death_chapter`.

- [ ] **Step 1: Write the failing wiring tests**

Append to `tests/test_entity_status.py`:

```python
import run_wiki
from scripts.wiki_preparation import load_status_verdicts


def test_the_pre_step_is_registered_before_wiki_preparation():
    # STU-512's lesson: without this, the whole feature is deletable with the
    # suite green.
    commands = [" ".join(cmd) for cmd in run_wiki.PRE_STEPS["wiki-preparation"]]
    assert any("scripts/entity_status.py" in cmd for cmd in commands)


def test_the_batch_entity_carries_the_verdict(tmp_path):
    (tmp_path / "entity_status.json").write_text(
        json.dumps({
            "roster": [],
            "verdicts": {"Brom": {"status": "deceased", "quote": BROM_QUOTE, "chapter": 38}},
        }),
        encoding="utf-8",
    )
    verdicts = load_status_verdicts(tmp_path)
    assert verdicts["Brom"]["status"] == "deceased"
    assert verdicts["Brom"]["chapter"] == 38


def test_a_missing_or_corrupt_status_artifact_leaves_every_entity_unknown(tmp_path):
    assert load_status_verdicts(tmp_path) == {}
    (tmp_path / "entity_status.json").write_text("{not json", encoding="utf-8")
    assert load_status_verdicts(tmp_path) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q -k "pre_step or batch_entity or status_artifact"`
Expected: FAIL — `ImportError: cannot import name 'load_status_verdicts'`

- [ ] **Step 3: Read the artifact in wiki_preparation**

In `scripts/wiki_preparation.py`, add near the other module-level helpers:

```python
def load_status_verdicts(processing_dir: Path) -> dict[str, dict]:
    """Per-character status decided by the entity-status pre-step (STU-488).

    Absent or unreadable artifact -> {} -> every character renders the slot's
    declared fallback, `unknown`. A book that never ran the stage is not an error.
    """
    path = Path(processing_dir) / "entity_status.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    verdicts = payload.get("verdicts") if isinstance(payload, dict) else None
    return verdicts if isinstance(verdicts, dict) else {}
```

- [ ] **Step 4: Stamp the batch entity**

Three edits in `scripts/wiki_preparation.py`, following `role_words`' existing parameter chain exactly.

(a) Import beside the other `wiki_creator` imports (next to `from wiki_creator.facts import extract_titles`, line ~43):

```python
from wiki_creator.entity_status import DEFAULT_STATUS
```

(b) `build_entity_bundle` (line ~366) gains a keyword parameter after `plot_events`:

```python
    plot_events: list[dict] | None = None,
    status_verdicts: dict[str, dict] | None = None,
) -> dict:
```

and in its returned dict, beside `titles` (line ~388), add:

```python
        "status": (status_verdicts or {}).get(canonical_name, {}).get("status", DEFAULT_STATUS),
        "death_chapter": (status_verdicts or {}).get(canonical_name, {}).get("chapter"),
```

(c) In `main()`, load the verdicts after the registry identity binding (line ~584):

```python
    status_verdicts = load_status_verdicts(paths.processing)
    print(
        f"wiki-preparation: {len(status_verdicts)} character status verdict(s) loaded",
        file=sys.stderr,
    )
```

and pass them at the `build_entity_bundle` call site (line ~645), beside `role_words`:

```python
            role_words=role_words,
            plot_events=plot_events,
            status_verdicts=status_verdicts,
        )
        for e in dedicated
    ]
```

- [ ] **Step 5: Register the pre-step**

In `run_wiki.py`, in `PRE_STEPS["wiki-preparation"]`, add as the **first** entry (it reads `registry.json`, written by the `write-registry` stage of `wiki-resolution`, and nothing else in preparation depends on its output ordering):

```python
    "wiki-preparation": [
        ["python", "scripts/entity_status.py", "--book"],
        ["python", "scripts/classify_relationships.py", "--book"],
        ["python", "scripts/build_event_layer.py", "--book"],
    ],
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd /home/arianeguay/dev/src/wt/stu-488 && pytest tests/test_entity_status.py -q`
Expected: PASS (49 passed)

- [ ] **Step 7: Run the full suite and the goldens**

Run:
```bash
cd /home/arianeguay/dev/src/wt/stu-488 && pytest -q && make golden && mypy wiki_creator/
```
Expected: `pytest -q` passes with no new failures (baseline: `1604 passed, 1 skipped`, plus this plan's new tests); `make golden` passes **unchanged** — nothing here touches a stage inside the golden chain. If a golden reds, the change is in the wrong place: stop and re-read the Global Constraints rather than running `make golden-update`.

- [ ] **Step 8: Commit**

```bash
cd /home/arianeguay/dev/src/wt/stu-488
git add scripts/wiki_preparation.py run_wiki.py tests/test_entity_status.py
git commit -m "feat(entity-status): stamp the verdict onto the batch entity (STU-488)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Measure on Eragon, then record what it cost

STU-538 fired 340 times for 0 true positives and nobody knew for months, because nobody counted. Here the ground truth is free: **we know who dies.** Brom and Garrow die in Eragon; the rest of the roster is alive.

**Files:**
- Modify: `CLAUDE.md`
- No test — this task's deliverable is a number in the MR description.

- [ ] **Step 1: Run the stage on Eragon**

Run:
```bash
cd /home/arianeguay/dev/src/wt/stu-488
python scripts/entity_status.py --book library/christopher_paolini/inheritance/books/01_eragon.yaml
```
Expected: a `[entity-status]` summary line naming how many characters were decided and how many are `deceased`, then one line per verdict.

If `registry.json` is absent for that book, the run prints the degradation warning and exits cleanly — regenerate it first with `make run-resolution BOOK=library/christopher_paolini/inheritance/books/01_eragon.yaml`.

- [ ] **Step 2: Check the roster by hand**

Read `library/christopher_paolini/inheritance/processing_output/01_eragon/entity_status.json`.

Record, for the MR description:
- how many characters were decided, out of the roster size;
- how many `deceased`, and **which** — Brom and Garrow are the true positives;
- every other `deceased` is a **false positive**: quote it, and say whether its `quote` is a real death sentence about that character or a bystander's scene.

There is no threshold to pass and no CI gate. If the stage returns `deceased` for anything but Brom and Garrow, that is a false positive and it is visible by eye. This is the control that stops us shipping another STU-538.

- [ ] **Step 3: If there are false positives, fix the prompt, not the check**

A false `deceased` whose quote is verbatim means the classifier read a bystander scene as a death — that is the prompt's `WHO THE SENTENCE IS ABOUT` block failing, and the fix belongs in `.studio/agents/entity-status.agent.yaml`. Do not loosen `parse_status_verdict`, and do not add a post-hoc filter to paper over it. Re-run Step 1 (delete `entity_status.json` first — the cache is keyed on the roster, not on the prompt).

- [ ] **Step 4: Record the gotcha in CLAUDE.md**

Add to the `## Gotchas` section, in the house style (name the measurement, name what would silently break):

```markdown
- Entity status (STU-488): the `status` infobox slot was declared `MIN` with
  `fallback: unknown` in STU-504 and never populated. It is filled by one
  `studio run entity-status-item` per book over the PERSON roster — the
  STU-529/STU-539 shape — as a **pre-step to wiki-preparation**, not a
  wiki-resolution stage: it changes no identity (unlike `alias-adjudication`,
  which entity-classification reads), and resolution is the chain `make golden`
  runs, so it stays LLM-free by construction. Enum is the fandom-wiki convention
  (`alive | deceased | missing | unknown | undead`), labels in
  `base.yaml#chrome.status_*`; `death` renders the chapter, derived by code from
  the snippet the verdict quotes — the model is never asked for a chapter, and
  never sees one. **The marker vocabulary retrieves, it does not decide**
  (`cue_words/<lang>.json#status_markers`): that is the whole difference from
  STU-538, which measured 340 fires and 0 true positives when a pattern *was* the
  verdict. "Eragon watched Brom die" carries a death marker in both characters'
  contexts and kills one; the model reads the subject, the regex cannot. A marker
  missing from the vocabulary means a death is never surfaced, which means
  `unknown` — the forgiving direction. Snippet selection is two-source because
  the enum asks two questions: marker-bearing snippets prove
  `deceased`/`missing`/`undead`, the **latest** snippets prove `alive` (a novel
  never says "Eragon is alive"). Both are latest-first — status is the state at
  the *end* of the tome. **A verdict must quote text we showed the model**
  (`parse_status_verdict` rejects any quote not verbatim in that entity's *own*
  snippets, which is also how `death` is dated: the snippet that proves the
  verdict dates it). These novels are in the model's training data, so a verdict
  from its memory of the plot and one from this run's text are otherwise
  indistinguishable — and it may remember a death that happens two tomes later.
  **Every failure path renders `unknown`**, the slot's own declared fallback:
  a false `deceased` kills a living character on a page nobody will reread and
  `Registry.accumulate` would carry it forward; a false `unknown` says "we don't
  know". The cache (`processing_output/<slug>/entity_status.json`) is keyed on
  the roster rows, so `WIKI_MAX_CHAPTERS` cannot replay a verdict made for a
  different roster — STU-539's premise was measured false precisely because it
  was measured on a 5-chapter extraction.
  **The series registry does not carry status**: the wiki is per-tome
  (`output/<slug>/`) while the registry is per-series, so "dead in tome 2 without
  erasing tome 1" is true by construction — tome 1 is never regenerated. The
  ticket's "series page" does not exist (STU-553 decides whether it should, and
  it conflicts with STU-232). `affiliation` is NOT a third slot of this shape:
  `FACTION` is an entity type since STU-505, so a faction change is a dated edge,
  not a scalar (STU-551). The in-universe death circumstance ("Killed by Durza at
  Farthen Dûr") is STU-552 — it needs grounded prose, not an infobox slot, which
  is why `death` carries a chapter instead.
```

Also update the `## Files To Know` list:

```markdown
- [scripts/entity_status.py](/home/arianeguay/dev/src/wiki-creator-by-studio/scripts/entity_status.py): per-tome character status pre-step (STU-488), writes `entity_status.json`; pure logic in `wiki_creator/entity_status.py`
```

- [ ] **Step 5: Commit**

```bash
cd /home/arianeguay/dev/src/wt/stu-488
git add CLAUDE.md
git commit -m "docs(entity-status): record why the marker retrieves and never decides (STU-488)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Final verification before the MR**

Run:
```bash
cd /home/arianeguay/dev/src/wt/stu-488 && pytest -q && make golden && make smoke && mypy wiki_creator/
```
Expected: all pass, goldens unchanged.

The MR description must tag `STU-488` and carry the Eragon numbers from Step 2.
