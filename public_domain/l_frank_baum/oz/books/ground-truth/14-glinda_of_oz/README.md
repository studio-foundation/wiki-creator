# Ground truth — *Glinda of Oz* (Oz book 14)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/14.txt`, from the Project Gutenberg EPUB) — never against memory or any
adaptation. Book 14 only: the last complete Oz book Baum wrote, in which the two most powerful
magic-workers in Oz are beaten by a marble door, and the island is finally raised by a schoolgirl's
guess at a name.

## Files

| File | Entities |
|---|---|
| `ozma_and_dorothy.json` | Ozma, Dorothy |
| `glinda_and_wizard.json` | Glinda, the Wizard of Oz |
| `skeezers.json` | Coo-ee-oh, Lady Aurex, Ervic, the Skeezers |
| `flatheads.json` | the Su-dic, Rora, the Flatheads, the cans of brains |
| `adepts_and_reera.json` | the three Adepts (Audah, Aurah, Aujah), Reera the Red |
| `rescue_expedition.json` | the Scarecrow, the Patchwork Girl, the Cowardly Lion, the Glass Cat, Button Bright, Ojo, Trot and Betsy |
| `counsellors.json` | the Tin Woodman, Tik-Tok, Jack Pumpkinhead, the Shaggy Man, the Frogman, Uncle Henry, Cap'n Bill, Professor Wogglebug |
| `journey_encounters.json` | the purple spiders, the white crab, the Mist Maids |
| `locations_and_magic.json` | the Magic Isle, Flathead Mountain, the magic words and Gaulau, the submarines, Dorothy's protections, the Book of Records |

38 entities.

## What this corpus is built to catch

1. **Glinda does not solve this book, and neither does the Wizard.** She fails to raise a model
   island in her own pond, fails at the marble door twice, and never learns the magic words. The
   island is raised because **Dorothy guesses that Coo-ee-oh's name has three syllables and her
   magic has three words**, and because **Scraps jokes about pumping the lake dry**. `glinda`,
   `the_wizard`, `dorothy` and `patchwork_girl` each pin their real contribution and forbid the
   heroic version.

2. **The Adepts are freed by Reera the Red, and Glinda never finds out.** Ervic tricks a Yookoohoo
   who has never helped anyone into doing it by wanting nothing from her, and the Adepts promise
   never to tell. `ervic`, `reera_the_red` and `the_three_adepts` each forbid the Glinda-restores-
   them version and the Ervic-steals-the-powder version.

3. **Coo-ee-oh stole every scrap of her magic** from the three Adepts at a banquet, and knew nothing
   before that. She is never restored: she ends the book a vain Diamond Swan who is glad to have
   forgotten her past. `coo_ee_oh` forbids both the self-taught version and the redemption.

4. **Nobody fights and nobody dies.** The Su-dic spills his own second vessel of poison, the fishes
   are never poisoned, the Flatheads throw down their arms at the sight of their old rulers, and the
   Su-dic ends with a round head and his fair share of brains. Each entry forbids the battle.

5. **The Skeezers elect their own Queen.** Ozma offers the choice; they vote for Lady Aurex. She is
   not appointed. `ozma`, `lady_aurex` and `the_skeezers` all pin this.

6. **Magic in this book is specific and non-transferable.** Coo-ee-oh's doors answer to one word and
   no other magic word has any effect on them at all; Ozma's fairy magic, Dorothy's Magic Belt and
   Glinda's ring together cannot lift the island an inch. `the_magic_words` and
   `dorothys_protections` exist to forbid the generic-magic reading.

## Verified book-14-specific facts

- **Glinda's Book of Records goes blind the moment she leaves home.** Ervic's rescue of the three
  fishes is recorded after she sets out, so she spends days trying to summon fishes already sitting
  in a copper kettle miles away.
- **The Flatheads' brains come in cans**, one per person, given by a Fairy Queen because they had no
  place in their bodies to hold brains — and they can be confiscated, which is the entire mechanism
  of the Su-dic's power. Glinda ends the system by growing each head over its own brains.
- **The invisible wall is invisible so the gap around it stays hidden**, not to hide the entrance —
  Ozma reasons this out on the spot.
- **The up-and-down stairway rings a bell** at every tenth step; Ozma hears it from the start because
  she is holding her wand.
- **The Su-dic loses his poison to his own heel** — he tips the second copper vessel over while
  dancing in glee, and cannot make more because only Rora knew the secret.
- **Rora trips her own husband**, which is what lets the invisible girls reach the stairway.
- **The white crab bargains** — it does nothing for free and asks specifically to be made white,
  because purple spiders fear white crabs.
- **The Wizard refuses to transform the lake's fishes** even to save everyone, on the grounds that it
  is wicked to transform a living creature without its consent and the lake belongs to the fishes.

## Roster items skipped, and why

- **Bare generic titles** — `Queen`, `the Dictator`, `the Adept`, `the King` — are omitted; `Queen`
  alone would bind Coo-ee-oh, Aurex and Lurline, and `King` spans the Spider King, the Nome King and
  the Kalidah King of book 13.
- **Unnamed walk-ons folded into their scene's entry**: the three Skeezers stranded with Ervic
  (inside `ervic`), Glinda's hundred maids of honor (inside `glinda`), the Su-dic's four axe-and-spear
  men (inside `su_dic`), and the tiger and gray wolf of the forest (inside `button_bright`).
- **Dictator Felo Flathead** has one scene and one line; his facts live inside `the_flatheads`.
- **Queen Lurline** is named twice as the source of Ozma's authority and never appears; her fact
  lives inside `ozma`.
- **Aunt Em, Dr. Pipt and the leopard** are mentioned only in passing and are recorded inside
  `uncle_henry`, `glass_cat` and `glass_cat` respectively.

## No roster alignment for this tome

The book-1..6 corpora were written against a generated roster. **Tomes 7–14 have never been run**,
so there is no roster to align to: this corpus is derived from the text alone, covering every entity
a reader would expect a page for.
