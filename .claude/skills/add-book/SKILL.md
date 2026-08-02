---
name: add-book
description: Import one EPUB into the wiki-creator corpus and make it runnable — pick the right root (public_domain for Project Gutenberg, library otherwise), scaffold and author its book YAML from the parsed text, and write its ground-truth corpus under books/ground-truth/. Use when the user says "/add-book", "ajoute ce livre", "add this epub", "importe cet epub", or drops an .epub path and asks for it to be set up. Ends at a book ready to run; it never runs the pipeline.
---

# add-book

Turn an EPUB into a book the pipeline can build: EPUB in the right corpus root, a
book YAML whose reader-authored fields were decided against the actual text, and a
ground-truth corpus the `validate-wiki-run` skill can audit against.

Modelled on how *Alice's Adventures in Wonderland* was added
(`public_domain/lewis_carroll/alice/`) — read that book's YAML and its
`books/ground-truth/README.md` as the reference shape before starting.

## Hard rule — no live LLM run

This skill costs zero LLM calls. The only commands it runs are `wiki book add`
and `scripts/parse_epub.py`, both deterministic. **Never** `make run`,
`studio run ... --live`, `wiki book run/extraction`, or any stage script against a
real provider — not even "just to see the roster". Every judgement below is made by
reading the parsed text yourself. If a field genuinely needs a measured number
(an NER sweep, a recall figure), leave the field at its default, say so in a
comment, and tell the user what run would produce the number.

## Step 0 — Worktree

Work in an isolated worktree off `main`, per the project norms:

```bash
git worktree add ../wc-add-<series-slug> -b add-book/<series-slug> origin/main
```

## Step 1 — Pick the corpus root

```bash
python - <<'PY'
from pathlib import Path
import zipfile, re
EPUB = "<path/to.epub>"
from wiki_creator.book_import import read_metadata
title, author = read_metadata(EPUB)
blob = b"".join(
    zipfile.ZipFile(EPUB).read(n)
    for n in zipfile.ZipFile(EPUB).namelist()[:12]
).decode("utf-8", "ignore")
gutenberg = "project gutenberg" in blob.lower()
print(f"title  = {title}\nauthor = {author}\ngutenberg markers = {gutenberg}")
PY
```

- **`public_domain/`** — Project Gutenberg markers present, or the work is
  otherwise verifiably public domain (author long dead, no live copyright). This
  root ships its EPUBs *and* its rendered `output/` in git: it is the demo corpus.
- **`library/`** — everything else. EPUBs and every derived artifact are
  gitignored; only the YAML is committed.

If the author/series directory already exists under either root, that decision is
already made — the new tome joins it, whatever the metadata says.

**A Gutenberg epub is not always one book.** Many classic-author volumes (a
Maupassant/Chekhov/de Maupassant-style *Œuvres complètes*) bundle several
stories after the one the user actually wants — check the parsed chapter list
(step 3) for headings that don't belong to the target title before authoring
anything. If it's an anthology, trim the epub down to the target story alone
at the zip/XML level before proceeding:

1. `ebooklib.epub.read_epub` + `book.spine`/`book.get_item_with_id` to find
   which spine file(s) hold the target story and which hold the rest.
2. If the story shares a spine file with other content (chapters split by
   internal `<div id="pgepubid...">` anchors within one packed HTML file, not
   separate files), parse that file's body, keep everything up to the next
   story's heading anchor, drop the rest (`lxml.etree`, not string slicing —
   preserves the markup).
3. Drop any spine file that is *entirely* other stories from the manifest
   and spine (`content.opf`), and remove it from the zip.
4. Keep the Project Gutenberg header/footer boilerplate spine files
   untouched — redistribution terms require them.
5. Rewrite with plain `zipfile` (preserve `mimetype` as the first entry,
   uncompressed) — **do not** round-trip through `ebooklib.epub.write_epub`,
   which can crash on `toc.ncx` regeneration for a real-world epub whose
   nav entries never got a `uid` (hit on `pg10746`; reproduces even
   unmodified, read-then-write with zero edits).
6. Re-parse with `scripts/parse_epub.py` and confirm the chapter count now
   matches only the target story (plus its Gutenberg boilerplate chunks).

## Step 2 — Import

`entity_slug` derives ugly slugs from long titles
(`Alice's Adventures in Wonderland` → `alice_s_adventures_in_wonderland`), so
**always pass `--author` and `--series` explicitly**, short and human. Match the
sibling convention already in that root (`lewis_carroll/alice`,
`sarah_j_maas/throne-of-glass`).

```bash
wiki book add <path/to.epub> --dest public_domain \
  --author lewis_carroll --series alice --number 01 --dry-run
```

Read the dry-run output, then drop `--dry-run`.

- `--number` is **reading order**, not publication order; an interquel is `04.5`
  (`discover_series_books` sorts it between `04_` and `05_`).
- A new tome in an existing series: same `--author`/`--series`, next `--number`.
- Do not use `--llm` — it is one LLM call for a `novel_summary`. Ask first if the
  user wants it.

