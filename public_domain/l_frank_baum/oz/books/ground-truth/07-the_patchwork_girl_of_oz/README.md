# Ground truth — *The Patchwork Girl of Oz* (Oz book 7)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/07.txt`, from the Project Gutenberg EPUB #32094) — never against
memory or any film. Book 7 only: this is the book in which the Crooked Magician's Liquid of
Petrifaction turns Unc Nunkie and Margolotte to marble, and the Munchkin boy Ojo crosses Oz
hunting the five ingredients of the charm that would undo it.

## Files

| File | Entities |
|---|---|
| `ojo_and_unc_nunkie.json` | Ojo, Unc Nunkie |
| `crooked_magician.json` | Dr. Pipt, Margolotte |
| `new_creations.json` | Scraps (the Patchwork Girl), Bungle (the Glass Cat), the Woozy, the phonograph (Victor Columbia Edison) |
| `oz_companions.json` | Scarecrow, Tin Woodman (Nick Chopper), Shaggy Man, Jack Pumpkinhead, Sawhorse, Toto |
| `oz_rulers.json` | Ozma, Dorothy, the Wizard, Glinda |
| `emerald_city_officials.json` | Soldier with the Green Whiskers, Tollydiggle, Guardian of the Gate, Jellia Jamb |
| `road_encounters.json` | the woodchopper, the Wise Donkey, the Foolish Owl, Chiss, Mister Yoop, Tottenhots, the lazy Quadling |
| `hoppers_and_horners.json` | Hoppers, Hip Hopper, Horners, Jak Horner, Diksey Horner |
| `locations.json` | Emerald City, Munchkin Country, Winkie Country, Quadling Country, Trick River, the tin castle, the dark well |
| `minor_and_offstage.json` | Mombi, Jinjur, Billina, Eureka, Professor Wogglebug, Cowardly Lion, Hungry Tiger |

48 entities.

## What this corpus is built to catch

1. **The quest fails, and every entry says so.** Ojo secures four of the five things and
   **never gets the yellow butterfly's left wing**: the Tin Woodman refuses it outright, and
   refuses to lend a live butterfly either. The statues are restored by **the Wizard, using a
   method Glinda taught him** — not by Dr. Pipt's compound, whose recipe book Ozma has burned.
   A page that mixes the charm, or that has Ojo return triumphant with all five ingredients, is
   inventing the ending; `ojo_and_unc_nunkie.json`, `tin_woodman`, `the_wizard` and `dark_well`
   each forbid it from their own side.

2. **Two makers, two made things, and the pairs are easy to swap.** Margolotte sewed and
   stuffed the Patchwork Girl; **Dr. Pipt** made the Glass Cat and supplied the Powder of Life
   for both. Margolotte chose only Obedience, Amiability and Truth for the girl's brains —
   **Ojo** is the one who emptied the whole Brain Furniture shelf into the dish. The intended
   name was **Angeline**; **the Glass Cat** named her Scraps. Each of these four attributions is
   asserted on the entry that owns it and forbidden on the entry that does not.

3. **Film / adaptation inventions** — swept as on the earlier tomes, even though Dorothy is a
   resident of Oz here and arrives nowhere by cyclone. `dorothy.json` forbids ruby slippers,
   Silver Shoes, heel-clicking, "there is no place like home", the Wicked Witch, Miss Gulch,
   Professor Marvel, "Over the Rainbow" and the dream ending; `toto` forbids Miss Gulch and the
   curtain; `the_wizard` forbids the humbug/balloon material, which belongs to book 1 and 4;
   `scarecrow`, `tin_woodman` and `cowardly_lion` each forbid the brains/heart/courage quest.

4. **Offstage names promoted to present characters (STU-716).** `minor_and_offstage.json` exists
   to assert absence. **Glinda never appears** — she acts only through the Wizard and is spoken
   of — so her entry is in `oz_rulers.json` with that stated and the appearance forbidden.
   **Mombi**, **Jinjur**, **Billina**, **Eureka** and **Professor Wogglebug** are named in
   backstory, in a report at the gate, in advice, and in the Shaggy Man's song, and none of them
   is on the page. The **Cowardly Lion** and **Hungry Tiger** are physically present at Ojo's
   trial and at the final scene but speak no line and take no part in the plot; their entries say
   exactly that.

5. **Paired polarity forbiddens (STU-717).** The book's only real hostile is **Mister Yoop**, who
   is caged and stays caged: `mister_yoop` forbids any relation making him an ally or friend of
   the travellers, and forbids his escape. **Chiss** is disarmed, not killed, and refuses to
   reform. The Hopper–Horner war ends with **no battle at all** — both group entries forbid the
   fight, the conquest and the apology.

## Verified book-7-specific facts

- **The five things**, verified against Dr. Pipt's own recitation and Ojo's tally: a six-leaved
  clover, the left wing of a yellow butterfly, a gill of water from a dark well, three hairs from
  the tip of a Woozy's tail, and a drop of oil from a live man's body.
- **The dark well is in Diksey Horner's radium mine**, at the bottom of a slide down which the
  whole party tumbles; Ojo fills Dorothy's gold pint flask by feel, in the dark.
- **The drop of oil comes from the Tin Woodman's left knee-joint**, caught in a crystal vial —
  the Emperor is the "live man" of the recipe and does not realize it until afterwards.
- **The wall between the Munchkin and green countries is an optical illusion**, passed with eyes
  shut in one hundred counted steps; the sliding stretch of road is beaten by walking backward.
- **The Hopper–Horner war** is caused by one pun on "under-standing" made by Diksey Horner, and
  is ended by Dorothy telling the Hoppers to laugh at it. Verified at the fence scene.
- **Dr. Pipt is straightened as well as stripped**: the Wizard's edict removes his magic and
  every crooked limb in the same gesture, leaving him "a simple Munchkin".

## Roster items skipped, and why

- **Bare generic titles** — `Chief`, `Champion`, `Emperor`, `Princess`, `the Voice` — are omitted
  so they cannot enter the alias lookup and bind the wrong page. `Chief` and `Champion` reduce to
  Jak Horner and Hip Hopper (both covered); `Emperor` to the Tin Woodman; `Princess` collides
  across Ozma and Dorothy. The unnamed **Voice** in the invisible house is a one-scene device with
  no name to hang a page on.
- **Unnamed walk-ons folded into their scene's entry**: the farm woman who sews up Scraps, the
  Quadling's wife and children (in `lazy_quadling`), the nineteen Horner daughters and the
  bachelor whose book of rules governs them (in `jak_horner`), and the Kalidahs Dr. Pipt turned to
  marble long ago (in `dr_pipt`).
- **Named only in the Shaggy Man's song and nowhere else** — Tik-tok, the Nine Tiny Piglets — are
  not given entries; naming them at all would risk promoting a lyric to a character. The song's
  other names (Wogglebug, Billina, the Lion, the Tiger, the Sawhorse, Jack) do have entries
  because each is also present or acting elsewhere in the book.

## No roster alignment for this tome

The book-1..6 corpora were written against a generated roster and could note which roster items
they skipped. **Tomes 7–14 have never been run**, so there is no roster to align to: this corpus
is derived from the text alone, covering every entity a reader would expect a page for. That is
the safer direction — a ground truth derived from a roster can only ever confirm what the
pipeline already found.
