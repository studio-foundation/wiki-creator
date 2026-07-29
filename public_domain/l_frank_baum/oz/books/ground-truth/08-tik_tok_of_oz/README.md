# Ground truth — *Tik-Tok of Oz* (Oz book 8)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/08.txt`, from the Project Gutenberg EPUB) — never against memory or
any film or stage adaptation. Book 8 only: the tome in which Queen Ann of Oogaboo sets out to
conquer the world, Betsy Bobbin is shipwrecked, and the Nome King Ruggedo is deposed by a dragon
carrying a pink ribbon and six eggs.

## Files

| File | Entities |
|---|---|
| `oogaboo.json` | Ann Soforth, Salye, Files, the Officers of Oogaboo |
| `betsy_and_hank.json` | Betsy Bobbin, Hank |
| `shaggy_and_brother.json` | Shaggy Man, the Ugly One |
| `rose_kingdom.json` | Ozga, the Royal Gardener, the Roses |
| `polychrome_and_tiktok.json` | Polychrome, Tik-Tok |
| `nome_kingdom.json` | Ruggedo, Kaliko, General Guph, the Long-Eared Hearer, Pang |
| `jinjin_land.json` | Tititi-Hoochoo, Tubekins, Quox, the Original Dragon, Erma |
| `oz_palace.json` | Ozma, Dorothy, the Wizard, Toto, Sawhorse, Cowardly Lion, Hungry Tiger, Jellia Jamb |
| `locations.json` | Oogaboo, Rose Kingdom, Rubber Country, Hollow Tube, Metal Forest |
| `minor_and_offstage.json` | the Rak, Glinda, Billina, the Pink Kitten, Hiergargo |

41 entities.

## What this corpus is built to catch

1. **Ruggedo is the enemy, and he is Roquat (STU-719).** The book states outright, in a
   parenthetical, that this King "was formerly named 'Roquat,' but after he drank of the 'Waters of
   Oblivion' he forgot his own name and had to take another" — the same entity as the Nome King of
   tomes 3 and 6, under a new name. `ruggedo` carries paired polarity forbiddens against any
   relation making him a friend or ally of Betsy, Shaggy or Queen Ann, and forbids the surviving
   alias "Roquat" as his name *in this book*.

2. **Ruggedo is deposed but NOT left wandering.** The Jinjin's sentence is exile as a homeless
   wanderer; the book's actual ending is different — Betsy pities him, and King Kaliko lets him stay
   underground as a common nome so long as he behaves. Both the sentence and the softer outcome are
   recorded, and "Ruggedo wanders the earth forever at the end" is forbidden.

3. **Who actually defeats the Nome King.** Not Queen Ann's Army, not Tik-Tok, not the Love Magnet,
   and not the dragon's teeth or claws. It is two objects: the **pink ribbon** whose sight strips
   every magical power from Ruggedo, and **six hen's eggs** rolled out of Quox's locket, which nomes
   cannot survive touching. Every plausible wrong answer is forbidden on the entry that would
   otherwise claim it — `ann_soforth`, `tik_tok`, `shaggy_man`, `quox`.

4. **The three kisses, in order.** The charm of ugliness is broken by **Polychrome**, who is still a
   Fairy. Betsy's kiss (a Mortal Maid) and Ozga's (a Mortal Maid who was once a Fairy) are both
   tried first and both fail. `ugly_one`, `betsy_bobbin`, `ozga` and `polychrome` each forbid the
   wrong attribution from their own side, because this is the single most swappable fact in the book.

5. **The Love Magnet has exactly one documented failure, and it is not Ruggedo.** It fails on the
   **Roses**, because they have thorns but no hearts. It never gets shown to Ruggedo at all — the
   King has Shaggy's arms bound to his body precisely so he cannot reach his pocket. "The Love
   Magnet conquers Ruggedo" is forbidden on both `shaggy_man` and `the_roses`.

6. **Offstage names promoted to present characters (STU-716).** **Glinda never appears**: she reads
   her Record Book, twists the Oogaboo pass, and deliberately tells no one — all of it reported.
   **Billina**, **the Pink Kitten** and **Hiergargo** are likewise named and never on the page. Ozma,
   Dorothy, the Wizard, Toto, the Sawhorse, the Lion and the Tiger appear only in the last two
   chapters and never leave the palace, which their entries state.

## Verified book-8-specific facts

- **Betsy Bobbin is from Oklahoma**, not Kansas, and is shipwrecked — the parallel with Dorothy is
  drawn by Ozma herself in the text.
- **Ozga ceases to be a fairy the moment she is exiled** and is thereafter a mere mortal, which is
  why she eats ordinary food on the journey. Verified in Polychrome's explanation to Betsy.
- **Tik-Tok's machinery will not let him lie, nor let his thoughts think falsely** — this is the
  Jinjin's stated reason for accepting his account and seating him on the throne.
- **The Army of Oogaboo never reaches the Land of Oz.** Glinda twists the pass; they emerge in an
  adjoining country separated from Oz by an invisible barrier, and the pass disappears behind them.
- **Quox is sent as punishment for his own offence** — telling the Original Dragon to mind his own
  business — because the Jinjin found no other wrongdoer in his whole land to send.
- **Hank cannot talk until he is inside Oz**, and the same is true of Toto, who has been able to
  talk all along and simply preferred not to. Both verified in the final chapter.

## Roster items skipped, and why

- **Bare generic titles** — `Queen`, `King`, `General`, `Private`, `Chief`, `the Voice` — are
  omitted so they cannot enter the alias lookup and bind the wrong page. This book is unusually
  dense with them: `Queen` collides across Ann, Ozma and Erma; `King` across Ruggedo, Kaliko,
  Tubekins, the Rain King and every royal of the Jinjin's land.
- **The sixteen officers are one entity, not sixteen.** They are named (Apple, Bunn, Cone, Clock,
  Plum, Egg, Banjo, Cheese, Nails, Cake, Ham, Stockings, Sandwich, Padlocks, Sundae, Buttons) but
  act only as a body, and several of the names are ordinary words that would bind wildly as aliases.
  **Jo Candy**, who refuses to join, is recorded inside that entry rather than given his own.
- **The six light maidens** (Sunlight, Moonlight, Starlight, Daylight, Firelight, Electra) are
  folded into `erma` for the same reason — every one of their names is a common noun.
- **Smith & Tinker** are the makers engraved on Tik-Tok's plates and never appear; their names are
  recorded inside `tik_tok` rather than given entries.

## No roster alignment for this tome

The book-1..6 corpora were written against a generated roster. **Tomes 7–14 have never been run**,
so there is no roster to align to: this corpus is derived from the text alone, covering every entity
a reader would expect a page for.