## Step 3 — Parse the text (LLM-free)

Everything below is decided against the text the pipeline itself reads. Produce it
with the parse stage alone — no spaCy, no NER, no network:

```bash
python - <<'PY' | python scripts/parse_epub.py > /dev/null
import json, pathlib
y = pathlib.Path("public_domain/lewis_carroll/alice/books/01-alice_in_wonderland.yaml").read_text()
print(json.dumps({"additional_context": y, "previous_outputs": {}, "all_stage_outputs": {}}))
PY
```

Writes `<root>/<author>/<series>/processing_output/<NN-slug>/epub_data.json` —
chapters with their full text. That file is the sole source of truth for steps 4
and 5. Sanity-check it first: chapter count, that Gutenberg boilerplate is gone,
that chapter splitting is not one giant merged chapter (packed spine items, see
`scripts/CLAUDE.md`).

A candidate cast, cheaply, without NER:

```bash
python - <<'PY'
import json, re, collections
d = json.load(open("<...>/processing_output/<NN-slug>/epub_data.json"))
text = "\n".join(c["content"] for c in d["chapters"])
names = re.findall(r"\b(?:the |The )?[A-Z][a-z]+(?: [A-Z][a-z]+)?\b", text)
for n, k in collections.Counter(names).most_common(80):
    print(f"{k:5} {n}")
PY
```

Frequency is a candidate list, not the roster — confirm every entry by reading its
occurrences.

## Step 4 — Author the book YAML

`wiki book add` writes only the mechanical fields. The load-bearing ones are
reader decisions (CLAUDE.md, "Config Is Read By People Who Know Books") — answer
each from the novel, and **omit any field you cannot answer** rather than guess a
value that then looks measured.

| Field | The question about the novel | How to answer from the text |
|---|---|---|
| `ner.invented_names` | Are this book's names invented, or ordinary real-world names? | Wonderland/Oz/Alagaësia → `true`. A realist novel with ordinary names → leave absent (`false`). |
| `ner.threshold` | — | Only with `invented_names: true`. `0.3` is the measured default (STU-535). Do not invent a different number. |
| `ner.character_names` | Is any of the cast named by a **common noun** (`the Hatter`, `the Dormouse`, `the Cat`)? | List them verbatim; they are matched literally and typed PERSON. This is the single highest-value field for a talking-creature cast — GLiNER under-detects common-noun names. Include the short form the text actually uses (`Rabbit` alongside `White Rabbit`) with its occurrence count in a comment. |
| `min_mentions_absolute` | How long/dense is the book? | `3` for a short novel; raise for a long one where 3 mentions is noise. |
| `coref` | — | `false` unless the user asks; it needs the `[coref]` extra and a GPU. |
| `generation.register` | In what voice should the wiki read? | One sentence naming tone, period and stance, written after reading a page of the prose. |
| `generation.narrative_arc.weights` | Is the book front-loaded, episodic, or climax-heavy? | Default `[0.25, 0.50, 0.25]`. Episodic middle (Alice) → `[0.15, 0.70, 0.15]`. Justify in a comment naming the book's shape. |
| `generation.narrative_arc.max_events` | How many self-contained set pieces are there? | Roughly one per distinct episode; 12 episodic chapters needed 21 for Alice. |
| `generation.*.sections` / `max_tokens_per_page` | — | Copy the Alice tiering unless the book calls for different sections. |
| `export.categories.language` / `labels` | What language does the wiki render in? | The book's own language. |
| `aliases` | What short name will the user type? | e.g. `aliases: [tog]`. |
| `export.red_links` | Which `[[links]]` are deliberately unresolved? | Leave absent until `make check-wikilinks` reports one. |

Comment convention: one comment per non-obvious value, naming the *reason from the
book* (and the ticket if there is one). Never write a comment that implies a
measurement you did not run.

## Step 5 — Write the ground-truth corpus

**Read the judge before writing the corpus.** The code that will evaluate it is
`wiki_creator/audit.py` (`validate_ground_truth`) and `wiki_creator/ground_truth.py`
— alias matching is bidirectional substring, forbidden relations need both names
plus a polarity word, signals are literal comma-free substrings. A corpus written
without reading the validator *looks* right and false-positives.

For a **multi-tome series**, write a shared SPEC (the constraints below plus the
series' own failure modes — film/adaptation inventions, cross-tome bleed,
offstage promotion) and delegate one subagent per tome, each grep-verifying
every fact against its own tome text: *if you can't find it in the text, it is
not canon.* The gates in step 6 are the safety net for delegated facts, not
trust.

Location, resolved from the book:

```
<root>/<author>/<series>/books/ground-truth/*.json           # single-tome series
<root>/<author>/<series>/books/ground-truth/<NN-tome>/*.json # multi-tome series
```

Multi-tome gets a subdirectory per tome because the `forbidden` set is tome-specific
(a villain absent from tome 1 is the arch-enemy in tome 3). Field names stay
suffixed `_book1` in every tome — the loader hardcodes them; the directory
disambiguates.

