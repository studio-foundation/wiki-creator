# Ground truth — *Ozma of Oz* (Oz book 3)

Corpus for step 1b of the `validate-wiki-run` skill, for the third Oz tome. Every fact here was
verified against the extracted tome text (`03.txt`, the Project Gutenberg text of *Ozma of Oz*,
1907) — never against memory or a film. Book 3 only: this EPUB is *Ozma of Oz*, and material from
the later Oz books (*Dorothy and the Wizard in Oz*, *The Road to Oz*, *The Emerald City of Oz*,
*Tik-Tok of Oz*) is not in it.

## Files

| File | Entities |
|---|---|
| `dorothy.json` | Dorothy |
| `nome_king.json` | Nome King (Roquat) |
| `ozma.json` | Ozma |
| `oz_companions.json` | Scarecrow, Tin Woodman, Cowardly Lion, Hungry Tiger |
| `billina_and_tiktok.json` | Billina, Tiktok |
| `land_of_ev.json` | Langwidere, Queen of Ev, Evardo, Evanna, Evring |
| `nomes.json` | Nomes, Chief Steward |
| `oz_notables.json` | Glinda, Jinjur |
| `locations.json` | Emerald City, Land of Ev, Australia |
| `minor_and_offstage.json` | Uncle Henry, Aunt Em, Toto, King Evoldo |

25 entities. The tome's whole named cast that received pages, plus four minor/offstage names.

## What this corpus is built to catch

The forbidden lists and hallucination signals target the failure modes the spec names, verified
against this tome:

1. **STU-719 — the Nome King is Dorothy's and Ozma's ENEMY, never an ally.** This is the flagship
   assertion of the corpus. Roquat of the Rocks imprisons the royal family of Ev as ornaments,
   entraps Ozma's entire rescue party into transformations, and tries to make prisoners of them all.
   Both `nome_king.json` and the `dorothy.json` / `ozma.json` entries carry structured forbidden
   relations (rule 4 shape — both characters named plus a polarity word): "the Nome King is Dorothy's
   ally", "the Nome King is Ozma's friend", and so on. He is beaten by Billina's eggs and loses his
   magic belt to Dorothy at the end.

2. **Later-tome / sequel bleed.** The Nome King's later identity **Ruggedo**, his tunnel invasion of
   the Emerald City (*The Emerald City of Oz*), General Guph, the Growleywogs, *Tik-Tok of Oz*, the
   **Shaggy Man**, **Button-Bright** and **Polychrome** (book 5+) are all confirmed absent here and
   forbidden. The magic belt is **won** by Dorothy in this book and given to Ozma — a page that has
   the Nome King keep it is wrong.

3. **Film / adaptation inventions.** "ruby slippers" (this book has **Silver Shoes**, which Dorothy
   recalls losing), "clicks her heels", "there's no place like home", Professor Marvel, Miss Gulch,
   the Horse of a Different Color, required green spectacles — all forbidden where the tome lacks them.

4. **STU-716 — offstage / spoken-about names.** `minor_and_offstage.json` holds names that never
   act in the story: **Aunt Em** (seen only washing dishes in the magic picture, never speaks, never
   meets Dorothy on-page), **Toto** (asleep in the Kansas sun in the magic picture, never leaves
   Kansas), and **King Evoldo** (dead before the book — he drowned himself; only ever spoken about).
   Uncle Henry is grouped here too as a minor character, but his entry records that he *is* present —
   at the ship's departure and the Australian reunion — and does not assert he never appears.

## Book-3 specifics verified against the text

- Dorothy is blown overboard from a ship in a storm, clinging to a chicken-coop with the yellow hen,
  while Uncle Henry sails to Australia (Sydney) for his health. Confirmed.
- **"Dorothy Gale" and the surname "Gale" ARE canon in this tome** — the subtitle names "Dorothy Gale
  of Kansas", and Dorothy introduces herself as "Dorothy Gale... just Dorothy to my friends and Miss
  Gale to strangers". The Alice-style prohibition of "Dorothy Gale" applies to books 1–2 only; it is
  **not** forbidden here.
- Tik-Tok, Billina, the Hungry Tiger and Princess Langwidere (30 interchangeable heads, recognized by
  her ruby key) all first appear in this tome. Confirmed.
- Ozma reigns as girl Ruler of Oz; the text says she was a baby stolen by a wicked old witch and made
  a boy, restored by a sorceress — but the name **"Tip"** and the witch's name **"Mombi"** do **not**
  appear in this tome, so they are forbidden as not-named-here rather than used as aliases.
- Ozma crosses the deadly desert with an army of twenty-seven on **Glinda's magic carpet**; the
  **magic belt** is won from the Nome King at the end and given to Ozma. Confirmed.

## Deliberate omissions from the roster

- **"King"** (a bare roster page) is skipped: as an alias, "King" is a substring of "Nome King",
  "King Evardo", "King Evoldo" and "the Munchkin king", so it binds nothing discriminantly, and the
  bare token would suppress forbidden-term hits elsewhere (the alias trap the skill's rule 2 warns of).
  The real kings are each covered under their own names — the Nome King (`nome_king.json`), King
  Evardo and the Queen of Ev (`land_of_ev.json`), and the dead King Evoldo (`minor_and_offstage.json`).
- The **Wheelers** and **Sawhorse** are described in the corpus facts but were not on the page roster,
  so they get no standalone entry.

## Signals are literal phrases, not descriptions

Each `hallucination_signals` entry is a substring a hallucinated page would literally contain
("Ruggedo", "the Nome King befriends Dorothy", "ruby slippers", "Aunt Em travels with Dorothy"),
contains no comma (the loader splits on commas), and is never merely the entity's own name.
