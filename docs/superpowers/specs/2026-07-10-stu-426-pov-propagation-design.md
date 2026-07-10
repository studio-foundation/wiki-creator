# STU-426 — Propagate narrative POV to summaries and the writer

- **Issue:** [STU-426](https://linear.app/studioag/issue/STU-426/propager-le-pov-narratif-jusquaux-resumes-et-au-writer)
- **Date:** 2026-07-10
- **Status:** Design approved, pending implementation plan

## Problem

`parse_epub.py` detects narrative POV per chapter (language-aware `detect_pov`),
but this signal never reaches the writer. Two losses, both documented in
`docs/flow-audit.md` (Gap §3 "Conscience du POV subjectif", inter-stage §2):

1. **Silent discard at the source.** `parse_epub.py` computes per-chapter POV
   (`chapter_results`, line 274) but collapses it to a single book-level modal
   `pov_detection` and throws the per-chapter detail away. Nothing persists to
   `chapters[i]`.
2. **No character attribution.** `detect_pov` returns only a POV *type*
   (`first_person` / `third_limited` / `omniscient`). It never says *which*
   character narrates — yet that is the whole point of the issue: what Chaol
   *believes* about Celaena ≠ what she is.

Consequence: the writer treats a secondary character's subjective perception as
objective encyclopedic fact.

## Precedent

`temporal_context` (STU-271) is the template. It is a per-chapter narrative
signal detected in the preparation stage and propagated through the identical
four-hop path we will reuse. POV type propagation is "do what STU-271 did, for a
second field"; POV character attribution is the net-new part.

## Design

Two layers. Layer 1 is pure propagation of an already-computed signal. Layer 2
is the confidence-gated hybrid attribution the issue actually asks for.

### Layer 1 — POV *type* propagation (deterministic, always on)

Four hops, mirroring `temporal_context`:

| Hop | File | Change |
|---|---|---|
| 1. Persist | `scripts/parse_epub.py` | Stop discarding per-chapter POV. Write `pov` and `pov_confidence` onto each `chapters[i]` dict from the already-computed `chapter_results`. Book-level modal `pov_detection` is unchanged. |
| 2. Summary | `scripts/chapter_summary.py` | Copy `pov` / `pov_confidence` from the chapter into the summary dict, beside `temporal_context` (line 327). Use defensive `.get(..., "unknown")` reads, matching the existing pattern. |
| 3. Batch | `scripts/wiki_preparation.py` | Copy the fields into each batch chapter entry (beside `temporal_context`, line 320). |
| 4. Prompt | `scripts/generate_wiki_pages.py` | When a chapter's POV is `first_person` / `third_limited`, tag its summary block with a subjectivity note so the writer nuances claims sourced from it. |

Defensive default at every hop is `"unknown"`, exactly like `temporal_context`,
so old runs and partial data never break.

### Layer 2 — POV *character* attribution (confidence-gated hybrid)

Runs in `scripts/chapter_summary.py`, per chapter, **only when
`pov ∈ {first_person, third_limited}`** (omniscient → no focal character,
`pov_character: null`).

**Step 1 — Deterministic pass** produces a candidate `pov_character` *and* a
certainty label:

- **Signal:** frequency of capitalized name-candidates in the chapter, weighted
  by proximity to thought markers (`third_person_thought_markers`, already
  loaded from cue-words). A candidate near "pensa / se demanda / sentit" is more
  likely the focal character than one merely mentioned.
- **Exclusion vocab comes from cue-words**, never hardcoded: title-cased tokens
  in `noise_words`, `false_positive_words`, `determiners`, `role_words` are
  filtered out. If a needed key is absent from `cue_words/<lang>.json`, the
  filter degrades to empty — no hardcoded fallback list in the script (CLAUDE.md
  invariant).
- **Certainty label** `high | medium | low` (matching `detect_pov`'s existing
  `confidence` vocabulary — not a raw float), derived from the top candidate's
  dominance: its share of weighted candidate mass, the margin over the
  runner-up, and absolute frequency.

**Step 2 — Gate:**

- certainty `high` (≥ threshold) → deterministic `pov_character` is
  authoritative. `pov_character_source: "deterministic"`.
- certainty `medium`/`low` → **LLM fallback** via the existing
  `chapter-summary-item` agent (extend its contract to emit `pov_character` +
  `pov_character_confidence`). `pov_character_source: "llm"`.
- No LLM configured (deterministic-only run) → degrade to `pov_character: null`
  with the low certainty recorded. Never blocks a run.

**Emitted per-chapter fields** (summary dict → batch → prompt):

```json
{
  "pov": "third_limited",
  "pov_confidence": "high",
  "pov_character": "Chaol Westfall",
  "pov_character_confidence": "high",
  "pov_character_source": "deterministic"
}
```

### Writer prompt

`generate_wiki_pages.py` composes a POV note per chapter block:

- With a character: *"This chapter is narrated from Chaol's perspective —
  statements about other characters may reflect his subjective view rather than
  objective fact."*
- Type only (no confident character): *"This chapter is third-person limited —
  some statements may reflect a character's subjective perception rather than
  objective fact."*
- `omniscient` → no note.

## Contract change

`.studio/contracts/chapter-summary-item.contract.yaml` gains optional emitted
fields, documented the same way `temporal_context` / `flashback_anchor` already
are:

```
# pov: "first_person" | "third_limited" | "omniscient" | "unknown"  (optional)
# pov_character: str | null  (optional)
# pov_character_confidence: "high" | "medium" | "low"  (optional)
```

These are optional (not `required_fields`), so deterministic mode and older
outputs validate unchanged.

## Data-flow constraint (why attribution lives in the summary stage)

`parse_epub.py` is the first script and has no entity/NER data, so it cannot
name the focal character. The summary stage is the right home: it is per-chapter,
already reads raw `content`, already loads cue-words (thought markers), and
already has both an `llm` mode and the `chapter-summary-item` studio seam for the
fallback. POV *type* is still detected upstream in `parse_epub.py` (text-only,
cheap) and merely propagated.

## Non-goals (YAGNI)

- **No canonicalization of `pov_character` to a resolved entity id.** A surface
  name string is sufficient for the writer's nuance. Canonicalization can be a
  later issue if needed.
- **No change to book-level `pov_detection`** or to the modal-vote logic.
- **No new pipeline stage.** All changes ride existing stages and the existing
  studio item.
- **No numeric confidence.** `high/medium/low` labels only, for codebase
  consistency.

## Testing

- `scripts/parse_epub.py`: per-chapter `pov`/`pov_confidence` persisted;
  book-level modal unchanged (extend `tests/test_parse_epub.py`).
- `chapter_summary.py`: deterministic attribution — clear focal character →
  `high` + name; ambiguous chapter → `low` + `null` (or LLM path in llm mode);
  omniscient → `null`. cue-words absent → graceful empty, no crash.
- Propagation: fields survive `wiki_preparation` into batch entries and appear
  in the generation prompt for `first_person`/`third_limited`, absent for
  `omniscient`.
- `pytest -q` green (baseline 735 passed, 31 skipped).

## Risk / effort

Impact medium (factual quality / encyclopedic neutrality). Effort
low-medium: Layer 1 is mechanical propagation; Layer 2's deterministic heuristic
and gate are the only genuinely new logic, and the LLM fallback reuses an
existing agent.
