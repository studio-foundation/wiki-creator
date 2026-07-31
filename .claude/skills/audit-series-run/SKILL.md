---
name: audit-series-run
description: Audit a wiki-series run — the cross-tome merged wiki under output/_series/, not a single tome's pages. Use when the user says "audit série", "valide la series run", "audit the series wiki", or after a wiki-series run / series_assembly.json regeneration. Per-tome runs go to validate-wiki-run instead.
---

# audit-series-run

Audit the series-level wiki: `<series_dir>/series_assembly.json` and
`output/_series/` (one merged page per entity + the hub). Everything here is
reading artifacts — never run the pipeline or any live LLM stage.

Per-tome page quality is validate-wiki-run's job; this skill audits what only
exists at series scope: the cross-tome join, the canonicalization, the links,
the hub, the arc.

## Step 1 — Link integrity + delta

```bash
python scripts/check_wikilinks.py --book <any tome.yaml> --series
```

Report the dead-link count **as a delta against the previous series audit**
(from `audits/audit_log.json`, entries with `"book": "_series"`). The Oz
canonicalization fix netted -126 dead links in one run — the delta is the
headline metric, the absolute count alone is noise. Triage each remaining dead
link with the triage-dead-links skill (red link vs canonicalization drift vs
missing page) rather than eyeballing.

## Step 2 — Arc present (the green-null trap)

```bash
python -c "import json,sys; a=json.load(open('<series_dir>/series_assembly.json')); print('arc:', 'PRESENT' if a.get('arc') else 'NULL')"
```

`arc: null` **passes the contract and the run stays green** — the hub renders
its deterministic frame with no arc paragraph and exit 0 (the STU-709 shape,
fixed by STU-720's native `call`). A null arc after a real series run is a bug
to file, not a cosmetic gap. Also confirm the hub page actually contains the
arc paragraph, not just the frame.

## Step 3 — Cross-tome merge quality (STU-719/742/746)

The assembly joins every tome on the canonical key (`wiki_creator/canonicalize.py`).
Check, on the assembly + rendered pages:

- **Split identities**: the same character under two page names (accent/case/
  article variants that `canonical_key` should have merged). Compare page stems
  pairwise after canonicalization — any pair equal post-canonicalization but
  distinct on disk is a merge miss.
- **Wrong merges**: generic role names merged across tomes ("the guard" of tome
  2 absorbed into "the guard" of tome 5) — `is_generic_role_name` should have
  dropped them; a generic-role page in `_series/` is a leak.
- **Link retargeting**: every tome's `[[link]]` is rewritten through the
  assembly's `link_targets` map — a page whose body still links a tome-local
  alias that `_series/` spells differently produces the dead links of step 1.
- **Stale-case filenames** (STU-746): page filename case must match the
  canonical display name; a `.wiki` differing only in case from the expected
  stem is the bug class series run 1 surfaced.

## Step 4 — Coverage

Every entity in the series registry (`<series_dir>/registry.json`) that meets
notability should have exactly one merged page in `output/_series/`; every
tome's notable cast should be reachable from the hub. Report: registry entities
without a page, pages without a registry entry, tome counts on each merged
page's tome list vs the tomes the registry says the entity appears in.

## Step 5 — Ground truth, per tome

Series pages merge tome content, so a tome-scoped forbidden can legitimately
appear on a series page (the Nome King IS the arch-enemy by tome 3). Do **not**
run per-tome gt-validate against `_series/` pages and count hits as violations
— only flag content that is forbidden in **every** tome of the series, or
adaptation/film contamination (never canon in any tome).

## Step 6 — Verdict, log, PR

Same shape as validate-wiki-run steps 5–7: 3–4 sentence verdict with **one**
priority action; append an entry to `audits/audit_log.json` with
`"book": "_series"` (delta dead links, arc status, merge misses, coverage);
worktree + PR `audit(<series>): series run <N> — <verdict>`. Defect issues get
the `bug` label.
