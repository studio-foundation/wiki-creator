# Oz series audit — issues found (2026-07-30, series run 1)

Source: `validate-wiki-run` audit of `output/_series/` after PR #364
(STU-719/740 canonicalization regen). Full entry in `audit_log.json`.
No Linear (STU team) access from this machine — file these manually.

---

## 1. Dead `[[Billina]]` links — stale-case export filename

**Severity:** High (broken links, easy fix)
**Labels:** `bug`, `claude:web`

`output/_series/characters/BILLINA.wiki` keeps its old all-caps filename
even though `series_assembly.json`'s `canonical_name` for that character
is now `"Billina"` (fixed by STU-719). Every other page links it as
`[[Billina]]`, so `check_wikilinks.py --series` reports 10 dead links:

```
Aunt_Em.wiki -> [[Billina]]
Dorothy.wiki -> [[Billina]]
Eureka.wiki -> [[Billina]]
Mr._Bunn.wiki -> [[Billina]]
Nome_King.wiki -> [[Billina]]
Ozma.wiki -> [[Billina]]
Scarecrow.wiki -> [[Billina]]
Tiger.wiki -> [[Billina]]
Tiktok.wiki -> [[Billina]]
Toto.wiki -> [[Billina]]
```

**Root cause:** `series_export.py::export_series` does
`shutil.rmtree(wiki_dir, ignore_errors=True)` then rewrites every page
fresh from `character.canonical_name` (`wiki_creator/series_pages.py`,
`page_filename()`). The page's own infobox (`|nom=Billina`) already
reflects the fixed name — only the filename is stale. Repo has
`core.ignorecase=true` (case-insensitive-preserving filesystem), which is
the likely reason a case-only rename didn't take effect on rewrite.

**Fix:** make series-export's rmtree+recreate path explicitly delete by
exact case before rewriting (or verify on a case-sensitive filesystem/CI
runner), then re-run `wiki series run` and confirm
`check_wikilinks.py --series` drops to 0.

---

## 2. Untranslated French prose on 5 English series pages

**Severity:** High (content-correctness, reader-facing)
**Labels:** `bug`, `claude:local` (needs re-running wiki-pages generation with real LLM access)

5 merged series character pages carry a paragraph or whole tome-section
written in French, inside a wiki whose `export.categories.language: en`:

| Page | Tome | Section |
|---|---|---|
| `characters/Saw-Horse.wiki` | Book 2 (Marvelous Land of Oz) | Biography |
| `characters/Old_Mombi.wiki` | Book 4 (Dorothy and the Wizard in Oz) | Biography |
| `characters/Wizard.wiki` | Book 5 (Road to Oz) | Biography |
| `characters/Lord_High_Chigglewitz.wiki` | Book 6 (Emerald City of Oz) | entire page |
| `characters/Nome_King.wiki` | Book 6 (Emerald City of Oz) | Personality + Trivia |

**Root cause:** traced to each tome's own
`processing_output/<tome>/wiki_pages.json` — the French text is already
there, i.e. a wiki-pages generation-stage LLM output that ignored the
declared language for these specific items. Pre-existing since the
original tome runs (commit `d9f8d92`, STU-709), **not introduced by
PR #364**. Run 1's per-tome audit (2026-07-28) already flagged this in
aggregate as `lang_fr_pct` (3.4% / 5.6% / 2.9% / 4.3% on books 02/04/05/06)
but never traced it to specific pages or filed it.

**Fix:** force-regenerate the affected wiki-pages items
(`wiki book pages <tome> --entities "Saw-Horse,Mombi,Wizard,Lord High
Chigglewitz,Nome King" --force`), and consider adding a post-generation
language-verdict check to the wiki-pages stage (same shape as the
existing per-unit verdict stages) so a language drift on an isolated item
fails that item instead of shipping silently.

---

## 3. Junk/generic-role entities outside PERSON scope

**Severity:** Medium (content quality, small blast radius)
**Labels:** `bug`, `claude:web`

STU-740 dropped stopword/generic-role/author-name junk entities, but
scoped to PERSON. The same class of junk survives in other entity types:

- `output/_series/locations/His_Majesty.wiki` — near-empty page
  (`* Name: His Majesty`), a generic role phrase misclassified as a
  LOCATION
- `output/_series/locations/Emperor.wiki` — same pattern
- `output/_series/events/The.wiki` — bare stopword title as an event

Plus one unmerged duplicate that predates STU-740 and isn't a generic-role
case: `output/_series/characters/Guardian.wiki` (Book 2) vs
`characters/Guardian_of_the_Gates.wiki` (Book 1) — same office/character,
never aliased together.

**Fix:** extend the STU-719/740 generic-role/stopword drop
(`wiki_creator/canonicalize.py::is_generic_role_name`) beyond PERSON to
LOCATION/EVENT, and add `Guardian` as an alias of `Guardian of the Gates`
in the relevant book's alias-resolution pass.

---

## Not filed (informational only)

Main_Page's reading order and main-characters list show raw slugs for
books 7-14 (e.g. `07-the_patchwork_girl_of_oz` instead of a title). Books
7-14 have book YAMLs and ground-truth corpora but were **never run**
(no `processing_output`, no epub committed) — this is expected fallback
behavior for an unrun tome, not a regression. Revisit once those tomes are
actually run.
