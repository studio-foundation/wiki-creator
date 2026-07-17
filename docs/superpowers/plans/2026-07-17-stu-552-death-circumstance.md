# STU-552 — Death Circumstance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render an in-universe death circumstance ("Tué par Durza à Farthen Dûr") in the PERSON infobox, built deterministically from two grounded fields on the verdict STU-488's `entity-status-item` call already returns.

**Architecture:** No new stage and no new LLM call. The `entity-status` pre-step's verdict gains two optional fields, `agent` and `place`. Each must clear three gates in `parse_status_verdict` — status is `deceased`, the name is on the type-scoped roster (PERSON for agent, PLACE for place), and it occurs verbatim in that verdict's own quote. `wiki_preparation` stamps them onto the batch entity; `_extracted_fact_value` formats them from `base.yaml#chrome` into a new `OPT` `death` slot. The LLM judges, the code formats — the same split as `status`.

**Tech Stack:** Python 3.11+, pytest, PyYAML. Studio CLI (`studio run entity-status-item`) — not exercised by any test in this plan; every test is offline.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-17-stu-552-death-circumstance-design.md`. Read it before Task 1.
- **Worktree:** `/home/arianeguay/dev/src/wc-stu-552`, branch `arianedguay/stu-552-in-universe-death-circumstance-as-grounded-prose`. All paths below are relative to it.
- **English only in code.** No French string literal in any `.py`. Every reader-facing string is data in `wiki_creator/templates/base.yaml`, keyed by language, read via `chrome_label` / `slot_label`.
- **No hardcoded word lists in scripts.** Vocabulary lives in `base.yaml` or `cue_words/<lang>.json`.
- **Comments: default to none.** Write one only for a constraint the code cannot state itself. Never explain what the code does.
- **Every failure path renders less, never a false fact.** A field failing a gate is dropped; the verdict survives.
- **`make golden` must stay green and unchanged.** This touches no resolution stage — if a golden moves, stop and report rather than running `make golden-update`.
- **Commit trailer** on every commit:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

### Task 1: Declare the `death` slot and its vocabulary

The slot, its label, its three phrasings, and the wikitext row. Nothing reads them yet — Task 2 is the first consumer. Two STU-488 guards assert `death` is *absent*; they invert here, in the same commit that makes them false.

**Files:**
- Modify: `wiki_creator/templates/base.yaml` (PERSON `infobox` list, `export.infobox_source`, `labels`, `chrome`)
- Test: `tests/test_entity_status.py:467-472`

**Interfaces:**
- Consumes: nothing.
- Produces: `base.yaml` keys `labels.death`, `chrome.death_by_at`, `chrome.death_by`, `chrome.death_at` (each `{fr, en}`, with `{agent}` / `{place}` placeholders), and a PERSON infobox slot `{token: death, provenance: extracted-fact, obligation: OPT}`.

- [ ] **Step 1: Invert the two STU-488 absence guards**

In `tests/test_entity_status.py`, replace the body of `test_person_declares_the_status_slot` (currently at `:467-472`):

```python
def test_person_declares_the_status_slot():
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["status"]["provenance"] == "extracted-fact"


def test_person_declares_the_death_slot_as_optional():
    # OPT, so `validate_template`'s MIN-needs-a-fallback rule does not apply and
    # an absent circumstance renders no row (STU-552).
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["death"]["provenance"] == "extracted-fact"
    assert slots["death"]["obligation"] == "OPT"
    assert "{{{death|}}}" in person["export"]["infobox_source"]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /home/arianeguay/dev/src/wc-stu-552
pytest tests/test_entity_status.py -k "declares_the" -v
```

Expected: `test_person_declares_the_death_slot_as_optional` FAILS with `KeyError: 'death'`. `test_person_declares_the_status_slot` passes.

- [ ] **Step 3: Add the slot to the PERSON infobox list**

In `wiki_creator/templates/base.yaml`, in `entity_types.PERSON.infobox`, insert directly after the `status` row (currently `:53`):

```yaml
      - {token: death,       group: infobox, provenance: extracted-fact, obligation: OPT, tiers: [figurant, secondary, principal]}
