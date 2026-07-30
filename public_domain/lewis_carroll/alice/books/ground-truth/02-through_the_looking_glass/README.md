# Ground truth — *Through the Looking-Glass* (book 2 of the Alice series)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against
`processing_output/02-through_the_looking_glass/epub_data.json`, the text the pipeline itself
reads — never against memory. Book 2 only: *Alice's Adventures in Wonderland* is a different
EPUB with its own corpus in `../01-alice_in_wonderland/`.

## Files

| File | Entities |
|---|---|
| `alice.json` | Alice |
| `red_royals.json` | Red Queen, Red King |
| `white_royals.json` | White Queen, White King |
| `knights.json` | White Knight, Red Knight |
| `tweedle_brothers.json` | Tweedledum, Tweedledee |
| `humpty_dumpty.json` | Humpty Dumpty |
| `lion_and_unicorn.json` | Lion, Unicorn, Haigha, Hatta |
| `garden_flowers.json` | Tiger-lily, Rose, Daisy |
| `wood_and_shop.json` | Gnat, Fawn, Sheep, Guard, Goat |
| `walrus_and_carpenter.json` | Walrus, Carpenter, Oysters |
| `minor_and_offstage.json` | Kitty, Snowdrop, Dinah, Frog, Jabberwock, Bandersnatch, Violet, Larkspur |

33 entities. The book's whole speaking cast except the omissions listed below.

## What this corpus is built to catch

1. **Cross-tome contamination, both directions.** The two Alice books share an author, a
   heroine and a shelf, and almost nothing else: no Hatter, no Cheshire Cat, no Queen of
   Hearts, no rabbit-hole, no tea-party in this one. Alice's `forbidden_book1` names all of
   them. The reverse case is already guarded in tome 1's corpus.
2. **Poem characters promoted to characters.** The Walrus, the Carpenter, the Oysters and the
   Jabberwock exist *only* inside recited or read verse. Their entries assert this in the
   first fact and forbid every phrase that would have them meet Alice. This is the biggest
   single hallucination surface in the book — the Walrus and the Carpenter are the most famous
   thing in it, and they are never in the story.
3. **The two identity jokes Carroll left implicit.** Hatta is not called the Hatter and Haigha
   is not called the March Hare anywhere in this text; the association is a reader's, not the
   book's. Both entities carry it under `identity_confusion_forbidden` as well as `forbidden`.
   Same shape for the Frog at Queen Alice's door, who is not the Frog-Footman of tome 1.
4. **Events the book stops just short of.** Tweedledum and Tweedledee never fight — the crow
   ends it. Humpty Dumpty is never shown falling, never mended; there is only a crash offstage.
   The Lion and the Unicorn never finish, and nobody wins the crown. The Red King never wakes.
   A page that resolves any of these has invented an ending.
5. **Biography invented from outside the book.** Alice Liddell, Oxford, Alice's parents, the
   White Knight as a self-portrait of the author. The novel gives none of it.

## Deliberate omissions

**Lily is omitted.** The White Queen's infant daughter — the White Pawn, five mentions — has
no alias that is not a substring of `Tiger-lily`. The corpus's alias lookup binds by
bidirectional substring, so *any* ordering of the two entities mis-binds one of the pages.
She is named instead inside the White Queen's and the Red Queen's facts. If the run produces
a `Lily` page it will be reported unbound; that is this omission, not a corpus defect.

**Bare `Queen`, `King` and `Knight` are not aliases of anybody.** Each is ambiguous *inside a
single chapter* between the Red and the White piece (and `Queen Alice` in chapter IX), so
binding one of them would silently attribute one character's page to another. The full forms
are all present. This mirrors the book YAML, which lists `Red Queen`/`White Queen` under
`ner.character_names` and deliberately leaves the bare forms out — except `Knight`, which the
YAML *does* list because every bare occurrence is the White Knight, and which the corpus still
declines as an alias because `Knight` is a substring of `Red Knight` too.

**Six aliases are four characters long** — `Rose`, `Lion`, `Frog`, `Gnat`, `Fawn`, `Goat`.
All six are the character's only name in the text, and all six are ordinary English nouns that
also occur in ordinary prose. They are kept because dropping them would drop six real
characters; the cost is that a `forbidden` term on another page could in principle be
suppressed by a spurious binding. None of the six shares a substring with any other entity in
this corpus.

**Below the mention floor, so no page and no entry**: the Beetle (2), the Horse (the hoarse
voice in the carriage), the gentleman dressed in white paper, the Jubjub bird (1), the Crow (1),
the Aged Aged Man of the White Knight's song, and the Messengers' bare title `Messenger`.

## Signals are literal phrases, not descriptions

Each `hallucination_signals` entry is a substring the loader searches for, splitting on commas.
Every signal here is a phrase a hallucinated page would literally contain (`"the Walrus met
Alice"`, `"put Humpty Dumpty together again"`, `"Hatta is the Mad Hatter"`), contains no comma,
is never just the entity's own name, and — checked mechanically — never occurs in the book.

## Verified behaviour

None. This corpus was written from the parsed text alone and has never been exercised against
a generated run: no pipeline run has been made on this book. A missing page in the first audit
is therefore a coverage gap to report, not evidence of a corpus defect.

One parsing note for whoever runs it first: `epub_data.json` holds 11 of the book's 12
chapters. Chapter XI ("Waking") is a single sentence — *"—and it really was a kitten, after
all."* — and its spine item does not survive the parse. It contains no entity and no fact used
here.
