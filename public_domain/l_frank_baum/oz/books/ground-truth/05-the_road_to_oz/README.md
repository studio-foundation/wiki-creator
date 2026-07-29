# Ground truth — *The Road to Oz* (Oz book 5)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text `oztext/05.txt` (the Project Gutenberg text of *The Road to Oz*, 1909) — never
against memory or any film. Book 5 only: field names carry the loader's hardcoded `_book1` suffix
regardless of tome; the tome is disambiguated by this directory, not the field name.

## Files

| File | Entities |
|---|---|
| `travelers.json` | Dorothy, Shaggy Man, Button-Bright, Polychrome, Toto |
| `oz_court.json` | Ozma, the Wizard, Jellia Jamb, High Chamberlain |
| `oz_companions.json` | Scarecrow, Tin Woodman (Nick Chopper), Jack Pumpkinhead, Tik-tok, Billina |
| `road_encounters.json` | King Dox, the Musicker, Johnny Dooit |
| `party_guests.json` | Santa Claus, John Dough, King Bud |
| `peoples_and_places.json` | Knooks, Ryls, Winkies, Deadly Desert, Emerald City, Kansas, Royal Palace |
| `minor_and_offstage.json` | Dyna, the Nome King |

29 entities. Covers the whole road-party, the Oz court and companions, the notable road
encounters, the three main foreign guests that got pages, the peoples and places, and the two
offstage names.

## What this corpus is built to catch

The forbidden lists and hallucination signals target the failure modes the skill exists to flag,
tuned to what *this* tome actually contains:

1. **First-appearance characters written with later-tome baggage.** The Shaggy Man, Button-Bright,
   and Polychrome all make their **series debut here**. Their forbidden sets bar roles they only
   acquire later: the Shaggy Man's brother and the Ruggedo expedition (*Tik-Tok of Oz*),
   Button-Bright's Magic Umbrella and Trot (*Sky Island*), Polychrome joining the brother-rescue
   quest. Verified absent in `05.txt`.
2. **The two transformations must not be swapped.** King Dox of Foxville gives **Button-Bright a
   fox head**; King Kik-a-bray of Dunkiton gives **the Shaggy Man a donkey head**; both are washed
   off in the Truth Pond. Each entry forbids the other's head.
3. **Film / adaptation contamination on Dorothy and Toto.** Ruby slippers (the series has Silver
   Shoes, and in *this* book Dorothy goes home by the **Magic Belt**), "Dorothy Gale" (the surname
   "Gale" never appears in the text), "there's no place like home", "Over the Rainbow", Miss Gulch,
   Professor Marvel, a green-skinned witch — none are in the tome.
4. **Cross-tome / sequel bleed and the Nome King enmity (STU-719 shape).** The Nome King **never
   appears** here — he is named only in backstory (Dorothy captured the Magic Belt from him; he
   once enslaved the Queen of Ev). His entry forbids the ally/friend relation with polarity words
   naming both sides, and asserts he never appears, attacks, or attends the party.
5. **Offstage names promoted to present characters (STU-716).** Dyna, the old woman who owns the
   Blue Bear Rug, is spoken about only by the Tin Woodman and never appears; her entry asserts she
   never appears, speaks, or meets anyone. (Her Blue Bear Rug *does* appear in the procession — the
   entry notes the distinction.)

## Deliberate omissions

Roster items intentionally not given their own entry, and why:

- **"Princess"** — not a distinct entity. The text uses "the Princess" almost always for **Ozma**
  (also "Princess Dorothy", "Princess Fluff"). A bare `Princess` alias would bind by bidirectional
  substring to any of them; it is covered by the Ozma entry and skipped to avoid a mis-binding.
- **Extraction junk** — `The`, `THE shaggy man`, `LAND OF OZ` (all-caps, from the desert warning
  sign and the back-matter book ads), and `TWINKLE` (from the "Twinkle Tales" advertisement printed
  after "THE END") are not characters and are skipped.
- **Long sentence-fragment "event" titles** are not entities and are skipped.

Foreign party guests present in the text but not on the page roster (Queen Zixi, Princess Fluff,
Chick the Cherub, Para Bruin, the Queen of Merryland, the Queen of Ev, King Evardo, King Kik-a-bray,
Glinda, the Woggle-Bug, the Cowardly Lion, the Hungry Tiger, the Saw-Horse, the Good Witch of the
North, the Guardian of the Gates, the Braided Man, the Candy Man) are named in the relevant entries'
relations but were not given standalone files, since they did not appear as separate pages in the
roster to validate.

## Signals are literal phrases, not descriptions

Each `hallucination_signals` entry is a substring the loader searches for, split on commas, so no
signal contains a comma and none is merely the entity's own name. Each `forbidden_book1` term is a
discriminant phrase (no bare common tokens); forbidden *relations* name both characters and carry a
polarity word (friend/ally/enemy/marries/parent) per the STU-717 structured check.

## Verification

Every fact was checked against `oztext/05.txt` by grep/read: the Nome King appears only in three
backstory mentions and never on-page; "Gale" is absent; the Shaggy Man's head is a donkey head and
Button-Bright's is a fox head; Dorothy returns to Kansas by the Magic Belt, not the Silver Shoes.