```

- [ ] **Step 4: Add the wikitext row**

In the same file, in `entity_types.PERSON.export.infobox_source`, insert directly after the `Statut` row (currently `:36`):

```
        |-
        | '''Décès''' || {{{death|}}}
```

Note the existing rows are hardcoded French in the template body; match that convention exactly rather than introducing a lookup here.

- [ ] **Step 5: Add the label and the three phrasings**

In `labels`, beside `status` (`:341`):

```yaml
  death:         {en: Death,       fr: Décès}
```

In `chrome`, after the `status_*` block (`:378`):

```yaml
  death_by_at:     {fr: "Tué par {agent} à {place}", en: "Killed by {agent} at {place}"}
  death_by:        {fr: "Tué par {agent}",           en: "Killed by {agent}"}
  death_at:        {fr: "Mort à {place}",            en: "Died at {place}"}
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pytest tests/test_entity_status.py -k "declares_the" -v
pytest tests/test_page_templates_schema.py -q
```

Expected: all PASS. The schema suite matters here: it enforces `MIN` extracted-facts need a `fallback`, and `death` is `OPT` precisely so it does not.

- [ ] **Step 7: Commit**

```bash
git add wiki_creator/templates/base.yaml tests/test_entity_status.py
git commit -m "$(cat <<'EOF'
feat(entity-status): declare the death slot and its phrasings (STU-552)

OPT, so an absent circumstance renders no row and the slot needs no
fallback. The two STU-488 guards asserting `death` is absent invert here:
the slot they were written against rendered a chapter, which is the thing
that was measured wrong 3 times in 4.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `death_label` — the formatter

Three field combinations, one phrasing each, `None` for neither. Pure; reads the chrome keys Task 1 declared.

**Files:**
- Modify: `wiki_creator/entity_status.py` (append after `status_label`, currently ends `:224`)
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: `chrome_label(key, lang)` from `wiki_creator.page_templates` (already imported at `entity_status.py:26`); the `chrome.death_*` keys from Task 1.
- Produces: `death_label(agent: str | None, place: str | None, lang: str) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_status.py`. Add `death_label` to the existing `from wiki_creator.entity_status import (...)` block at the top of the file:

```python
def test_death_label_renders_both_fields():
    assert death_label("Durza", "Farthen Dûr", "fr") == "Tué par Durza à Farthen Dûr"
    assert death_label("Durza", "Farthen Dûr", "en") == "Killed by Durza at Farthen Dûr"


def test_death_label_renders_the_agent_alone():
    assert death_label("Durza", None, "fr") == "Tué par Durza"


def test_death_label_renders_the_place_alone():
    # A death with no killer — illness, drowning. "Mort à X" stays true whatever
    # the cause, which is why there is no cause enum.
    assert death_label(None, "Terím", "fr") == "Mort à Terím"


def test_death_label_is_none_without_a_field():
    assert death_label(None, None, "fr") is None
    assert death_label("", "  ", "fr") is None


def test_death_label_falls_back_to_fr_for_an_unknown_lang():
    # chrome_label's own fallback chain; the slot must not vanish for a book
    # whose output_language has no chrome entry.
    assert death_label("Durza", None, "de") == "Tué par Durza"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_entity_status.py -k death_label -v
```

Expected: FAIL at import — `ImportError: cannot import name 'death_label'`.

- [ ] **Step 3: Implement**

Append to `wiki_creator/entity_status.py`:

