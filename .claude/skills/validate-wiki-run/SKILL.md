---
name: validate-wiki-run
description: Audit a Wiki Creator generation run. Use whenever the user provides wiki_pages.json and/or batch_*.json files from the pipeline, names a book/tome to audit, or says "valide la run", "audit de run", "qu'est-ce qui fonctionne", "nouvelles pages". Produces a structured delta table, per-issue validation with upstream trace, and new Linear issues.
---

# validate-wiki-run

Audit one book's generation run: regression table, ground-truth validation,
upstream trace of every violation, coverage, weak entities, verdict, audit log,
PR. The deterministic checks live in committed, tested code (PR #371) — run
them, never re-implement them inline:

```bash
python scripts/audit_run.py metrics     --book <book.yaml>
python scripts/audit_run.py gt-validate --book <book.yaml>   # exit 1 on violations
python scripts/audit_run.py trace       --book <book.yaml> --terms "<term>" ...
python scripts/audit_run.py coverage    --book <book.yaml>
python scripts/audit_run.py batch-stats --book <book.yaml>
python scripts/audit_run.py providers
```

Every path resolves from the book YAML (`wiki_creator/paths.py`). If the user
dropped artifact files instead of naming a repo book, copy them into the book's
`processing_output/<slug>/` / `wiki_inputs/<slug>/` first — or pass
`gt-validate --pages <file>` for a bare page list.

This skill never runs the pipeline or any live LLM stage (CLAUDE.local.md hard
rule). Auditing is reading artifacts.

## Ground-truth corpus

Resolved from the audited book, never hardcoded — discover what exists:

```bash
ls -d {library,public_domain}/*/*/books/ground-truth/ 2>/dev/null
```

- Single-tome corpus (Narnia, TOG, Eragon in the demo set): flat JSONs in
  `books/ground-truth/`, describing tome 1.
- Multi-tome series (Oz 14 tomes, Alice 2 tomes): one
  `books/ground-truth/<NN-tome>/` subdirectory per tome, because the cast and
  above all the `forbidden` set are tome-specific (the Nome King is absent from
  Oz tomes 1–2, arch-enemy in 3 and 6 — STU-719). Field names stay `_book1` in
  every tome; the directory disambiguates. `audit_run.py` resolves the tome
  subdirectory automatically.
- Each corpus README states its provenance: **written against a generated
  roster** (Oz 1–6, Alice 01) or **from the text alone, never exercised against
  a run** (Oz 7–14, Alice 02). For text-only corpora, an entity with no page is
  a **coverage gap to report**, not a corpus defect.
- No corpus for this series → `gt-validate` exits 2; mark step 1b **n/a**
  explicitly in the audit, never skip it silently.

Corpus semantics (per-entity fields, matching rules, the constraints each
learned from an observed false positive/negative) are documented in the
add-book skill and enforced by `scripts/lint_ground_truth.py`. If a violation
smells like a corpus bug rather than a run bug, lint the corpus before filing
anything.

## Workflow

### Step 1 — Providers

`python scripts/audit_run.py providers` prints defaults + the five verdict
agents' pins (STU-624). Check the book YAML for per-stage overrides (e.g.
`generation.chapter_summary.llm_model`). Report the mix in the final table and
the audit_log `providers` field — **a content hallucination reads first against
the generation model** (3/5 "bugs" of one Alice audit were mistral quality;
re-measure a suspected defect on claude-code before filing a code bug).

### Step 1a — Metrics

`audit_run.py metrics` — per-page flags (empty/prefixed infobox, EPUB IDs,
Relations heading, `_failed`, language sniff) plus series-specific known
hallucination keywords and duplicate titles read from
`<series_dir>/audits/known_issues.json`:

```json
{
  "hallucination_keywords": {"Kiera Cass": "halluc_KieraCass", "Aelin Gallian": "halluc_Aelin"},
  "duplicate_titles": ["Captain Westfall", "Crown Prince"]
}
```

If the file is missing for a series with known cross-run issues, create it from
the previous audit entries (the TOG lists used to live inline in this skill).
The language sniff only surfaces cross-language contamination (both markers on
one page); expected language is the book's own `export.categories.language`.

### Step 1b — Ground-truth validation

`audit_run.py gt-validate --book <book.yaml>` on the fresh run. The checks and
their history (STU-294 full-phrase signals, STU-465 attribution suppression +
word-boundary match, STU-314 identity confusion + infobox alias cross-entity,
STU-717 structured relation slots with polarity) live in
`wiki_creator/audit.py` — read the code when a result surprises you, don't
reason from memory.

`REL_ABSENT` advisories are weak signals, never counted as violations —
`known_relations_book1` is not exhaustive by construction (STU-717).

Two other page sources, for corpus work rather than run audits:
- `--from-wiki` — pages rebuilt from the rendered `output/<slug>/` (gate 1: a
  clean committed run must yield zero violations);
- `--pages <file>` — an injected page list (gate 2: poisoned pages must be
  flagged).