One file per **cluster** of 2–5 related entities (household, faction, location
set), plus a `minor_and_offstage.json` for names that are spoken about but never
appear. Per-entity schema (nested form, keyed by lowercase slug; the flat form
`{"entity": "...", ...}` is also accepted):

```json
{
  "dinah": {
    "canonical_aliases_book1": ["Dinah"],
    "known_facts_book1": ["…verified sentence…"],
    "known_relations_book1": {"Alice": "Her mistress; …"},
    "forbidden_book1": {
      "sequel_only": ["Dinah's kittens"],
      "not_in_this_book": ["Dinah appears in Wonderland"]
    },
    "hallucination_signals": ["Dinah's kittens", "Dinah said"],
    "identity_confusion_forbidden": []
  }
}
```

Five constraints, each learned from an observed false positive or false negative:

1. **Verify every fact against `epub_data.json`, never against memory.** Grep the
   phrase. A wrong fact in the corpus turns a correct page into a violation. Adaptations
   and sequels contaminate memory hardest: the text says "the Hatter", not "the Mad
   Hatter".
2. **Aliases are matched by bidirectional substring** (`a in title or title in a`).
   Keep them short, untranslated and discriminating. When one alias contains another
   (`Mouse` ⊂ `Dormouse`), put both entities in the **same file, shorter-binding one
   first**, and give the shorter one a non-contained alias (`the Mouse`).
3. **`forbidden` entries are discriminating phrases, not bare tokens.** The loader
   drops `len <= 4`, which is not enough: `Aren` matches `aren't`, `Bree` matches
   `breeze`. Write `Aren, Brom's ring`.
4. **A forbidden *relation* must name both characters and the link type** — the
   structured check fires only when a forbidden phrase names the page entity, the
   infobox slot target, and a polarity word (`friend`/`ally`/`enemy`/`married`/`sister`…).
   `Bill is an enemy of Alice` fires; `Bill` alone does not.
5. **`hallucination_signals` are literal substrings, comma-free, never just the
   entity's own name.** A signal written as prose ("Any appearance of the Dodo
   outside chapter III") degrades to the character's name and fires on every page.

Then decide the corpus's own scope, and **write the omissions down**: an entity
whose name is a bare numeral or a common word (Alice's three gardeners: Two, Five,
Seven) must be left out — as aliases they poison the attribution lookup and silently
suppress hits elsewhere. Omitted-with-a-reason beats a silent gap.

Finish with a `README.md` beside the JSONs, in the Alice shape:
- table of file → entities, and the total count vs the book's whole named cast;
- **what this corpus is built to catch** — the concrete failure modes (sequel
  contamination, adaptation contamination, biography invented from outside the book,
  offstage names promoted to characters);
- the deliberate choices and omissions, with their reason;
- verified behaviour, if any run has been audited against it — otherwise state
  plainly that the corpus is derived from the text alone and never yet exercised,
  so a missing page is a coverage gap to report, not a corpus defect.

## Step 6 — Gate the corpus

Three mechanical, LLM-free gates, in order. The committed tools (PR #371) do
the work — never re-implement them inline.

**Gate 0 — lint** (catches every rule above a machine can see):

```bash
python scripts/lint_ground_truth.py --book <book.yaml>
```

Every `FAIL` is fixed before moving on. `WARN` is fixed *or* justified in the
README. Facts are the part no linter can check — spot-check each
`known_facts_book1` entry by grepping a distinctive phrase against
`epub_data.json`.

**Gate 1 — zero false positives.** If the book has a rendered run (committed
`output/<slug>/` or a fresh one on disk), the corpus run against it must yield
**zero violations** — every hit on a clean run is a corpus bug, fix it by hand:

```bash
python scripts/audit_run.py gt-validate --book <book.yaml> --from-wiki
```

No run exists → state it in the README (corpus derived from the text alone,
never exercised) and skip; do not fake the gate.

**Gate 2 — teeth.** Write 2–3 poisoned page records embodying the exact failure
modes the corpus exists to catch (the forbidden relation, the sequel/adaptation
contamination, the identity confusion), and confirm the corpus flags them:

```bash
python scripts/audit_run.py gt-validate --book <book.yaml> --pages poison.json
```

A corpus that passes gate 1 but not gate 2 has no teeth — tighten the forbidden
phrases/signals until the poison fires, then re-run gate 1.

## Step 7 — Commit

```bash
git add <root>/<author>/<series>/books
git commit
```

Note what is and is not tracked: `library/**/*.epub` is gitignored (YAML only),
`public_domain/` ships its EPUBs. `.claude/` is in `.gitignore` but the skill
files themselves are force-added and tracked — a skill change is still a
separate commit, never mixed with the book.

## Step 8 — Hand back

Report, terse:
- where the EPUB and YAML landed, and which root, with the reason;
- the reader-authored YAML fields chosen and what in the text decided each;
- the ground-truth entity count, the omissions, and the linter result;
- **what is not verified**: no pipeline run happened, so the roster, the page set
  and the extraction quality are all unmeasured. Name the command the user would
  run (`wiki book run <alias>`) and leave running it to them.