```python
def death_label(agent: str | None, place: str | None, lang: str) -> str | None:
    """The localized death circumstance, or None when neither field is grounded.

    OPT, unlike `status_label`: a character the text never says died renders no
    row at all rather than a fallback.
    """
    who = str(agent or "").strip()
    where = str(place or "").strip()
    if who and where:
        return chrome_label("death_by_at", lang).format(agent=who, place=where)
    if who:
        return chrome_label("death_by", lang).format(agent=who)
    if where:
        return chrome_label("death_at", lang).format(place=where)
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_entity_status.py -k death_label -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/entity_status.py tests/test_entity_status.py
git commit -m "$(cat <<'EOF'
feat(entity-status): format the death circumstance from agent and place (STU-552)

Two optional fields, three phrasings, no cause enum: an agent means someone
killed them, a place means they died there. A death by illness has no agent
and renders "Mort à X", which stays true whatever the cause.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The three gates in `parse_status_verdict`

The load-bearing task. `parse_status_verdict` gains a required `name_index` parameter, so every caller is forced to supply the rosters rather than silently degrading to no circumstance.

**Files:**
- Modify: `wiki_creator/entity_status.py:151-188` (`parse_status_verdict`), plus a new `build_name_index` and `_grounded_name`
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: `_normalize(text) -> str` (`entity_status.py:59-61`), `_is_quoted(quote, snippets) -> bool` (`:143-148`), `STATUS_VALUES`, `DEFAULT_STATUS`.
- Produces:
  - `build_name_index(entities: list[dict]) -> dict[str, dict[str, str]]` — `{"PERSON": {normalized surface: canonical}, "PLACE": {...}}`. Input dicts carry `entity_type`, `canonical_name`, `aliases`.
  - `parse_status_verdict(payload: object, rows: list[dict], name_index: dict[str, dict[str, str]]) -> dict[str, dict]` — verdict values are `{"status", "quote"}` plus optional `"agent"` / `"place"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_status.py`, and add `build_name_index` to the import block:

```python
def _index():
    return build_name_index(
        [
            {"entity_type": "PERSON", "canonical_name": "Durza", "aliases": []},
            {"entity_type": "PERSON", "canonical_name": "Brom", "aliases": []},
            {"entity_type": "PERSON", "canonical_name": "Chaol Westfall", "aliases": ["Captain Westfall"]},
            {"entity_type": "PLACE", "canonical_name": "Farthen Dûr", "aliases": []},
        ]
    )


def _rows(quote):
    return [{"name": "Brom", "aliases": [], "snippets": [{"text": quote, "chapter_id": "ch37"}]}]


def _verdict(entry, quote):
    return parse_status_verdict({"status": [entry]}, _rows(quote), _index())


def test_agent_and_place_survive_all_three_gates():
    quote = "Durza's blade took Brom in the side at Farthen Dûr"
    verdicts = _verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"},
        quote,
    )
    assert verdicts["Brom"] == {
        "status": "deceased",
        "quote": quote,
        "agent": "Durza",
        "place": "Farthen Dûr",
    }


def test_a_name_absent_from_the_quote_is_dropped():
    # Gate 3. The slot asserts a link between two facts; sourcing the halves
    # from two snippets is the model inferring that link.
    quote = "Durza's blade took Brom in the side"
    verdicts = _verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"},
        quote,
    )
    assert verdicts["Brom"]["agent"] == "Durza"
    assert "place" not in verdicts["Brom"]


def test_a_name_off_the_roster_is_dropped():
    quote = "Galbatorix's blade took Brom in the side"
    verdicts = _verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Galbatorix"},
        quote,
    )
    assert "agent" not in verdicts["Brom"]


def test_the_roster_is_type_scoped():
    # A PERSON returned as a place is not a place.
    quote = "Brom died with Durza"
    verdicts = _verdict({"name": "Brom", "status": "deceased", "quote": quote, "place": "Durza"}, quote)
    assert "place" not in verdicts["Brom"]


def test_an_alias_renders_the_canonical_name():
    quote = "Captain Westfall struck Brom down"
    verdicts = _verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Captain Westfall"},
        quote,
    )
    assert verdicts["Brom"]["agent"] == "Chaol Westfall"


def test_only_a_deceased_verdict_carries_a_circumstance():
    quote = "Durza hunted Brom through Farthen Dûr"
    verdicts = _verdict(
        {"name": "Brom", "status": "missing", "quote": quote, "agent": "Durza", "place": "Farthen Dûr"},
        quote,
    )
    assert verdicts["Brom"] == {"status": "missing", "quote": quote}


def test_a_dropped_field_never_drops_the_verdict():
    # The asymmetry: a wrong agent costs the circumstance, never the status.
    quote = "Brom is dead"
    verdicts = _verdict(
        {"name": "Brom", "status": "deceased", "quote": quote, "agent": "Galbatorix", "place": "Urû'baen"},
        quote,
    )
    assert verdicts["Brom"] == {"status": "deceased", "quote": quote}


