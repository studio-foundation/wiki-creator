# Ground truth — *Alice's Adventures in Wonderland* (book 1)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against
`processing_output/01-alice_in_wonderland/chapters.json`, the text the pipeline itself reads —
never against memory. Book 1 only: this EPUB is *Alice's Adventures in Wonderland*, and
*Through the Looking-Glass* is not in it — that tome has its own corpus in
`../02-through_the_looking_glass/`.

## Files

| File | Entities |
|---|---|
| `alice.json` | Alice |
| `white_rabbit.json` | White Rabbit |
| `mad_tea_party.json` | Hatter, March Hare |
| `mice.json` | the Mouse, Dormouse |
| `court_of_hearts.json` | Queen, the King, Knave |
| `duchess_household.json` | Duchess, Cheshire Cat, the Cook, Footman |
| `caterpillar_and_pigeon.json` | Caterpillar, Pigeon, Father William |
| `mock_turtle_and_gryphon.json` | Mock Turtle, Gryphon, Tortoise |
| `pool_of_tears.json` | Dodo, Lory, Eaglet |
| `minor_and_offstage.json` | Dinah, Bill, Mary Ann, Mabel, Ada |

27 entities. The book's whole named cast except the three gardeners (see below).

## What this corpus is built to catch

The forbidden lists and hallucination signals target four failure modes seen on real runs:

1. **Sequel contamination** — *Through the Looking-Glass* material (Red Queen, Tweedledee,
   Humpty Dumpty, the White Knight, Alice becoming a Queen, Dinah's kittens). Run 1 of this book
   produced exactly this.
2. **Adaptation contamination** — "the Mad Hatter" (the text says only "the Hatter"), the blue
   dress, the pinafore, the unbirthday, the 10/6 card.
3. **Biography invented from outside the book** — Alice's age, Alice Liddell, London, the
   Victorian upper class. The novel gives none of it.
4. **Offstage names promoted to characters** — Tortoise (a nickname for the Mock Turtle's old
   schoolmaster, spoken about in the past tense), Mary Ann, Mabel, Ada and Father William all
   have entries whose job is to assert that they never appear, never speak, and meet no one.

## Two deliberate choices

**The Mouse and the Dormouse share one file, in that order.** The loader binds a page to the
first entity whose alias matches by bidirectional substring, and the page title `Mouse` is a
substring of the alias `Dormouse`. Listing the Mouse first — with the alias `the Mouse`, which is
*not* a substring of `Dormouse` — makes each page bind to the right entity. Splitting them across
files would leave that to glob order.

**The three gardeners (Two, Five, Seven) are omitted.** Their names are bare numerals. As aliases
they would enter the attribution lookup and match `two`, `five`, `seven` anywhere in ordinary
prose, which silently suppresses forbidden-term hits on other pages — the failure the skill's
alias rule exists to prevent. The cost is that their three (figurant, ~200-token) pages are not
validated. Stated here rather than left as a silent gap.

## Signals are literal phrases, not descriptions

The loader treats each `hallucination_signals` entry as a substring to search for, splitting it
on commas. A signal written as prose ("Any appearance of the Dodo outside chapters II and III")
reduces to the character's own name and fires on every page. Every signal here is therefore a
phrase a hallucinated page would literally contain ("Dinah's kittens", "the Knave is beheaded"),
contains no comma, and is never just the entity's own name.

## Verified behaviour

Against the run of 2026-07-28 (28 pages, `wiki_pages.json`): **0 violations, 0 false positives,
0 unbound pages** other than the three gardeners above.

Against six deliberately poisoned pages (Looking-Glass Alice, Mad Hatter, Dinah's kittens, a
speaking Tortoise, a convicted Knave, Bill as Alice's enemy): **37 violations caught**, every
poisoned page flagged.
