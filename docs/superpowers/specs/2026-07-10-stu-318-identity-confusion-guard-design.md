# STU-318 — Identity-confusion guard for generated PERSON pages

**Linear:** [STU-318](https://linear.app/studioag/issue/STU-318/confusions-identitaires-llm-validation-post-generation-canonical-name)
**Date:** 2026-07-10
**Status:** Design approved, ready for planning

## Problem

Run 15 produced three *pure LLM hallucinations* — identity confusions between
distinct characters, with no upstream file (entities_classified, relationships,
batches) containing the bad association:

1. **Nehemia** described as "de son vrai nom Yrene Astellaris" (Yrene is a
   book-6 character) — *prose-level* confusion.
2. **Verin** infobox `nom: Kaltain`, `date_de_naissance: Années 800 EC` — Verin
   is not Kaltain Rompier — *infobox-level* swap.
3. **Kaltain Rompier** described as "confidente de la reine Elena Havilliard du
   royaume de Ruhn" (Elena is an ancient legend; "Ruhn" does not exist in the
   series) — *prose-level* confusion.

The current generator force-sets `title`, `importance`, and `entity_type` from
the batch entity ([`parse_response`](../../../scripts/generate_wiki_pages.py)),
but the LLM-authored infobox `nom` field and biography prose are unvalidated —
which is exactly where the confusions live.

## Scope

This issue ships a **small, targeted guard** — detection + correction after
generation. A deeper fix (page templates that make identity fields
*deterministic* so the LLM never authors them) is intentionally **out of scope**
and tracked as a separate issue. This spec closes the highest-value, lowest-risk
slice now.

### In scope

A post-generation identity guard in `scripts/generate_wiki_pages.py`, running
**only for `entity_type == "PERSON"`**, structured as a sibling of the existing
`forbidden_names` retry block. Two detections:

- **Self-mismatch** — the generated infobox `nom` shares no token with the
  entity's own `{canonical_name} ∪ aliases`.
- **Sibling-swap** — the generated infobox `nom`, or a value in the infobox
  `alias` field, exactly equals a *different* batch entity's canonical_name.

On detection: **retry once**, then **force-correct** (keep the page — do not
stub it).

### Out of scope (deferred, conscious decisions)

- **Page templates / deterministic identity fields** → separate issue. This is
  the real root-cause fix (prevention over detection); it touches `build_prompt`,
  `parse_response`, the `wiki_pages.json` shape, `wiki_export.py`, and many
  tests, so it gets its own spec.
