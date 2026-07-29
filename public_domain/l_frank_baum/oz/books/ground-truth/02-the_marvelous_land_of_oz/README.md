# Ground truth — *The Marvelous Land of Oz* (book 2)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/02.txt`, the Project Gutenberg text of *The Marvelous Land of Oz*),
never against memory or the film. Book 2 only: Dorothy has already gone home and does not appear,
and nothing from books 3+ (the Nome King, Tik-Tok, the Magic Belt, the Shaggy Man, Billina) is in it.

## Files

| File | Entities |
|---|---|
| `tip_ozma.json` | Tip (revealed as Princess Ozma) |
| `oz_companions.json` | Jack Pumpkinhead, Scarecrow, Nick Chopper (Tin Woodman), Woggle-Bug, Saw-Horse, Gump |
| `emerald_city_court.json` | Glinda the Good, Jellia Jamb, Soldier with the Green Whiskers, Guardian of the Gates |
| `antagonists.json` | Old Mombi, General Jinjur |
| `factions_and_places.json` | Gillikins, Munchkins, Quadlings, Winkies, Field Mice, Emerald City, Land of Oz |
| `minor_and_offstage.json` | Dorothy, Wizard of Oz, Pastoria, Professor Nowitall, Nikidik |

25 entities. The tome's whole named present cast, plus its principal offstage names.

## What this corpus is built to catch

The forbidden lists and hallucination signals target the failure modes seen on real Oz runs:

1. **The Tip = Ozma reveal, stated correctly.** The one load-bearing plot fact of this book is that
   Tip is Princess Ozma: as an infant, Ozma was transformed into the boy Tip by **Mombi**, at the
   **Wizard's** bidding, to hide Pastoria's heir. The name "Ozma" appears in the narrative only from
   the Glinda chapters onward (verified: before line 4726 it occurs only in a chapter title). The
   corpus asserts the true relation and forbids the common corruptions: that Tip and Ozma are two
   people, that Mombi is Ozma's mother, that Glinda (not Mombi) does the transformation — Glinda
   explicitly "never deals in transformations."
2. **STU-716 — offstage names promoted to present characters.** **Dorothy does not appear in book 2**
   (grep confirms: 11 mentions, all in the Author's Note or as past history — she was sent home to
   Kansas). The **Wizard of Oz** likewise never appears; he fled in a balloon before the story and is
   only spoken about. **Pastoria** is long dead, **Professor Nowitall** and **Nikidik** exist only in
   a told story or offstage. Each has an entry whose forbidden set asserts it never appears, speaks,
   or meets anyone in this tome.
3. **Cross-tome / sequel bleed.** The Nome King, Tik-Tok, the Magic Belt, the Shaggy Man, Billina,
   Nimmie Amee, Omby Amby and Jack's later giant-pumpkin house are all confirmed absent here and
   forbidden where a page might reach for them.
4. **Adaptation / book-1 contamination.** In book 2 the Scarecrow already **has** his brains and the
   Tin Woodman already **has** his heart — so pages that make them *seek* those are flagged. Film
   inventions (ruby slippers, Dorothy Gale, Munchkinland / the Lollipop Guild, Glinda as the Witch of
   the North arriving in a bubble, the Winkies as the Witch's green guards) are forbidden on the
   relevant pages. The book has no ruby slippers and no Silver Shoes (grep confirms both absent).

## Binding choices (alias notes)

The loader binds a page to the first entity whose alias matches by bidirectional substring, so
aliases are kept short and discriminant, and a few roster title-pages are folded onto their real
entity rather than given generic aliases:

- **`Queen (= Jinjur)`** — folded into `jinjur` via the alias `Queen Jinjur`. A page titled `Queen`
  is a substring of `Queen Jinjur`, so it binds to Jinjur, matching the roster annotation. No entity
  is given the bare token `Queen` (it would match "Queen of the Field Mice" and any Ozma-as-Queen
  page); the Field Mice entry deliberately uses only `Field Mice`, not `Queen of the Field Mice`, to
  avoid competing for a `Queen` page.
- **`Emperor`** — folded into `nick_chopper`. In this tome "Emperor" is unambiguously the Tin Woodman
  (Emperor of the Winkies), so a page titled `Emperor` validates against his facts.
- **`His Majesty`** — **skipped, not bound.** It is used for the Scarecrow (dominant) but also for the
  Tin Woodman ("your Majesty"), so an entity alias would risk a wrong binding and a false violation;
  the page is left unvalidated instead. Stated here rather than left as a silent gap.
- **`Tip` includes `Ozma`/`Princess Ozma` as aliases** because they are literally the same character;
  no separate "Ozma" page exists in the roster, so this is harmless and lets any Ozma-titled page bind
  to the true entry.

Skipped roster items and why: `Queen` and `Emperor` (folded above); `His Majesty` (ambiguous title,
unbound); the long sentence-fragment "event" titles and all-caps extraction junk (`The`,
`L. FRANK BAUM`) are not entities.

## Signals are literal phrases, not descriptions

Each `hallucination_signals` entry is a substring the loader searches for, split on commas, so every
signal here contains no comma and is never merely the entity's own name. Forbidden relations name
both characters and carry a polarity word (e.g. "Ozma is married to the Scarecrow", "Mombi is Ozma's
mother", "Jinjur marries the Scarecrow") per the STU-717 structured check.
