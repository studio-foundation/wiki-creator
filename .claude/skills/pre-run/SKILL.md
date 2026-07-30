---
name: pre-run
description: Pre-flight checklist before a real (paid, LLM) pipeline run on a book — backup, cache inventory, provider mix, smallest-slice choice. Use when the user says "prépare la run", "pre-run", "je vais lancer une run", "what will this run cost", or asks to get a book ready to run. Ends by handing the command to the user; it NEVER launches the run.
---

# pre-run

A real run costs an hour and hundreds of LLM calls, and overwrites gitignored
artifacts the last run produced. This skill does everything cheap and
deterministic *around* the run, then stops. **Launching the run is the user's
move, always** (CLAUDE.local.md hard rule) — end by printing the exact command,
never by executing it.

## Step 1 — Backup

Snapshot before anything else; the bak/new delta is what makes the run
auditable afterwards:

```bash
cd <root>/<author>/<series>
mkdir -p bak_<DD-MM-YY>
cp -r processing_output wiki_inputs output registry.json character_graph.json bak_<DD-MM-YY>/ 2>/dev/null
```

(`registry.json`/`character_graph.json` may not exist on a first run — fine.)

## Step 2 — Cache inventory

Report what will replay vs what will be paid for again:

```bash
ls .studio/runs/map-cache/ 2>/dev/null | wc -l     # engine per-item resume (GLOBAL, all books)
ls <processing_output>/<slug>/{section_filter,alias_adjudication,entity_status,entity_affiliation,entity_species}.json 2>/dev/null
ls <processing_output>/<slug>/extraction_cache.json 2>/dev/null
```

- Intact caches make a plain re-run cheap on the LLM side; deterministic
  compute (extraction, co-occurrence) re-executes regardless.
- Caches are keyed on item/roster + prompt fingerprint, **not** provider — a
  provider change with warm caches replays the old provider's outputs silently.
  Provider comparison → use the compare-providers skill, which clears the right
  set.
- A cache the user just deleted costs its full price — say which ones are
  missing and roughly what that re-buys (per-chunk map items, 5 verdicts).

## Step 3 — Provider mix

```bash
python scripts/audit_run.py providers
```

Plus the book YAML's per-stage overrides. State the mix that will produce this
run — the audit will need it (`providers` field of the audit log), and a
quality problem reads first against the generation model.

## Step 4 — Smallest slice

Confirm the run about to be paid for is the smallest one that answers the
question (CLAUDE.local.md order): suite/goldens → one stage
(`studio replay <run-id> --restart --stage <stage>` on run ids from
`studio status`, or a single pipeline via `wiki book extraction <alias>`) →
entity slice (`wiki book pages <alias> --entities "X" --force`) → chapter slice
(`WIKI_MAX_CHAPTERS=N` — never measure a premise on a subset, STU-497/539) →
full run only when the deliverable is the full chain.

## Step 5 — Hand off

Print, in one block: the backup path created, the cache summary (replays vs
re-buys), the provider mix, and the exact command chosen in step 4. Then stop.
After the run finishes, the user flow is: validate-wiki-run (audit), then
`make sync-push` (share the paid artifacts with the other machine —
`WIKI_SYNC_REMOTE` must be set).