def test_the_name_index_folds_typography_and_case():
    index = build_name_index([{"entity_type": "PLACE", "canonical_name": "Farthen Dûr", "aliases": []}])
    assert index["PLACE"]["farthen dûr"] == "Farthen Dûr"


def test_the_name_index_ignores_types_that_are_not_person_or_place():
    index = build_name_index([{"entity_type": "ORG", "canonical_name": "Varden", "aliases": []}])
    assert index == {"PERSON": {}, "PLACE": {}}
```

- [ ] **Step 2: Update the existing `parse_status_verdict` call sites in the test file**

`name_index` is required. Every pre-existing `parse_status_verdict(payload, rows)` call in `tests/test_entity_status.py` needs a third argument. Find them:

```bash
rg -n 'parse_status_verdict\(' tests/test_entity_status.py
```

For each pre-existing call, pass `_index()`. These tests assert on `status` and `quote` only, and none of their fixtures set `agent` / `place`, so the verdicts they expect are unchanged.

- [ ] **Step 3: Run the tests to verify they fail**

```bash
pytest tests/test_entity_status.py -q
```

Expected: FAIL at import — `ImportError: cannot import name 'build_name_index'`.

- [ ] **Step 4: Implement `build_name_index` and `_grounded_name`**

In `wiki_creator/entity_status.py`, insert above `parse_status_verdict` (currently `:151`):

```python
_CIRCUMSTANCE_TYPES = ("PERSON", "PLACE")


def build_name_index(entities: list[dict]) -> dict[str, dict[str, str]]:
    """{entity_type: {normalized surface: canonical_name}} for the two types a
    death circumstance can name. Aliases map to their canonical name, so a
    circumstance renders `Chaol Westfall` where the text said `Captain Westfall`.
    """
    index: dict[str, dict[str, str]] = {etype: {} for etype in _CIRCUMSTANCE_TYPES}
    for entity in entities:
        names = index.get(str(entity.get("entity_type") or ""))
        if names is None:
            continue
        canonical = str(entity.get("canonical_name") or "").strip()
        if not canonical:
            continue
        for surface in (canonical, *(entity.get("aliases") or [])):
            key = _normalize(surface)
            if key:
                names.setdefault(key, canonical)
    return index


def _grounded_name(value: object, quote: str, names: dict[str, str]) -> str | None:
    """The canonical name this value denotes, or None.

    Two gates: it is on the type's roster, and it is verbatim in the quote the
    verdict already had to prove. A name sourced from a neighbouring snippet
    would render where the character *was*, not where they died.
    """
    surface = _normalize(value)
    if not surface:
        return None
    canonical = names.get(surface)
    if canonical is None or surface not in _normalize(quote):
        return None
    return canonical
```

- [ ] **Step 5: Add the third gate to `parse_status_verdict`**

Change the signature and docstring (`:151-160`):

```python
def parse_status_verdict(
    payload: object, rows: list[dict], name_index: dict[str, dict[str, str]]
) -> dict[str, dict]:
    """Map the classifier's reply to verified verdicts, keyed by roster name.

    A name absent from the result is `unknown`; unparseable input verdicts
    nothing. A verdict survives only when its name is on the roster, its status
    is in the enum and is not `unknown`, and its quote is verbatim in **that
    entity's own** snippets. The model has read these novels: without the quote
    check, a verdict from its memory of the plot and one from this run's text
    are indistinguishable afterwards.

    A `deceased` verdict may also carry `agent` / `place` — each kept only when
    `name_index` knows it under the right type and the quote names it. A field
    failing either gate is dropped; the verdict survives (STU-552).
    """
```

Then replace the loop's final line (`:187`, `verdicts[name] = {"status": status, "quote": quote}`) with:

```python
        verdict = {"status": status, "quote": quote}
        if status == "deceased":
            agent = _grounded_name(entry.get("agent"), quote, name_index["PERSON"])
            place = _grounded_name(entry.get("place"), quote, name_index["PLACE"])
            if agent:
                verdict["agent"] = agent
            if place:
                verdict["place"] = place
        verdicts[name] = verdict
