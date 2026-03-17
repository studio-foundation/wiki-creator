# STU-271 — `chapter-summary`: add `temporal_context` (present / flashback)

## Problem

The `chapter-summary` contract does not distinguish present-narrative chapters from flashback chapters. Bullets from both are fed identically into the wiki biography prompt, producing incorrect timelines and violating INV-WC-02. It also blocks STU-232 (the "Avant les événements du livre" section).

## Design

### 1. Contracts

**`chapter-summary-item.contract.yaml`** and **`chapter-summary.contract.yaml`** — add two optional fields to the schema comment blocks:

```yaml
# temporal_context: "present" | "flashback" | "mixed" | "unknown"  (optional, default "unknown")
# flashback_anchor: str | null  — e.g. "5 ans avant les événements du ch.01"
```

No change to `required_fields` — both fields are optional so existing runs remain valid.

### 2. Agent prompt (`chapter-summary.agent.yaml`)

Extend the expected JSON output to include the two new fields:

```json
{
  "chapter_id": "...",
  "chapter_title": "...",
  "summary_bullets": ["..."],
  "temporal_context": "present" | "flashback" | "mixed" | "unknown",
  "flashback_anchor": "..." | null
}
```

The system prompt instructs the model to detect temporal context from:
- Grammatical tense shifts
- Temporal introduction formulas ("Des années plus tôt...", "Il se souvenait de...", "Years before...")
- Narrative register different from the main thread

Conservative rule: **when in doubt → `"unknown"`**.
`flashback_anchor` is only populated when `temporal_context` is `"flashback"` or `"mixed"`, otherwise `null`.

### 3. Extractive detection (`scripts/chapter_summary.py`)

**Cue words** — add `"flashback_cues"` list to `wiki_creator/cue_words/fr.json` and `en.json`. Example for French:
```json
"flashback_cues": ["des années plus tôt", "il se souvenait", "elle se souvenait", "des mois plus tôt", "bien avant"]
```
Example for English:
```json
"flashback_cues": ["years before", "years earlier", "she remembered", "he remembered", "months before", "long before", "had been"]
```

**`_detect_temporal_context(content, flashback_cues)`** — new private function. Lowercases content, checks for any cue match. Returns `"flashback"` on match, `"present"` otherwise. Returns `"unknown"` when `flashback_cues` is empty.

**`_summarize_chapter_extractive`** — calls `_detect_temporal_context` and appends `temporal_context` and `flashback_anchor: null` to the result dict. Receives `flashback_cues` via parameter (passed from callers).

**`summarize_chapter_from_item_result`** — when the LLM succeeds, passes through `temporal_context` and `flashback_anchor` from `item_result` (defaulting to `"unknown"` / `null`). When falling back to extractive, uses the heuristic.

**`summarize_chapters` / `summarize_chapters_incrementally`** — pass `flashback_cues` down from callers; `main()` loads them from `load_lang_config(language).get("flashback_cues", ())`.

### 4. `wiki_preparation.py` — `build_chapter_summary_context`

Each entry in the returned list gains a `temporal_context` field:

```python
{
    "chapter_key": chapter_key,
    "summary_bullets": bullets,
    "temporal_context": summary.get("temporal_context", "unknown"),
}
```

No filtering at this layer — all chapters pass through. Separation happens in the prompt layer.

### 5. `generate_wiki_pages.py` — prompt rendering

Split `chapter_summary_block` into two labeled sections:

**Present block** — chapters where `temporal_context` in `{"present", "mixed", "unknown"}`:
```
## Chapter summary context
  - Chapter: Ch01
    - Celaena arrived at the castle...
```

**Backstory block** — chapters where `temporal_context == "flashback"`:
```
## Backstory context (flashback chapters — events before the main narrative)
  - Chapter: Ch03
    - Five years earlier, Celaena trained under Arobynn...
```

Each block is omitted from the prompt if it has no content.

## Acceptance Criteria

- [ ] `chapter-summary-item.contract.yaml` and `chapter-summary.contract.yaml` include `temporal_context` and `flashback_anchor` in comments
- [ ] Agent system prompt requests detection and returns both new fields
- [ ] `_detect_temporal_context` uses `flashback_cues` from `cue_words/<lang>.json` (no hardcoded lists in scripts)
- [ ] Extractive path sets `temporal_context` and `flashback_anchor: null` on every summary dict
- [ ] LLM path passes through `temporal_context` / `flashback_anchor`; fallback path uses heuristic
- [ ] `build_chapter_summary_context` propagates `temporal_context` in each entry
- [ ] `generate_wiki_pages.py` renders two separate blocks in the prompt
- [ ] `pytest -q` passes