- **Promoting "Yrene Astellaris" into code-enforced `validation.forbidden_names`**
  (would let the existing retry loop catch case #1 in prose). Dropped from this
  issue.
- **`nehemia.json` GT edit** (issue action #2 — add "Yrene Astellaris" to
  `identity_confusion_forbidden`). The GT files feed the human `validate-wiki-run`
  audit skill, not pipeline code. Dropped from this issue by explicit decision.

Cases #1 and #3 are *prose-level* confusions inside the LLM-authored biography;
this guard does not target them. The existing `forbidden_names` guard remains the
mechanism for prose, and the template refactor will shrink the prose surface
further. This guard targets case #2 (the infobox swap) and any future
infobox-`nom` confusion.

## Design

### 1. Pure detection function

```python
def _check_identity_confusion(
    page: dict,
    entity: dict,
    sibling_canonicals: set[str],
) -> list[str]:
    """Return human-readable identity issues; empty list means clean.

    PERSON-only. Caller is responsible for skipping non-PERSON entities.
    """
```

Behaviour:

- **Normalization** — a shared `_normalize_identity(s)` helper: lowercase, strip
  accents, strip punctuation, split into a token set. Reused by both detections.
- **Self-mismatch** — let `nom = infobox_fields.get("nom")`. If `nom` is present
  and non-empty, require at least one shared token between `tokens(nom)` and
  `tokens(canonical_name) ∪ ⋃ tokens(alias)` over the entity's known aliases.
  No overlap → append an issue string naming the offending `nom`.
  - If `nom` is absent/empty, no self-mismatch issue (nothing was authored to be
    wrong; the infobox extractor / template layer handles absence elsewhere).
- **Sibling-swap** — build the normalized-token sets of *other* batch entities'
  canonical_names (`sibling_canonicals`, already excluding this entity). If
  `tokens(nom)` **shares ≥1 token** with a sibling's canonical tokens, **or** any
  comma-split value in the infobox `alias` field does, append an issue string
  naming the swapped-with entity. Overlap (not exact set-equality) is required:
  the bad `nom: "Kaltain"` (`{kaltain}`) must match the sibling canonical
  "Kaltain Rompier" (`{kaltain, rompier}`), whose sets are not equal.
  - To avoid noise from generic shared tokens (e.g. "princess", "lady"), the
    swap-check ignores tokens that also appear in *this* entity's own
    `{canonical_name} ∪ aliases` — only a token that is distinctive to the
    sibling counts as a swap signal.

Return the accumulated issues. The self-check catches *any* wrong `nom` (including
invented names no sibling set can know); the swap-check adds precise diagnostics
("swapped with Kaltain") and reaches into the `alias` field the self-check does
not inspect. They overlap on Verin→Kaltain but are not redundant.

### 2. Guard flow

In [`_run_generation_for_entity`](../../../scripts/generate_wiki_pages.py), add a
block parallel to the `forbidden_names` retry, gated on
`entity.get("type") == "PERSON"`:

1. Run `_check_identity_confusion`. If clean, no-op.
2. If issues found: log a warning, **retry once** via a fresh
   `_run_wiki_page_item` (same re-strip-relations handling as the existing block).
3. Re-check. If still issues → **force-correct**:
   - `page["infobox_fields"]["nom"] = entity["canonical_name"]`
   - strip any sibling-canonical value from the infobox `alias` field
   - write a debug artifact via `_save_generation_debug_artifact`
   - tag `page["_identity_corrected"] = True`
   - log a warning; **return the (corrected) page** — never a stub.

Force-correct over stub is the right tradeoff: we already own the correct value
(`canonical_name`), so discarding a probably-good biography over one bad field
would throw away signal to punish a typo.

### 3. Threading `sibling_canonicals`

`main` builds, per batch, `sibling_canonicals_by_entity` — or more simply, for
each entity computes the set of *other* entities' canonical_names in that batch —
and passes `sibling_canonicals` into `_run_generation_for_entity` (new optional
param, defaulting to an empty set so existing callers/tests are unaffected).

## Testing

Unit tests for `_check_identity_confusion`:

- Verin → `nom: Kaltain` where the sibling canonical is "Kaltain Rompier":
  flagged by **both** checks (exercises token-overlap, not set-equality).
- Generic shared token: entity "Princess Nehemia" alias, `nom: "Princess X"`
  where a sibling is "Princess Y" — the shared "princess" token must **not** by
  itself trigger a swap (distinctive-token rule).
- Verin → `nom: <invented non-sibling>`: flagged by self-check only.
- Clean PERSON (`nom` matches canonical or an alias): no issues.
- Multi-token canonical ("Nehemia Ytger") with `nom: "Nehemia"`: token overlap →
  no issue.
- Non-PERSON entity: caller skips (assert the guard flow does not run / returns
  early) — a translated title like `nom: "Le Roi d'Adarlan"` vs canonical
  "The King of Adarlan" must **not** false-positive because it is never checked.
- Alias-field swap: `alias` contains a sibling canonical → flagged.

Guard-flow test:

- After a persistent mismatch, assert the page is **kept** (not a stub),
  `infobox_fields["nom"] == canonical_name`, `_identity_corrected is True`, and a
  debug artifact was written.

Run `pytest -q` and `mypy wiki_creator/` (script lives under `scripts/`, but keep
types clean) before claiming completion.

## Follow-up issue

Tracked as [STU-436](https://linear.app/studioag/issue/STU-436/page-templates-make-wiki-page-identityinfobox-fields-deterministic).

**Title:** Page templates: make wiki-page identity/infobox fields deterministic
(prevent identity confusion at the source)

**Gist:** Generalize STU-319's force-set-from-batch approach into a per-
`entity_type` page template where identity/infobox slots (`nom`, `alias`, `type`)
are bound by code from the batch entity, and the LLM only fills descriptive prose
sections. Makes the infobox class of identity confusion unrepresentable rather
than merely detected. Touches `build_prompt`, `parse_response`, `wiki_pages.json`
shape, `wiki_export.py`, and tests. Related to STU-318 and STU-319.