```

- [ ] **Step 6: Run the tests to verify they pass**

```bash
pytest tests/test_entity_status.py -q
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add wiki_creator/entity_status.py tests/test_entity_status.py
git commit -m "$(cat <<'EOF'
feat(entity-status): ground the death circumstance in the verdict's own quote (STU-552)

Three gates per field: the status is `deceased`, the name is on the
type-scoped roster, and it is verbatim in the quote the verdict already
had to prove. The quote gate is the load-bearing one — "they rode to
Farthen Dûr" one sentence from "Durza's blade took Brom" would render
where he rode, not where he died.

`name_index` is required rather than defaulted: a caller that forgot it
would render no circumstance forever, silently.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Version the cache

The rows do not change in this ticket — same roster, same snippets, only the question changed. So a pre-existing `entity_status.json` validates against the roster key and replays a verdict that answers the old question, rendering no circumstance forever. Roster-keying answers "different roster?"; the version answers "different question?".

**Files:**
- Modify: `wiki_creator/entity_status.py:191-214` (`load_cached_status`, `save_status_cache`)
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CACHE_VERSION = 2`; the cache payload gains a `version` key. Signatures of `load_cached_status` / `save_status_cache` are unchanged.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_status.py` (add `CACHE_VERSION`, `load_cached_status`, `save_status_cache` to the import block if absent):

```python
def test_a_cache_from_an_older_question_is_not_replayed(tmp_path):
    # STU-552 changed what we ask, not the roster we ask it about. Without the
    # version, a pre-STU-552 cache validates and renders no circumstance forever.
    rows = _rows("Brom is dead")
    path = tmp_path / "entity_status.json"
    path.write_text(
        json.dumps({"version": 1, "roster": rows, "verdicts": {"Brom": {"status": "deceased"}}}),
        encoding="utf-8",
    )
    assert load_cached_status(path, rows) is None


def test_a_cache_without_a_version_is_not_replayed(tmp_path):
    rows = _rows("Brom is dead")
    path = tmp_path / "entity_status.json"
    path.write_text(json.dumps({"roster": rows, "verdicts": {}}), encoding="utf-8")
    assert load_cached_status(path, rows) is None


def test_a_saved_cache_round_trips(tmp_path):
    rows = _rows("Durza's blade took Brom at Farthen Dûr")
    verdicts = {"Brom": {"status": "deceased", "quote": "x", "agent": "Durza"}}
    path = tmp_path / "entity_status.json"
    save_status_cache(path, rows, verdicts)
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == CACHE_VERSION
    assert load_cached_status(path, rows) == verdicts
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_entity_status.py -k cache -v
```

Expected: `test_a_cache_from_an_older_question_is_not_replayed` FAILS — the stale verdicts are returned instead of `None`.

- [ ] **Step 3: Implement**

In `wiki_creator/entity_status.py`, beside `DEFAULT_STATUS` (`:29`):

```python
CACHE_VERSION = 2
```

In `load_cached_status`, extend the guard and the docstring:

```python
    """Cached verdicts for exactly this roster and this question, or None.

    Keyed on the rows themselves: the roster changes with WIKI_MAX_CHAPTERS and
    with every upstream extraction fix, and a verdict returned for a different
    roster must not be replayed onto it. The version covers what the rows
    cannot — STU-552 changed what we ask, not who we ask it about.
    """
    try:
        cached = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cached, dict) or cached.get("roster") != rows:
        return None
    if cached.get("version") != CACHE_VERSION:
        return None
```

In `save_status_cache`, add the key:

```python
        json.dumps(
            {"version": CACHE_VERSION, "roster": rows, "verdicts": verdicts},
            ensure_ascii=False,
            indent=2,
        ),
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
pytest tests/test_entity_status.py -q
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add wiki_creator/entity_status.py tests/test_entity_status.py
git commit -m "$(cat <<'EOF'
fix(entity-status): key the verdict cache on the question, not just the roster (STU-552)

The rows are unchanged by STU-552 — same roster, same snippets, new
question. A pre-existing entity_status.json would validate against the
roster key and replay a verdict that never had an agent or a place,
rendering no circumstance forever and silently.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Wire it — ask for the fields, stamp them, render them

The pure logic from Tasks 2-4 reaches a page. Without this task the whole feature is deletable with the suite green (STU-512's lesson), so it ends with a wiring test per hop.

**Files:**
- Modify: `.studio/agents/entity-status.agent.yaml` (the return schema and its rules)
- Modify: `scripts/entity_status.py` (build the index, thread it through `resolve_status`)
- Modify: `scripts/wiki_preparation.py:403` (stamp two scalars)
- Modify: `scripts/generate_wiki_pages.py:735-746` (`_extracted_fact_value`)
- Test: `tests/test_entity_status.py`

**Interfaces:**
- Consumes: `build_name_index`, `parse_status_verdict(payload, rows, name_index)`, `death_label(agent, place, lang)` from Tasks 2-3.
- Produces: batch-entity keys `death_agent` / `death_place` (`str | None`); the `death` infobox token.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_entity_status.py`. Import `death_label` and `_extracted_fact_value` if not already imported:

```python
def test_the_binder_renders_the_circumstance():
    entity = {"death_agent": "Durza", "death_place": "Farthen Dûr"}
    assert _extracted_fact_value(entity, "death", "fr") == "Tué par Durza à Farthen Dûr"


def test_the_binder_omits_the_slot_without_a_circumstance():
    # OPT: `_bind_batch_fields`'s `if value:` drops the token entirely, so a
    # living character gets no Décès row.
    assert _extracted_fact_value({}, "death", "fr") is None
    assert _extracted_fact_value({"status": "alive"}, "death", "fr") is None


def test_wiki_preparation_stamps_the_circumstance_onto_the_batch_entity():
    # The hop the suite cannot see otherwise: unstamp these and every page
    # renders no Décès row with every other test still green.
    import scripts.wiki_preparation as wiki_preparation

    entity = {"canonical_name": "Brom", "type": "PERSON", "aliases": []}
    verdicts = {"Brom": {"status": "deceased", "quote": "x", "agent": "Durza", "place": "Farthen Dûr"}}
    bundle = wiki_preparation.build_entity_bundle(entity, status_verdicts=verdicts)

    assert bundle["death_agent"] == "Durza"
    assert bundle["death_place"] == "Farthen Dûr"


def test_wiki_preparation_stamps_none_for_a_character_with_no_circumstance():
    import scripts.wiki_preparation as wiki_preparation

    entity = {"canonical_name": "Eragon", "type": "PERSON", "aliases": []}
    bundle = wiki_preparation.build_entity_bundle(entity, status_verdicts={})

    assert bundle["death_agent"] is None
    assert bundle["death_place"] is None
```

The last two call the function that owns `:403`. Read `scripts/wiki_preparation.py` around `:380-410` to get its real name and required parameters, and adapt the two calls — the other fixture arguments it needs (`persons`, `places`, `orgs`, `events`, `relationships`, `role_words`) already have construction patterns in the existing tests in this file and in `tests/test_wiki_preparation.py`. Do not change the function's signature to suit the test.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
pytest tests/test_entity_status.py -k "binder_renders_the_circumstance or stamps" -v
```

Expected: the binder test FAILS with `assert None == 'Tué par Durza à Farthen Dûr'`; the stamp tests FAIL with `KeyError: 'death_agent'`.

- [ ] **Step 3: Render it in the binder**

In `scripts/generate_wiki_pages.py`, add `death_label` to the existing `from wiki_creator.entity_status import status_label` import, then add a branch to `_extracted_fact_value` after the `status` branch (`:741-745`):

```python
    if token == "death":
        # OPT, unlike `status`: no grounded circumstance renders no row (STU-552).
        return death_label(entity.get("death_agent"), entity.get("death_place"), lang)
```

- [ ] **Step 4: Stamp it in preparation**

In `scripts/wiki_preparation.py`, after the `"status"` line (`:403`):

```python
        "death_agent": (status_verdicts or {}).get(canonical_name, {}).get("agent"),
        "death_place": (status_verdicts or {}).get(canonical_name, {}).get("place"),
