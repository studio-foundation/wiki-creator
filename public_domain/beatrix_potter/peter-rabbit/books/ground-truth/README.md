# Ground truth — *The Tale of Peter Rabbit* (book 1)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against
`processing_output/01-peter-rabbit/epub_data.json`, the text the pipeline itself reads — never
against memory. This book was added as a small, cheap, everything-in-one-chapter fixture to
exercise the pipeline end to end without burning many tokens; the whole story is one un-chaptered
scene, ~5,400 characters.

## Files

| File | Entities |
|---|---|
| `peter.json` | Peter |
| `mcgregor.json` | Mr. McGregor |
| `rabbit_family.json` | Mrs. Rabbit, Flopsy, Mopsy, Cotton-tail |
| `garden.json` | McGregor's garden |

7 entities. The book's whole named cast except Mrs. McGregor and Benjamin Bunny (see below).

## What this corpus is built to catch

1. **Sequel contamination** — Beatrix Potter wrote real sequels featuring this cast: *The Tale of
   Benjamin Bunny* (Peter and Benjamin go back for his lost clothes) and *The Tale of the Flopsy
   Bunnies* (Flopsy marries Benjamin Bunny). Neither event is in this book.
2. **Adaptation contamination**, mostly from the 2018 film: "Thomas McGregor" (a nephew character
   invented for the film), McGregor dying of a heart attack, Peter's jacket recolored red (the
   text says blue), and the modern one-word spelling "Cottontail" (the book always hyphenates
   "Cotton-tail").
3. **The chase resolving the wrong way** — Mr. McGregor never catches, injures, or forgives Peter
   in the book; he only ever loses him.
4. **Offstage names promoted to on-page characters** — see below.

## Deliberate omission: Mrs. McGregor and Benjamin Bunny

Both are named and both are spoken about ("put in a pie by Mrs. McGregor", "his cousin, little
Benjamin Bunny"), but each occurs exactly **once** in the text — below `min_mentions_absolute: 2`
in the book YAML, so the pipeline does not produce a page for either. Unlike Alice's
`minor_and_offstage.json` (which covers named characters who *do* get pages despite never
physically appearing), there is no page here to hold ground truth against. Instead, the failure
mode they represent — an offstage, below-threshold name getting promoted into an on-page
character — is asserted as `forbidden`/`hallucination_signals` entries on `peter.json` and
`mcgregor.json` ("Benjamin Bunny helps Peter", "Mr. McGregor's nephew").

## Deliberate omission: unnamed characters

The old mouse, the white cat and the "friendly sparrows" are never given proper names in the
text — only common-noun descriptions. They have no stable alias to write ground truth against and
are left out entirely, same reasoning as Alice's three gardeners (a common-noun alias like "the
cat" or "the mouse" would poison the substring lookup against unrelated prose elsewhere).

## Deliberate omission: "the wood" and "sand-bank"

Referenced several times but too generic and short to serve as a discriminating alias on their
own (`"the wood"` collides with ordinary prose everywhere). Only `McGregor's garden` — a fully
qualified, discriminating phrase and the actual scene of the story — got a ground-truth entry.

## One fix from the linter: the "Mr." prefix on the garden's alias

`lint_ground_truth.py` caught a real binding bug, not noise: `Mr. McGregor` (the person) is a
literal prefix of `Mr. McGregor's garden` (the place). `_find_page_entry` in `audit.py` matches
page titles to entries by bidirectional substring, in file-load order — `garden.json` sorts
before `mcgregor.json`, so a page titled "Mr. McGregor" would have bound to the garden entity
first. The garden's alias dropped the "Mr. " prefix (`McGregor's garden`, still a literal
substring of the text's "Mr. McGregor's garden" so it still passes the alias-occurs-in-text
check), and the person entity's speculative bare `"McGregor"` alias was removed — the text never
uses it standalone (checked: 12/13 mentions are "Mr. McGregor", the other is "Mrs. McGregor").

## One deliberate choice: "Cottontail" as a forbidden term

The book spells the third sibling `Cotton-tail`, hyphenated, in all three mentions. Most modern
retellings and merchandise use the unhyphenated `Cottontail`. That's listed as an
`adaptation_inventions` forbidden term on `cotton_tail`'s entry precisely because it is *not* a
random string — it is the one-word contamination this book is likeliest to attract.

## Verified behaviour

Not yet exercised against a run — no live pipeline run has been made on this book (see
`CLAUDE.local.md`: this skill never runs the pipeline). The linter (`lint_ground_truth.py`) has
been run clean; the audit gates (`audit_run.py gt-validate`, zero-false-positive and poisoned-page
checks) are the user's to run once a real run exists. Until then, treat the roster, page set and
extraction quality as unmeasured, per the skill's step 8.