### Step 1c — Upstream trace

For **every** violation from 1b:

```bash
python scripts/audit_run.py trace --book <book.yaml> --terms "<exact term 1>" "<term 2>"
```

The first stage containing the term is the responsible component:
- present from `entities_classified`/`relationships` → upstream (extraction or
  classification) injected it;
- present in a batch but not upstream → wiki-preparation introduced it
  (chapter_summaries, related_context);
- absent everywhere upstream → pure LLM hallucination at generation.

Document per violation: exact term, first file, component (the precise
script/agent, e.g. `wiki_preparation.py:build_related_context`), targeted
corrective action.

### Step 1d — Coverage

`audit_run.py coverage` — batch entities without a page, `_failed` pages,
entities classified but filtered before the batches.

### Step 1e — Weak entities

`audit_run.py batch-stats` — per-entity relation quality (untyped, missing
evidence, generic evolution, empty key_moments) plus `REL_TYPE_GT_MISMATCH`
(a target the corpus describes as antagonist carrying a positive type, STU-314).

### Step 2 — Regression table

All previously fixed bugs — report any regression:

| Criterion | Ref | Status |
|---|---|---|
| Zero `- `-prefixed infobox keys | STU-263 | ✅/❌ |
| Zero EPUB IDs in content | STU-265 | ✅/❌ |
| entity_type non-null everywhere | STU-266 | ✅/❌ |
| Known alias duplicates absent (known_issues.json) | STU-261/275 | ✅/❌ |
| Alias merges correct (e.g. Brullo/Master) | STU-276 | ✅/❌ |
| Zero cross-series, expected language, oriented relations | STU-278 | ✅/⚠️/❌ |
| Non-generic evolution, key_moments ≥50%, diverse types | STU-279 | ✅/⚠️/❌ |
| temporal_context propagated in chapter summaries | STU-271 | ✅/❌ |
| Zero known cross-series hallucination | STU-278 | ✅/❌ |
| Zero ground-truth violation | GT | ✅/⚠️/❌ |

Use ✅ (ok), ⚠️ (partial — specify), ❌ (regression), ➕ (new problem).

### Step 3 — Cross-run dashboard

Build the metric-per-run table from the series' `audits/audit_log.json` entries
plus this run's numbers — the log is the single source of truth, not this
skill. Rows: pages, infobox %, prefixed keys, EPUB IDs, expected-language %,
alias duplicates, hallucinations, GT violations, typed relations %, key_moments
%, non-generic evolution %.

### Step 4 — New problems (verified diagnosis)

For each problem absent from previous runs: one-line description, page/entity,
**verified cause from the 1c trace** (never a guess), responsible component,
targeted corrective action, Linear-worthy yes/no. Every issue filed for a
defect the audit detected (regression, hallucination, generation failure, real
GT violation) **must carry the `bug` label**; feature/refactor issues must not.
Before filing, check for duplicates with `list_issues` on the Wiki Creator
project — the up-to-date issue state lives in Linear, not in this skill.

### Step 5 — Verdict

3–4 sentences: pipeline state, what is validated, what still blocks, **one**
priority action for the next run.

### Step 6 — Audit log

Append (never overwrite) an entry to `<series_dir>/audits/audit_log.json`
(shared across a series' tomes; the `book` field names the tome):

```json
{
  "run": 0, "date": "YYYY-MM-DD", "book": "<slug>",
  "providers": {"generation": "", "verdict_agents": "", "chapter_summaries": ""},
  "pages_generated": 0, "infobox_pct": 0, "lang_expected_pct": 0,
  "alias_duplicates": 0, "hallucinations": 0,
  "gt_violations": [{"page": "", "signal": "", "cause": "", "first_seen_in": "", "component": "", "action": ""}],
  "coverage": {"batch_entities": 0, "pages_generated": 0, "missing": [], "failed": [], "filtered_before_batch": 0},
  "weak_entities": [],
  "regression": {"prefixed_keys": "✅", "epub_ids": "✅", "entity_type_null": "✅", "alias_duplicates": "✅", "cross_serie": "✅", "evolution_quality": "✅", "temporal_context": "✅", "ground_truth": "✅"},
  "verdict": "", "new_issues": []
}
```

### Step 7 — Audit PR

Always in a worktree — never a direct commit on `main`:

```bash
git worktree add -b audit/<series>-run<N> .worktrees/audit-<series>-run<N> origin/main
# copy the updated audit_log.json (and known_issues.json if touched) in, then:
git commit -m "audit(<series>): run <N> — <one-line verdict>"
git push -u origin HEAD && gh pr create --fill --base main
```

PR body: verdict, provider mix, issues filed (`STU-XXX`). A clean run still
gets its PR — the audit_log is the cross-run record feeding step 3.

## Output format

Steps in order: 1 (providers), 1a–1e, 2, 3, 4, 5, 6, 7. No introductory prose —
straight to results.