```

- [ ] **Step 5: Run those tests to verify they pass**

```bash
pytest tests/test_entity_status.py -k "binder_renders_the_circumstance or binder_omits or stamps" -v
```

Expected: 4 passed.

- [ ] **Step 6: Ask the classifier for the fields**

In `.studio/agents/entity-status.agent.yaml`, change the return shape:

```yaml
  Return exactly:
  {
    "status": [ {"name": "...", "status": "...", "quote": "...", "agent": "...", "place": "..."} ]
  }
```

Add, directly after the `"quote" is copied VERBATIM...` paragraph:

```yaml
  "agent" and "place" are OPTIONAL and only for "deceased". Omit either one you
  cannot fill from the quote itself.
  - "agent": the character who killed them, named in the quote.
  - "place": where they died, named in the quote.

  Both must be written EXACTLY as the quote writes them, and both must be in the
  quote you returned — not in a neighbouring snippet. A place the character
  travelled to in another sentence is not where they died. If the quote names no
  killer, omit "agent". If it names no place, omit "place". Neither is a guess:
  a field we cannot read off the quote is dropped, and the status still stands.
```

- [ ] **Step 7: Build the index and thread it through**

In `scripts/entity_status.py`, add `build_name_index` to the `from wiki_creator.entity_status import (...)` block.

Change `resolve_status` (`:65`) to take the index and pass it on. Its signature becomes:

```python
def resolve_status(
    rows: list[dict], book_title: str, cache_path: Path, name_index: dict[str, dict[str, str]]
) -> dict[str, dict]:
```

Inside it, find the single `parse_status_verdict(...)` call and pass `name_index` as the third argument.

In `main()`, build the index from the registry before the `resolve_status` call (`:164`):

```python
    name_index = build_name_index(
        [
            {
                "entity_type": record.entity_type,
                "canonical_name": record.canonical_name,
                "aliases": record.aliases,
            }
            for record in registry.entities
        ]
    )
```

and pass it:

```python
    verdicts = resolve_status(
        rows,
        book_title=str(book_cfg.get("title") or paths.processing.name),
        cache_path=cache_path,
        name_index=name_index,
    )
```

Note `build_name_index` walks **all** entities, not the PERSON-only `persons` list — the place roster is the whole point.

- [ ] **Step 8: Run the full entity-status suite**

```bash
pytest tests/test_entity_status.py -q
```

Expected: all PASS.

- [ ] **Step 9: Run the full suite and the golden**

```bash
pytest -q
make golden
```

Expected: `pytest -q` reports the documented state (`1604 passed, 1 skipped`) **plus** the tests added here, with no failures. `make golden` passes with no golden diff — this touches no resolution stage, so a golden that moves means something is wired wrong. Stop and report rather than running `make golden-update`.

- [ ] **Step 10: Commit**

```bash
git add .studio/agents/entity-status.agent.yaml scripts/entity_status.py scripts/wiki_preparation.py scripts/generate_wiki_pages.py tests/test_entity_status.py
git commit -m "$(cat <<'EOF'
feat(entity-status): render the death circumstance in the infobox (STU-552)

The classifier is asked for an optional agent and place alongside the
verdict it already returns; preparation stamps them, the binder formats
them. Plain names, no wikilinks — `event_infobox_fields` sets that
precedent, and it keeps red links and the STU-501 rule out entirely: the
killer is a fact about the dead character, not a typed relation.

A wiring test pins each hop. Without them the feature is deletable with
the suite green (STU-512).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Record it in CLAUDE.md

The repo's gotcha list is where a decision that reads as arbitrary later gets its measurement back. The `death` slot's removal is already recorded under STU-488; this amends that entry rather than opening a second one.

**Files:**
- Modify: `CLAUDE.md` (the `Entity status (STU-488)` gotcha, its final paragraph)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing.

- [ ] **Step 1: Amend the STU-488 entry**

In `CLAUDE.md`, the STU-488 gotcha ends with the paragraph beginning **The `death` slot (rendering the chapter the verdict quotes) shipped alongside `status` and was removed**. Keep that paragraph — the measurement is why the chapter is not coming back — and replace only its last sentence (`The in-universe death circumstance ("Killed by Durza at Farthen Dûr") is STU-552 — it needs grounded prose, not a derived infobox slot.`) with:

```markdown
  The in-universe circumstance ("Tué par Durza à Farthen Dûr") replaced it in
  STU-552, and **not as prose**: the ticket proposed the STU-481 `## Déroulement`
  shape, but free prose in an infobox slot is the one non-grounded field, which
  is what `_extracted_fact_value` exists to prevent. It is two optional fields —
  `agent`, `place` — on the verdict this same call already returns, so it costs
  no stage and no LLM call, and there is **no `cause` enum**: an agent means
  someone killed them, a place means they died there, and a death by illness
  renders "Mort à X", which stays true whatever the cause. Each field clears
  three gates: `status == "deceased"`, the name is on the **type-scoped** roster
  (PERSON for `agent`, PLACE for `place`, alias → canonical), and it is
  **verbatim in that verdict's own quote**. The quote gate is the load-bearing
  one and is deliberately stricter than "somewhere in the entity's snippets":
  the slot asserts a link between two facts, and "they rode to Farthen Dûr" one
  sentence from "Durza's blade took Brom" would render where he rode, not where
  he died. A field failing a gate is dropped and the verdict survives — a wrong
  `agent` costs the circumstance, never the `status`. Names render **plain, never
  wikilinked** (`event_infobox_fields`'s precedent): a collated entity has no
  page, so a link would be red, and no edge is drawn, so the STU-501 rule never
  engages. The cache gained a `CACHE_VERSION` because the rows did **not** change
  — same roster, new question — so roster-keying alone would have replayed a
  pre-STU-552 verdict forever and silently. The infobox is not spoiler-gated
  (`content_units` skips it by construction), so the circumstance leaks the death
  exactly as `Statut : Décédé` already does; gating the infobox is its own ticket.
```

- [ ] **Step 2: Verify nothing else in CLAUDE.md still calls STU-552 pending**

```bash
rg -n 'STU-552' CLAUDE.md
```

Expected: only the amended passage. Any other line describing STU-552 as future work is now stale — fix it in place.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: record the death circumstance's gates and the cache version (STU-552)

Amends the STU-488 entry rather than opening a second one: the removed
chapter slot and its replacement are one story, and the measurement that
killed the chapter is why it is not coming back.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Two fields on the verdict, no new stage/call | 5 (agent yaml), 3 (parse) |
| No `cause` enum | 2 — the formatter has no cause axis |
| Gate 1 (`status == "deceased"`) | 3 |
| Gate 2 (type-scoped roster, alias → canonical) | 3 |
| Gate 3 (verbatim in the verdict's own quote) | 3 |
| A dropped field never drops the verdict | 3 |
| `OPT` slot, no fallback | 1 |
| Three chrome phrasings + absent | 1, 2 |
| Plain names, no wikilinks | 5 — nothing links; no test needed for an absence the code cannot express |
| `wiki_preparation` stamps two scalars | 5 |
| `_extracted_fact_value` formats | 5 |
| `CACHE_VERSION` | 4 |
| Agent YAML asks for the fields | 5 |
| STU-488 guards invert | 1 |
| `test_page_templates_schema` stays green | 1 Step 6 |
| Ticket's end-to-end test | 3 (`test_agent_and_place_survive_all_three_gates`) + 5 (binder) — the two halves of "renders that, grounded in a verbatim excerpt" |
| Out of scope: infobox not gated, `forbidden_names`, death chapter, registry | Not implemented, recorded in Task 6 |

No gap.

**Placeholder scan:** every code step carries its code. The one open instruction is Task 5 Step 1, which asks the implementer to read `scripts/wiki_preparation.py:380-410` for the bundle function's real name and fixture arguments rather than guessing them into the plan — that is a lookup in a named file, not a TBD.

**Type consistency:** `build_name_index` returns `dict[str, dict[str, str]]` in Task 3 and is consumed with that shape in Task 5. `parse_status_verdict`'s third parameter is `name_index` in both. `death_label(agent, place, lang)` is defined in Task 2 and called with that arity in Task 5. Batch keys are `death_agent` / `death_place` in Tasks 5's stamp, its binder, and its tests. `CACHE_VERSION` is the name in Task 4's implementation and its test.
