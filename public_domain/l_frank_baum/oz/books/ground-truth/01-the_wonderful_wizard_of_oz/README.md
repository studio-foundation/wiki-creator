# Ground truth — *The Wonderful Wizard of Oz* (Oz book 1)

Canon corpus for the `validate-wiki-run` audit gate (STU-726). Every fact here was verified against
the extracted tome text `oztext/01.txt` — the text the pipeline reads — never against memory and
never against the 1939 film. This is book 1 only: *The Marvelous Land of Oz*, *Ozma of Oz*, and the
rest of the series are not in this EPUB, and their characters (Ozma, the Nome King, Tik-Tok, the
Shaggy Man, Billina) do not appear here.

## Files

| File | Entities |
|---|---|
| `dorothy_and_toto.json` | Dorothy, Toto |
| `companions.json` | Scarecrow, Tin Woodman, Cowardly Lion |
| `oz_and_witches.json` | Wizard, Wicked Witch (of the West), Glinda |
| `supporting_cast.json` | Aunt Em, Uncle Henry, Boq, Queen (of the Field Mice), King (of the Winged Monkeys), Guardian of the Gates, Mr. Joker |
| `peoples.json` | Munchkins, Quadlings, Winkies, Winged Monkeys, Kalidahs, Hammer-Heads |
| `locations.json` | Land of Oz, Emerald City, Kansas, Land of the South, Palace, Throne Room |
| `minor_and_offstage.json` | Witch of the East, Gayelette, Quelala |

30 entities. Every named item on the generated page roster is covered.

## What this corpus is built to catch

1. **Film / adaptation inventions.** The book has **Silver Shoes**, not ruby slippers; Dorothy has
   **no surname** ("Gale" is absent from the text — grep confirms); the Wicked Witch of the West is
   **not green-skinned** (the only greenish skin in the book is the gate Guardian's) and rides no
   broomstick; the Munchkins sing no Lollipop-Guild song; there is no "there's no place like home",
   no "Over the Rainbow", no Professor Marvel, no Miss Gulch, no Technicolor/sepia, no Horse of a
   Different Color. Oz is a real country, not a dream Dorothy wakes from. These are forbidden on the
   pages they would contaminate.
2. **Sequel / cross-tome bleed.** Ozma, the Nome King, Tik-Tok, the Shaggy Man, Billina, and the
   name "Nick Chopper"/"Nimmie Amee" for the Tin Woodman and his lost love all belong to later
   tomes and are grepped absent here. The Tin Woodman ruling the Winkies and the Scarecrow ruling
   the Winkies are later-book roles; in book 1 the Tin Woodman only *agrees to return* and rule the
   Winkies after Dorothy leaves, and the Scarecrow is left to rule the **Emerald City**.
3. **The two Wicked Witches.** The roster page **"Wicked Witch" is the Witch of the West** — the
   one-eyed antagonist who enslaves the Winkies, dreads water and the dark, and melts. The Witch of
   the **East** is a separate entity killed offstage by the falling house before she ever appears;
   she lives in `minor_and_offstage.json`. The book never calls the two witches sisters ("sister" is
   absent from the text), so that relation is forbidden on both entries.
4. **STU-716 offstage names.** Gayelette and Quelala exist only inside the Winged Monkey King's
   legend, in the past tense; the Witch of the East is only ever spoken about, never alive on the
   page. All three carry forbidden sets asserting they never appear, never speak, and meet no one in
   the present story.

## Deliberate choices

- **The Witch of the East's alias is `Witch of the East`, not `Wicked Witch of the East`.** The West
  page's title is `Wicked Witch`; the loader binds a page to the first entity whose alias matches by
  bidirectional substring, and `Wicked Witch` is a substring of `Wicked Witch of the East`. Dropping
  the word `Wicked` from the East alias keeps the `Wicked Witch` page from ever binding to the East
  entry.
- **`King` and `Queen` use their bare page titles as aliases.** The roster titles are literally
  `King` (of the Winged Monkeys) and `Queen` (of the Field Mice). A fuller alias like
  `King of the Winged Monkeys` contains the substring `Winged Monkeys` and would steal the
  `Winged Monkeys` faction page. The bare page title binds correctly and collides with nothing. The
  cost — that the common words *king*/*queen* enter the attribution lookup — is the same trade the
  Alice corpus made explicit for its numbered gardeners.
- **The Wizard's aliases include `Oz the Great and Terrible`**, never bare `Oz`, which would collide
  with `Land of Oz` and `Emerald City of Oz`.

## Deliberate omissions

- **The Munchkin girl the Tin Woodman loved, and her lazy old-woman guardian**, are both **unnamed**
  in book 1 (the name "Nimmie Amee" is a later-tome invention). With no name there is no entity and
  no page to bind, so they get no entry; their story is recorded as facts on the Tin Woodman.
- **The Witch of the North** — the little old woman who greets Dorothy and kisses her forehead — is a
  real character but is **not on the generated roster**, so she gets no page-binding entry. Glinda's
  forbidden set nonetheless asserts Glinda is *not* the Witch of the North (a common conflation), and
  Dorothy's protecting kiss is credited to the North Witch, not Glinda.
- **Event-sentence "pages" and extraction junk** (long sentence-fragment titles, "The",
  "L. FRANK BAUM", all-caps duplicates) are not entities and are skipped.

## Signals are literal phrases, not descriptions

Each `hallucination_signals` entry is a substring a hallucinated page would literally contain, holds
no comma (the loader splits on commas), and is never merely the entity's own name — "ruby slippers",
"the man behind the curtain", "the Witch has green skin", "the East Witch is sister to the West
Witch", "clicks her heels".
