---
name: triage-dead-links
description: Classify every dead wikilink reported by make check-wikilinks / check-wikilinks-series and route each to its real fix. Use when the wikilink gate fails, the user pastes dead-link output, or says "triage les liens morts", "fix the dead links", "check-wikilinks est rouge".
---

# triage-dead-links

A dead `[[link]]` has exactly four causes, each with a different fix in a
different place. Never "fix" one by deleting the link or blanket-adding it to
`red_links` — classify first.

```bash
make check-wikilinks BOOK=<book.yaml>      # output/<slug>/
make check-wikilinks-series BOOK=<tome>    # output/_series/
```

## The four classes

For each dead link `[[X]]` on page P:

1. **Canonicalization drift** — a page for the entity EXISTS under a variant
   spelling (case, accents, article, punctuation). Test: canonicalize both
   sides with `wiki_creator/canonicalize.py:canonical_key` — equal keys but
   different page stems = drift (`City_of_Emeralds` page vs `[[Emerald City]]`
   link is the archetype, STU-719). Fix at the **root**: the link and the page
   must both come out of `preferred_display_name` / the series `link_targets`
   map — a divergence means some writer bypassed it; find that writer, don't
   patch the one link. Series scope: also check stale-case filenames (STU-746).

2. **Missing page, entity known** — the target is in the registry /
   entities_classified but got no page (below notability, filtered before the
   batches, or `_failed`). Confirm with
   `python scripts/audit_run.py coverage --book <book.yaml>`. Fix is a
   decision, not a mechanism: raise the entity's notability in the book YAML,
   or accept it as a red link (class 4). A `_failed` page is a generation bug —
   file it.

3. **Missing page, entity unknown** — the target never survived extraction/
   resolution (an alias that never merged, a name NER missed). Trace with
   `python scripts/audit_run.py trace --book <book.yaml> --terms "X"`. This is
   an upstream bug (clustering, alias resolution, NER config) — file it with
   the trace as evidence; the dead link is only the symptom.

4. **Intentional red link** — mentioned-but-not-notable by design (an offstage
   name, a place never visited). Declare it in the book YAML
   `export.red_links` list, with the reason as a YAML comment. This list is an
   editorial statement, not a suppression dump — a class-1/2/3 link parked
   here is a bug hidden from the gate.

## Output

Table: link → page(s) it appears on → class → fix location (file or issue).
Then apply the class-4 YAML edits and any class-1 fixes whose root cause is
found; file issues (label `bug`) for class 2-failed/3; re-run the gate and
report the before/after count. The gate exits non-zero on any dead link, so
done = green or every remainder is a filed issue plus a declared red link.
