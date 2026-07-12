# STU-464 — Chapter summary grounding check (design)

**Issue:** [STU-464](https://linear.app/studioag/issue/STU-464/chapter-summary-validator-doesnt-check-grounding-hallucinated)
**Date:** 2026-07-12
**Branch:** `arianedguay/stu-464-chapter-summary-validator-doesnt-check-grounding`

## Problem

`chapter_summaries.json` for Throne of Glass contained hallucinated bullets: invented
character names ("Duke of Niflaren" instead of Duke Perrington, "King Eadmund",
"King Davoth") and, in chapters 14/24/32, entirely fabricated scenes.

The validator stage of `chapter-summary-item.pipeline.yaml` runs
`scripts/chapter_summary_validator.py`, whose `validate_summary()` only calls
`check_temporal_context` and `check_bullets_not_empty`. It never checks that bullets
are grounded in the chapter's source text. So summaries with invented names pass
validation as long as `temporal_context` is set and bullets are non-empty.

(An LLM grounding agent, `.studio/agents/chapter-summary-validator.agent.yaml`, exists
but is orphaned — nothing invokes it, and its `{grounded, ungrounded_bullets}` output
shape doesn't match the validator contract's `{valid, errors, feedback}`.)

## Decision

**Option A — deterministic grounding heuristic in the validator script.** Chosen over
wiring the LLM agent (B) or upgrading the generator model (C):

- Cheap, deterministic, fully unit-testable, no LLM call, no API cost.
- Catches the invented-name class, which is the majority of the reported bugs.
- Aligns with the project norm of preferring deterministic checks and forbidding
  hardcoded word lists.

**Failure mode:** hard-fail. An ungrounded proper noun sets `valid: false` and adds the
names to feedback, so the existing RALPH loop (group `max_iterations: 3`) regenerates
with actionable feedback — consistent with how existing validator errors behave.

## Key finding: no plumbing needed

The issue assumed the chapter text would have to be plumbed into the validator stage.
It does not. The validator stage already declares `context.include: [input, previous_stage_output]`.
The engine's context propagation (`case 'input'`) dumps the pipeline `input` into
`additional_context`, and the pipeline `input` for `chapter-summary-item` is
`{chapter_id, chapter_title, chapter_content, max_bullets}` (see
`_chapter_summary_item_input` in `scripts/chapter_summary.py`).

`parse_payload` already loads `additional_context` into `ctx` and passes it to
`validate_summary` as `meta`. So `meta["chapter_content"]` is the chapter text —
already in hand. **No pipeline YAML change, no agent change.**

## Change surface

- `scripts/chapter_summary_validator.py` — add `check_grounding`, wire one line into
  `validate_summary`.
- `tests/test_chapter_summary_validator.py` — add grounding tests.

No other files. The orphaned agent YAML is left as-is (out of scope for this issue).

## Design of `check_grounding(summary, meta) -> list[str]`

1. `chapter_text = meta.get("chapter_content", "")`. If empty/whitespace → return `[]`.
   Degrade gracefully: without source text we cannot check grounding, and this keeps
   unit tests and older payloads working (matches the project's tolerance-of-missing-
   context norm).
2. Build a normalized token set from `chapter_text`: casefold, Unicode-aware, with
   punctuation and possessives stripped.
3. For each bullet in `summary_bullets`, extract **proper-noun candidates**:
   uppercase-initial tokens (Unicode-aware), length ≥ 2, not pure digits.
4. Normalize each candidate the same way as step 2. If the normalized candidate is
   **not** in the chapter token set → ungrounded.
5. Dedupe (preserving first-seen order), cap the reported list at 5, return a single
   error line: `❌ Noms/termes absents du texte du chapitre: Niflaren, Eadmund`.

Wired into `validate_summary` as one added line:
`errors += check_grounding(summary, meta)`. No signature change — `meta` already
carries `chapter_content`.

### Why this is word-list-free

The project forbids hardcoded vocabulary in scripts. This heuristic needs none: the
chapter text *is* the allowlist. Common sentence-initial words ("Elle", "The", "When")
self-filter because their casefolded form appears somewhere in the source text; real
names appear in the source; only invented proper nouns survive as flags. No stopword
list, no `cue_words` dependency.

### Normalization rules

- **Casefold**, Unicode-aware (accents preserved via `str.casefold`, not ASCII-folding).
- **Possessives / elisions:** strip English `'s`/`’s` suffix and French `d'`/`l'`/`j'`/
  `qu'` etc. elision prefixes before comparison.
- **Punctuation:** strip leading/trailing punctuation; keep internal hyphens and
  apostrophes inside a token (hyphenated/elided names compared whole).
- **Candidate filter:** first character is an uppercase letter (Unicode), token length
  ≥ 2, token is not purely digits/roman-numeral punctuation.

### Known blind spot (documented, not fixed)

A fabricated scene built entirely from *real* names (chapters 14/24/32) passes — every
token is grounded. This heuristic targets the invented-name class only. Semantic
fabrication detection would require Option B (LLM agent) or C (stronger generator),
both deferred.

## Tests

- Invented name absent from text → flagged, `valid: false`.
- Real name present in text → grounded, no error.
- Sentence-initial common word (appears lowercased in text) → not flagged.
- Possessive in bullet (`Celaena's`) vs bare name in text (`Celaena`) → grounded.
- Accented name (`Celaena`, `Nehemia`) → grounded.
- Missing/empty `chapter_content` → no grounding error (graceful pass).
- Full `validate_summary` on a hallucinated summary → `valid: false` with a grounding
  error present.

## Out of scope

- Regenerating the already-hand-corrected Throne of Glass data (issue notes downstream
  outputs should be regenerated once the pipeline fix lands — a separate operational step).
- Deleting/wiring the orphaned `chapter-summary-validator.agent.yaml`.
- Options B and C.
