# Ground truth — *The Lost Princess of Oz* (Oz book 11)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/11.txt`, from the Project Gutenberg EPUB) — never against memory. Book
11 only: the tome in which Ozma, the Magic Picture, Glinda's Book of Records, the Wizard's black bag
and one Cookie Cook's dishpan all vanish in a single night.

## Files

| File | Entities |
|---|---|
| `ozma_and_dorothy.json` | Ozma, Dorothy |
| `search_party.json` | Button-Bright, Scraps, the Wizard, Toto, Betsy and Trot |
| `cayke_and_frogman.json` | Cayke the Cookie Cook, the Frogman |
| `ugu.json` | Ugu the Shoemaker |
| `bear_center.json` | the Lavender Bear, the little Pink Bear, Corporal Waddle |
| `thi_and_herku.json` | High Coco-Lorum, the Thists, the Czarover of Herku, the Herkus |
| `locations.json` | Yip Country, Merry-Go-Round Mountains, Truth Pond, Great Orchard, wicker castle |
| `minor_and_offstage.json` | Glinda, Cap'n Bill, the other search parties, the search-party animals, Wiljon and the ferryman |

27 entities.

## What this corpus is built to catch

1. **Where Ozma actually is.** Not a dungeon cell, not invisible, not transformed into Button-Bright
   — she is inside a **golden peach pit in Button-Bright's left jacket pocket**, having been the
   solitary enchanted peach at the exact center of the Great Orchard. Dorothy guesses "dungeon cell"
   and is wrong; the Wizard guesses "a chunk of pitch" from the black spot in the Magic Picture and
   is wrong. `ozma`, `ugu`, `button_bright` and `great_orchard` each forbid the wrong answer.

2. **The little Pink Bear never makes a mistake — and this is the book's central joke.** Every one of
   his apparently contradictory answers is literally true: Ozma *was* in the hole (because
   Button-Bright and the pit were in it), was *not* in the hole once Button-Bright was pulled out,
   and *was* "here, among you". `little_pink_bear` forbids "makes a mistake" outright, and also
   forbids the one thing he genuinely cannot do: tell the future.

3. **Dorothy conquers Ugu, and she does it with the Nome King's Magic Belt.** Not the Wizard, not the
   Frogman, not the Lion. Two details are load-bearing and easy to lose: the Belt grants **one wish a
   day** (spent the day before on caramels, saved for the upside-down hall), and Dorothy meant to say
   **Dove of Peace** but in her excitement said only "dove" — which is why the bird is enormous and
   murderous. `dorothy`, `the_wizard` and `ugu` each forbid the wrong conqueror.

4. **Ugu is not destroyed, is not restored, and asks forgiveness.** He escapes in the dishpan to the
   Quadling Country, repents on a tree branch, and **refuses** Dorothy's offer to make him a man
   again, preferring the free and independent life of a bird. The book's last scene is his pardon.

5. **The Frogman is a humbug, and the Truth Pond is what unmakes him.** He knew it himself all along;
   the pond only makes him say so. Cayke **refuses** to bathe in it. This pair of facts is the whole
   arc of the subplot and each entry forbids the reversal.

6. **The three fortress barriers are all stolen, and two are beaten with household objects.** Glinda's
   Barrier of Fire dies to a single **match** (her stolen book gives the spell but not the antidote);
   the Wizard's own Wall of Steel dies to a **pin** stuck in the far side; the army of girl-soldiers
   is an optical illusion Scraps simply dances through.

7. **Offstage names promoted to present characters (STU-716).** **Glinda never leaves her castle** and
   never traces Ozma. **Cap'n Bill stays behind to mind the palace.** The other three search parties —
   Ojo/Unc Nunkie/Dr. Pipt, the Scarecrow/Tin Woodman, the Shaggy Man/Tik-Tok/Jack Pumpkinhead — never
   reach Ugu; the Scarecrow and Tin Woodman only stumble on the abandoned dishpan and think it would
   make a good foot-bath. The **Soldier with the Green Whiskers** has been fishing for two months.

## Verified book-11-specific facts

- **Toto's lost growl is never actually stolen.** He blames Ugu throughout; he finds it again in a
  corner of the wicker castle when a mouse runs out.
- **Zosozo** is the Czarover's own invention, pure energy, fed to every Herku one teaspoonful a year;
  Ugu once took two and pushed over the city wall. The Wizard's vial of it is what lets the Frogman
  fight the Dove of War.
- **The city of Thi does not move** — the surrounding land turns — and its wall is not there at all.
- **The Herkus are lean, not large.** The rumour that they are twice the size of giants is exactly
  backwards; they keep giants as slaves by strength alone.
- **Nobody in Oz can die**, which is why the Bear King can condemn his prisoners to death "merely as
  a matter of form", the execution set ten years out.

## Roster items skipped, and why

- **Bare generic titles** — `King`, `Princess`, `the Wizard` as a common noun, `Corporal` — are
  omitted where they would collide across the book's many rulers.
- **Unnamed walk-ons folded into their scene's entry**: the old shepherd who warns the party, the
  Bluefinch and the White Rabbit of the orchard, the peacock on the castle wall, the charioteer of
  Thi, the giant slaves of Herku, the jolly ferryman at the end (a different man from the unhappy
  one), and the nine Yips who turn back at the gulf.
- **Aunt Em**, who sewed Scraps's eyes back on before the book opens, is mentioned once and never
  appears; the fact lives inside `scraps`.
- **The Magic Dishpan and the Magic Belt** are recorded inside the entries of the people who own and
  use them rather than given entries of their own, since neither is a character.

## No roster alignment for this tome

The book-1..6 corpora were written against a generated roster. **Tomes 7–14 have never been run**,
so there is no roster to align to: this corpus is derived from the text alone, covering every entity
a reader would expect a page for.
