# Design: Noise Reduction in Entity Extraction

**Date:** 2026-03-04
**Problem:** The entity extraction stage produces too many noisy entities (735 for *Le Jeu de l'Ange*), inflating context size and polluting downstream stages with non-entities like `Merci`, `Salaud`, `E`, `S`, `objectai`.

---

## Root Causes

1. **Frontmatter chapters** — TitlePage contains author, translator, epub-maker names (not story entities).
2. **Single-letter / very short spans** — spaCy extracts `E`, `S`, `I`, `Or`, `Ah` from formatting artifacts.
3. **Lowercase verbs** — French conjugated forms like `objectai`, `plaidais-je`, `décevrez` slip through as PERSON entities because spaCy's French model struggles with dialogue-heavy text.
4. **Common words at sentence start** — Capitalized words like `Merci`, `Parfait`, `Salaud` are misidentified as proper names in dialogue.

---

## Solution: Two-Layer Filtering

### Layer 1 — Coarse filter in `entity_extraction.py` (no LLM cost)

Applied inside `extract_entities()` before adding any entity to the registry.

**Rule 1: Skip frontmatter chapters**
Chapters whose `id` (lowercased) matches any of: `titlepage`, `cover`, `colophon`, `copyright`, `toc`, `index`, `halftitle`, `dedication` are skipped entirely.

**Rule 2: Minimum mention length ≥ 3 characters**
Drops `E`, `S`, `I`, `M`, `Me`, `Ah`, `Or`, `II`, `B`, `A`, `P`.

**Rule 3: First character must be uppercase**
Drops `objectai`, `plaidais-je`, `décevrez`, `d'Escobillas` (starts with apostrophe/lowercase).
Check: `ent.text.strip()[0].isupper()`.

**Expected impact (estimated):**
735 → ~680 entities (removes ~55 obvious garbage entries).
Does not fix `Merci`-type noise — deferred to Layer 2.

### Layer 2 — Relevance flag in entity-resolution agent

The resolver LLM adds a `relevant: boolean` field to each resolved entity.

**Instruction added to `resolver.agent.yaml`:**
> Set `relevant: false` only for entries that are clearly not proper nouns — common words and interjections mistakenly extracted (e.g. `Merci`, `Parfait`, `Salaud`), grammar artifacts (`J'écrivis`), or punctuation fragments. Every real proper noun — even rarely mentioned — should be `relevant: true`. Do not filter places just because they're real-world geography.

**Output schema change:**
Each resolved entity gains: `"relevant": true | false`.

**Contract schema change (`entity-resolution.contract.yaml`):**
Add `relevant` as a required field per entity.

**Pipeline change:**
The wiki-generation stage filters out `relevant: false` entities before generating pages.

---

## Files Changed

| File | Change |
|------|--------|
| `scripts/entity_extraction.py` | Add frontmatter skip + length + uppercase filters in `extract_entities()` |
| `.studio/agents/resolver.agent.yaml` | Add relevance instruction + update output schema example |
| `.studio/contracts/entity-resolution.contract.yaml` | Add `relevant` field to per-entity schema |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Add `relevant: false` filter before wiki-generation |

---

## Non-Goals

- No French stopword list (maintenance burden, risk of false negatives).
- No token-count requirement for PERSON type (would drop valid single-name characters like `Balthazar`).
- No frequency threshold (hapax minor characters are valid wiki entries).
