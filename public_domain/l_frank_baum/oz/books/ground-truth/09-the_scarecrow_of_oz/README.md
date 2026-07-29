# Ground truth — *The Scarecrow of Oz* (Oz book 9)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/09.txt`, from the Project Gutenberg EPUB) — never against memory or
any film. Book 9 only: the tome in which Trot and Cap'n Bill are drawn into a whirlpool, reach the
hidden kingdom of Jinxland, and the Scarecrow is sent by Glinda to depose King Krewl.

## Files

| File | Entities |
|---|---|
| `trot_and_capn_bill.json` | Trot, Cap'n Bill |
| `button_bright_and_ork.json` | Button-Bright, the Ork |
| `island_and_mo.json` | Pessim, the Bumpy Man |
| `jinxland_court.json` | King Krewl, Googly-Goo, Pon, Gloria |
| `witches.json` | Blinkie, the three witches |
| `scarecrow_and_glinda.json` | Scarecrow, Glinda |
| `emerald_city.json` | Ozma, Dorothy, Betsy Bobbin, the Wizard, Sawhorse |
| `locations.json` | Jinxland, Land of Mo, Pessim's island, Great Gulf, Ruby Cavern, Orkland |
| `minor_and_offstage.json` | King Kynd, King Phearse, Tin Woodman, the reception guests |

29 entities.

## What this corpus is built to catch

1. **Three Kings of Jinxland, one rightful heir, and the succession is easy to garble.** **King
   Kynd** (Gloria's father) fell into the Great Gulf. His Prime Minister **Phearse** (Pon's father)
   took the throne and was destroyed by *his* Prime Minister **Krewl**, who weighted him under a
   pond with stones. Only **Gloria** has a right to the throne, and the Scarecrow tells Pon so to
   his face — Pon's father had no right either. Each entry forbids the wrong attribution: Krewl did
   not kill Kynd, Phearse was not the rightful King, and Pon does not claim the crown.

2. **Nobody dies in Jinxland.** The text is explicit: it is impossible to kill anyone in this land.
   Phearse is pressed into the mud, Kynd is lost in a bottomless gulf, Krewl is demoted to gardener
   under the name **Grewl**, Googly-Goo is bound, and Blinkie is shrunk and stripped. Every
   "is killed"/"is executed" variant is forbidden on the entry that would otherwise carry it.

3. **What actually saves the Scarecrow, and what actually breaks each spell.** The Scarecrow is
   saved from the bonfire by **fifty Orks**, whose whirling tails scatter the fire — not by Glinda,
   not by Ozma, not by his own wits. Cap'n Bill is restored and Gloria thawed by **Blinkie herself**,
   compelled by Glinda's two boxes — the shrinking dust and the withheld antidote. Pon's love does
   *not* thaw Gloria, though he says he hopes it will; `pon`, `blinkie`, `gloria` and `glinda` each
   forbid the wrong agent from their own side.

4. **Two magic berries with opposite effects, on an island where they alone grow.** **Lavender**
   shrinks, **dark purple** restores. This pair is the single most swappable fact in the book — the
   plot turns on it three times (the Ork, Trot and Cap'n Bill, the three Mo birds) — so
   `pessims_island` forbids both reversals explicitly.

5. **Offstage names promoted to present characters (STU-716).** **Glinda never enters Jinxland**:
   she reads her Record Book and sends the Scarecrow with everything he uses there. **Ozma, Dorothy,
   Betsy and the Wizard never leave the palace**, watching in the Magic Picture; the Wizard's house,
   the roadside table and the fresh straw all arrive without him. **King Kynd and King Phearse** are
   backstory only. The whole cast of `minor_and_offstage.json`'s `reception_guests` — the Tin
   Woodman, Jack Pumpkinhead, Professor Wogglebug, Tik-Tok, the Shaggy Man and his brother, Uncle
   Henry, Aunt Em, the Lion, the Tiger, Eureka, Hank, Toto, the Woozy and the nine piglets — appears
   in the **final chapter only** and takes no part in the adventure.

## Verified book-9-specific facts

- **Jinxland is part of the Land of Oz**, a slice of the Quadling Country cut off by mountains and
  the Great Gulf. This is the Scarecrow's whole basis for deposing Krewl in Ozma's name.
- **The Ork is not a bird and has no feathers** except a scarlet crest; he flies by a
  propeller-shaped tail and scorns birds as "all fluff and feathers". His name at home is Flipper.
- **Gloria's heart is frozen, not her love killed** — Blinkie says outright that killing love is a
  hard job even for a skillful witch, and offers the freezing as a substitute.
- **The Scarecrow's one fear is fire**, which he refuses to name aloud because his enemies "will
  never think of it" — and Googly-Goo thinks of it one chapter later.
- **The Land of Mo has no water**: it rains lemonade, and the snow is buttered, salted popcorn.
- **Blinkie loses her magic without knowing it**: the second powder destroys her power, and she
  discovers it only when a charm that would have destroyed half of Jinxland does nothing at all.

## Roster items skipped, and why

- **Bare generic titles** — `King`, `Queen`, `Princess`, `the Observer`, `the Ork` as a species —
  are omitted where they would collide. `King` alone spans Krewl, Kynd, Phearse and Pessim in this
  book; `Princess` spans Gloria and Dorothy.
- **The three summoned witches are one entry, not three**, because the book never names them
  individually and they act only as a group.
- **Unnamed walk-ons folded into their scene's entry**: the cottage woman who feeds the travellers
  and warns them about the King, the deaf man and dumb woman at the farmhouse, the Jinxland soldiers,
  and the three enlarged Mo birds (in `land_of_mo` and `capn_bill`).
- **`Flipper`** is recorded inside the Ork's entry rather than given as an alias: it is used once,
  in his father's remembered speech, and is too ordinary a word to be a safe alias key.

## No roster alignment for this tome

The book-1..6 corpora were written against a generated roster. **Tomes 7–14 have never been run**,
so there is no roster to align to: this corpus is derived from the text alone, covering every entity
a reader would expect a page for.
