# STU-234 — Copyright Validator: Design

**Date:** 2026-03-05
**Ticket:** [STU-234](https://linear.app/studioag/issue/STU-234/validateur-copyright-detection-de-verbatim-entre-output-wiki-et-texte)
**Status:** Approved
**Depends on:** STU-231 (wiki-generation templates — merged)

---

## Problem

INV-WC-01 stipulates the wiki must never reproduce more than 2-3 consecutive sentences from the source text. No automated mechanism currently enforces this. The LLM could produce verbatim passages without the contract catching it.

Legal concern: reproducing passages from a copyrighted book in a wiki is plagiarism, not fair use.

---

## Approach

**Deterministic script hook (Option A from ticket)**

A post-generation script `scripts/copyright_check.py` runs as a `hooks.on_stage_complete` on `wiki-generation`. If violations are found → `on_failure: reject` → ralph retries the stage with enriched feedback naming the problematic passages.

No LLM involved. Zero API cost.

---

## Algorithm

**Sliding window n-gram matching** (not LCS — LCS finds non-contiguous subsequences, which would produce false positives):

1. Read source text from `previous_outputs["epub-parse"]["chapters"]`
2. Tokenise source into words: lowercase, strip punctuation
3. Build a `set` of all 15-grams (tuples of 15 consecutive tokens) from source
4. For each wiki page, tokenise content the same way
5. Slide a 15-word window across wiki content; if any window is in the source set → violation

**Quote exemption:**
- Before tokenising wiki content, mask text inside `«»` or `""` guillemets that is ≤5 words
- Replace with neutral filler tokens so adjacent words don't form false 15-grams
- Short character quotes and citations are safe; only paragraphs get checked

**Threshold:** ≥15 consecutive words = violation (configurable via `--threshold` in test mode)

---

## Script Interface

The hook mechanism passes the stage output via `{{output | tojson}}` template substitution — not the full Studio script executor context. The script receives a **subset** of context:

**Input stdin** (piped from the hook command):
```json
{
  "pages": [{ "title": "...", "content": "...", "importance": "..." }],
  "epub_path": "books/le-jeu-de-lange.epub"
}
```

- `pages` comes from `{{output | tojson}}` (the wiki-generation output)
- `epub_path` comes from `{{input.file_path}}` — the book path is in `book.input.yaml`
- The script re-reads the epub directly using `ebooklib` to get source chapter text (same lib as `parse_epub.py`)

This avoids needing access to `epub-parse` previous output and makes the script self-contained.

**Output stdout — pass:**
```json
{
  "status": "pass",
  "checked_pages": 42,
  "violations": []
}
```

**Output stdout — fail:**
```json
{
  "status": "fail",
  "checked_pages": 42,
  "violations": [
    {
      "page_title": "David Martín",
      "wiki_passage": "Il prit le manuscrit entre ses mains tremblantes...",
      "source_passage": "Il prit le manuscrit entre ses mains tremblantes...",
      "chapter": "ch03",
      "consecutive_words": 18
    }
  ],
  "feedback": "Violations copyright détectées dans : [David Martín]. Reformule ces passages en paraphrasant — ne reproduis pas les mots exacts du livre source."
}
```

The `feedback` field is surfaced to ralph and injected into the retry prompt.

**Standalone test mode:**
```bash
python scripts/copyright_check.py --test
python scripts/copyright_check.py --test --threshold 10
```

In test mode, reads from fixture files (`tests/fixtures/`) instead of stdin.

---

## Pipeline Integration

`wiki-pipeline.pipeline.yaml` — add `hooks` block to `wiki-generation`.

Hook syntax (based on Studio `on_stage_complete` format):

```yaml
- name: wiki-generation
  kind: analysis
  agent: writer
  contract: wiki-generation
  ralph:
    max_attempts: 3
  hooks:
    on_stage_complete:
      - command: "echo '{\"pages\": {{output.pages | tojson}}, \"epub_path\": \"{{input.file_path}}\"}' | python scripts/copyright_check.py"
        on_failure: reject
  context:
    include:
      - input
      - previous_stage_output
```

The hook receives `{{output.*}}` (wiki-generation stage output fields) and `{{input.*}}` (book.input.yaml fields). The script is invoked as a plain Python subprocess — no runtime declaration needed in hook context.

---

## Acceptance Criteria

- [ ] `scripts/copyright_check.py` implemented with `--test` mode
- [ ] Detects sequences of ≥15 consecutive identical words against source text
- [ ] Integrated as `hooks.on_stage_complete` on `wiki-generation`
- [ ] Violations trigger reject → ralph retry with `feedback` naming the passages
- [ ] Short quotes (≤5 words between guillemets) are exempt
- [ ] On *Le Jeu de l'Ange*: no wiki page contains verbatim source passages

---

## Files Changed

| File | Change |
|------|--------|
| `scripts/copyright_check.py` | New |
| `.studio/pipelines/wiki-pipeline.pipeline.yaml` | Add `hooks.on_stage_complete` to `wiki-generation` |
