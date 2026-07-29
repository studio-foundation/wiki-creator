# Ground truth — *The Magic of Oz* (Oz book 13)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/13.txt`, from the Project Gutenberg EPUB) — never against memory or any
adaptation. Book 13 only: the tome where a sulky boy finds one word written under a floor board, and
that word is stronger than everything Glinda and the Wizard own put together.

## Files

| File | Entities |
|---|---|
| `kiki_and_ruggedo.json` | Kiki Aru, Ruggedo, Pyrzqxgl, Bini Aru, Mopsi Aru, the Li-Mon-Eags |
| `forest_of_gugu.json` | Gugu, Rango, Bru, Loo, the twelve monkeys |
| `rescue_party.json` | Dorothy, the Wizard of Oz, the Cowardly Lion, the Hungry Tiger |
| `magic_isle.json` | Trot, Cap'n Bill, the Glass Cat, the Lonesome Duck, the Kalidah, the Magic Flower |
| `emerald_city.json` | Ozma, Glinda, the Scarecrow, the Tin Woodman, the Patchwork Girl, Professor Wogglebug, Jellia Jamb |
| `locations.json` | Mount Munch, the Forest of Gugu, the Magic Isle, the Fountain of the Water of Oblivion, the Diamond Palace |
| `minor_and_offstage.json` | Toto, Eureka, the Sawhorse, the sparrow, the Black Bag, the banquet guests, Hank and the Yellow Hen |

40 entities.

## What this corpus is built to catch

1. **The word beats the tools.** The Wizard's Black Bag fails completely — powders, violet smoke, a
   black ball from a silver pistol, growing pincers, a magic axe — and every single enchantment in
   the book is undone by **Pyrzqxgl**, a word he learned by hiding in a hollow tree. `the_black_bag`,
   `the_wizard` and `pyrzqxgl` each forbid the version where his own magic wins.

2. **The power is in the pronunciation, not the word.** Ruggedo hears it spoken aloud and still
   cannot use it; the Wizard's own first attempt, with a wrong accent, fails. This is why Kiki never
   loses control by speaking near anyone — and why speaking it into a hollow tree is what loses it
   for him. `pyrzqxgl` and `ruggedo` both pin it.

3. **Kiki never gives up the secret, and Ruggedo never learns it.** Every jewel Ruggedo owns is
   refused. The whole conspiracy runs on Kiki's refusal, and both men privately plan to destroy the
   other the moment they win. `kiki_aru` and `ruggedo` forbid the shared-secret version and the
   loyal-allies relation.

4. **Two prisoners are freed by transformation, not by rescue.** Trot and Cap'n Bill cannot be cut
   free (flesh roots), cannot be pulled free (like pulling teeth), and cannot wish themselves free —
   the Magic Plant obeys wishes about itself and nothing else. **Dorothy** is the one who thinks of
   the bumblebees. `trot`, `capn_bill`, `magic_flower` and `magic_isle` each forbid a shortcut.

5. **Nothing in this book is killed.** The Kalidah is staked, not slain, and frees itself. The Loons'
   equivalent here — the six giant soldiers — are simply too big to move and are restored. Ruggedo
   and Kiki end the book innocent rather than punished. Each entry forbids the violent version.

6. **The forest is not conquered and does not march.** Gugu calls the strangers liars before he
   believes them, Bru refuses a human shape outright, Rango calls them mischief-makers from the
   first minute, and the assembly never actually votes. `gugu`, `bru`, `rango` and
   `forest_of_gugu` each forbid the war that never happens.

## Verified book-13-specific facts

- **Glinda's Book of Records writes down what *people* do, not what birds or beasts do.** This is the
  loophole the entire conspiracy is designed around, and the reason Ruggedo insists they never resume
  human form inside Oz.
- **Ruggedo is afraid of eggs** — any kind and every kind — which is why the goose shape is a
  torment to him and why his last coherent boast is that there is not an egg in sight.
- **The Glass Cat finds the Black Bag by accident**, while climbing the avocado tree to look at the
  giants' heads, and then hides it under leaves until the Wizard admits her pink brains are better
  hunters than his.
- **The Hungry Tiger identifies the magician** before anyone else, by hearing Ruggedo shout
  "Stop, Kiki—stop!", and is turned into a rabbit mid-spring.
- **Cap'n Bill beats the island with a piece of tree bark** bound under his good foot: only meat
  roots, and leather soles and woolen stockings come from beasts and sheep.
- **The twelve monkeys avenge themselves on the Glass Cat with blue mud**, and the Wizard refuses to
  wash it off — he calls it tit-for-tat and lets her be laughed at.
- **Both magicians end the book harmless and memory-less**, kept in Oz rather than sent away, because
  the last time Ruggedo was sent home he relearned the old evil ways.

## Roster items skipped, and why

- **Bare generic titles** — `King`, `Professor`, `the Sorceress`, `the Nome` alone — are omitted;
  `King` alone would bind Gugu, Ruggedo and the Kalidah King, and `Professor` spans Wogglebug and
  the Swynes of book 12.
- **Unnamed walk-ons folded into their scene's entry**: the Council's brawlers (Chipo the Wild Boar,
  Arx the Giraffe, Tirrip the Kangaroo) inside `gugu`, the wolf who tells the Glass Cat what
  happened inside `glass_cat`, the innkeepers of Ev and Noland inside `kiki_aru`, and Glinda's fifty
  handmaids inside `glinda`.
- **The outside kingdoms Kiki flies over** — Hiland and Loland, Merryland, Noland, Ix, Ev — are
  facts on `kiki_aru` rather than separate location entries; none of them has a scene.
- **The Kalidah King** is mentioned once, offstage, as the one who might mend the holes; his fact
  lives inside `the_kalidah`.

## No roster alignment for this tome

The book-1..6 corpora were written against a generated roster. **Tomes 7–14 have never been run**,
so there is no roster to align to: this corpus is derived from the text alone, covering every entity
a reader would expect a page for.
