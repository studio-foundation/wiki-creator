# Ground truth — *The Emerald City of Oz* (Oz book 6)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/06.txt`, from the Project Gutenberg EPUB #517) — never against memory
or any film. Book 6 only: this is *The Emerald City of Oz*, in which the Nome King Roquat tunnels
under the Deadly Desert to conquer Oz, half the book is a comic tour of odd towns, and Glinda ends
the series by making Oz invisible forever.

## Files

| File | Entities |
|---|---|
| `dorothy.json` | Dorothy |
| `kansas_family.json` | Aunt Em, Uncle Henry |
| `oz_rulers.json` | Ozma, Glinda, the Wizard |
| `oz_companions.json` | Scarecrow, Tin Woodman (Nick Chopper), Shaggy Man, Tiktok, Jack Pumpkinhead, Omby Amby |
| `oz_animals.json` | Toto, Billina |
| `nome_invaders.json` | Nome King (Roquat), General Guph, Grand Gallipoot, First and Foremost, Kaliko |
| `hostile_peoples.json` | Nomes, Growleywogs, Phanfasms, Chief of the Whimsies |
| `oz_peoples.json` | Munchkins, Winkies |
| `locations.json` | Emerald City, Land of Oz, Kansas, Water of Oblivion (Forbidden Fountain) |
| `comic_towns.json` | Bunbury, Bunnybury, Fuddles (Fuddlecumjig), Utensia, Rigmarole Town |
| `comic_town_figures.json` | Grandmother Gnit, Lord High Chigglewitz, Mr. Bunn, Pop Over, Judge Sifter, Keeper of the Wicket, Blinkem, King Kleaver |
| `minor_and_offstage.json` | Uncle Sam, Royal Family of Ev, Jellia Jamb |

45 entities.

## What this corpus is built to catch

1. **The Nome King is the ENEMY of Dorothy and Ozma (STU-719).** In this book the Nome King —
   named **Roquat the Red**, treated here as an alias of the same entity — digs a tunnel under the
   Deadly Desert to conquer Oz and enslave Ozma and Dorothy, allied with the Growleywogs, Whimsies
   and Phanfasms. `nome_invaders.json` forbids any relation making Roquat an ally or friend of
   Dorothy or Ozma (both sides carry the paired, polarity-worded forbidden phrase per STU-717), and
   the hostile-peoples file forbids the same for his allied armies.

2. **Film / adaptation inventions** — swept even though this is a late book. Dorothy comes to Oz by
   the Magic Belt, not a cyclone, and wears no shoes of power here: `dorothy.json` forbids "ruby
   slippers", "Silver Shoes", "clicks her heels", "there is no place like home", the Wicked Witch,
   Miss Gulch, Professor Marvel, "Over the Rainbow", and the "it was all a dream" ending.
   `toto.json` (in `oz_animals.json`) forbids "Miss Gulch takes Toto" and Toto pulling back the
   curtain. Note: **"Dorothy Gale" IS canon in this book** (used in the narration and in Dorothy's
   signed farewell note), so it is a kept alias, not a forbidden surname.

3. **Cross-tome / sequel bleed** — the comic towns are easy to confuse with one another and with
   later-book material. Each town file forbids swapping one town's nature for another's (Bunbury =
   bread people, Bunnybury = walled rabbit city built by Glinda, Utensia = kitchen utensils under
   King Kleaver, Fuddles = jigsaw people, Rigmaroles = long-winded talkers). Book-3+ Ev material
   (Langwidere, Evoldo) is forbidden on the Royal-Family-of-Ev entry; earlier-book origins (Powder
   of Life for Jack, the Tin Woodman's heart-quest, the Wizard's balloon/humbug reveal, Tiktok as
   the Royal Army) are forbidden on the respective companion entries.

4. **Offstage / spoken-about names promoted to present characters (STU-716).** `minor_and_offstage.json`
   gives entries whose job is to assert absence: **Uncle Sam** (named once in a comparison, never in
   Oz), the **Royal Family of Ev** (backstory only), and **Jellia Jamb** (a named palace-housekeeper
   walk-on who guides a tour but takes no part in the plot).

## Verified book-6-specific facts

- **Aunt Em and Uncle Henry move to Oz permanently**, brought from Kansas by Ozma's Magic Belt to
  escape losing their mortgaged farm. Verified (ch. 2–3, 5).
- **General Guph** is the Nome King's newly made general who personally recruits the Whimsies,
  Growleywogs and Phanfasms. Verified (ch. 4, 6, 8, 11).
- **The comic tour towns each verified** before assertion: Bunbury (bread), Bunnybury (rabbits),
  Utensia (kitchen utensils), Fuddlecumjig (jigsaw Fuddles), Rigmarole Town (long-winded), plus the
  Cuttenclips' paper village (see omissions).
- **The climax**: the invaders drink from the **Water of Oblivion** in the **Forbidden Fountain** (a
  plan devised by the Scarecrow) and forget everything; the Scarecrow and Tin Woodman throw Roquat
  in so he too forgets; Glinda then makes all of Oz **invisible to outsiders forever**. Verified
  (ch. 26–30).

## Roster items skipped, and why

- **`Captain`, `Emperor`, `King`, `Princess`** — bare generic titles, not entities. `Captain`
  reduces to the Captain General (Omby Amby, covered); `Emperor` to the Tin Woodman (covered);
  `King` and `Princess` collide across many bearers (Nome King, Rabbit King, King Kleaver / Ozma,
  Dorothy). Bare tokens like these are omitted so they cannot enter the alias lookup and bind the
  wrong page (the STU rule-2 hazard).
- **Long sentence-fragment "event" titles** (e.g. "How the General Talked to the King") and
  **all-caps extraction junk** ("BUNNYBURY", "FUDDLECUMJIG") — not entities; ignored per spec.
- **Present but not in the generated roster**, so not given entries (noted here rather than left as
  a silent gap): the **Sawhorse** (draws the wagon, speaks), the **Cowardly Lion** and **Hungry
  Tiger** (Ozma's body-guards; ch. 7 "How Aunt Em Conquered the Lion"), **Professor Wogglebug**
  (ch. 9), and **Miss Cuttenclip** / the **Cuttenclips** and **Rabbit King** (present but no roster
  page; the Rabbit King's alias would also collide with the bare `King` page). Their facts are
  folded into related entries where they appear (the Lion into `aunt_em`, the Rabbit King into
  `bunnybury`).

## Signals are literal phrases, not descriptions

Every `hallucination_signals` entry is a literal substring a hallucinated page would contain, with
no comma inside a signal and never just the entity's own name — matching the loader's comma-split
substring search.
