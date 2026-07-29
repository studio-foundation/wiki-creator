# Ground truth — *Dorothy and the Wizard in Oz* (Oz book 4)

Canon corpus for the `validate-wiki-run` gate (STU-726). Every fact here was verified against the
extracted tome text (`04.txt`, the Project Gutenberg edition, 1908) — never against memory, the
film, or other Oz books. This tome only: Dorothy, Zeb, Jim and Eureka fall into the earth in an
earthquake, journey up through the Mangaboos, the Valley of Voe and the Gargoyles, and are carried
back to Oz by Ozma's Magic Belt, where the climax is the trial of Eureka the kitten.

## Files

| File | Entities |
|---|---|
| `travelers.json` | Dorothy, the Wizard, Zeb, Jim, Eureka |
| `underground_peoples.json` | Mangaboos, the Prince, the Princess (Mangaboo), Gwig (the Sorcerer), Gargoyles |
| `oz_reunion.json` | Ozma, Scarecrow, Tin Woodman, Hungry Tiger, Sawhorse, Billina, Jellia Jamb, Woggle-Bug |
| `places.json` | Land of Oz, Emerald City, Kansas, Omaha, Hugson's Ranch, Valley of Voe, Pyramid Mountain, Black Pit |
| `minor_and_offstage.json` | Toto, Mombi, Nome King, Champion (Overman-Anu), Uncle Henry, Aunt Em, Uncle Hugson, Munchkin |

34 entities.

## What this corpus is built to catch

1. **Film / adaptation contamination.** Forbid "ruby slippers", "clicks her heels", "there's no
   place like home", "Professor Marvel", "Over the Rainbow", "the Horse of a Different Color". Note
   the book's own shoes are the **Silver Shoes** — referenced (Dorothy lost them in the air and now
   uses the Magic Belt), so "silver shoes" is **not** forbidden; only the film's ruby slippers are.
2. **Cross-tome / sequel bleed.** Ozma, the Sawhorse, the Woggle-Bug, Billina, the Hungry Tiger and
   Jellia Jamb all belong to Oz history, not to the underground journey — their forbidden sets rule
   out book-1/book-2 placement and later-book events (Ozma captured by the Nome King, marching on
   the Nome Kingdom, meeting the Shaggy Man — all book 6+). The travelers Zeb and Jim never return
   in later books; that is forbidden on their entries.
3. **STU-716 — offstage / spoken-about names promoted to present characters.** Toto is the archetype
   here: the author's own preface states he "was in Kansas while Dorothy was in California," so he is
   named but never present. Mombi (only in Ozma's account of the past), the Nome King (only by
   reference), the Champion Overman-Anu (spoken of by the Voe people, already eaten by a bear),
   Uncle Henry and Aunt Em (seen only in the enchanted picture) each get an entry asserting they
   never appear, never speak, and meet no one.
4. **STU-719 — the Nome King as ally.** The Nome King is Dorothy's and Billina's past **enemy** (she
   captured his Magic Belt). His entry, Ozma's, and Billina's each carry the paired-with-polarity
   forbidden relation ("the Nome King is Ozma's ally", "the Nome King befriends Billina").

## Deliberate choices

**"Dorothy Gale" is canon in this tome and is NOT forbidden.** Unlike books 1–2, book 4 uses the
surname explicitly — Zeb's first line is "are you Dorothy Gale?" (verified). It is a canonical alias.

**The Mangaboo Prince and Princess.** "Prince" is a substring of "Princess", so the loader's
bidirectional-substring binding would cross the two pages. Following the Alice Mouse/Dormouse fix,
the Prince entity carries the alias **"the Prince"** (not "Prince"): "the Prince" is not a substring
of "Princess", so the "Prince" page binds to the Prince and the "Princess" page binds to the
Princess. The Mangaboo Princess is a **different character from Princess Ozma** — Ozma's only alias
is "Ozma" (never "Princess Ozma") so the "Princess" page cannot bind to her; her entry states this
explicitly and forbids the confusion.

**The Wizard's alias is never bare "Oz".** "Oz" is a substring of "Ozma", "Land of Oz", "Wizard of
Oz" and more, so it would mis-bind everywhere. His aliases are "the Wizard" and "Wizard of Oz".
Likewise Uncle Hugson is aliased "Uncle Hugson" / "Uncle Bill Hugson", never bare "Hugson", so the
"Hugson's Ranch" page does not bind to him.

**Minor-but-present names in `minor_and_offstage.json`.** Uncle Hugson (final scene only) and the
Munchkin champion (the Oz games) do appear; their facts say so. They share the file with the truly
offstage names because both are small roles, as Alice's `minor_and_offstage` mixed the offstage
(Mary Ann, Mabel) with the barely-present (Bill).

## Roster items skipped, and why

- **"L. FRANK BAUM"** — the author's name from the title page / preface. Extraction junk, not an entity.
- **"The"** — a stopword captured as a title. Junk.
- **"WIZARD"** (all-caps) — a duplicate of the Wizard, lifted from illustration captions
  ("PORTRAIT OF THE WIZARD OF OZ", "THE WIZARD FIRED INTO THE THRONG"). Covered by `the_wizard`.
- **"DOROTHY"** (all-caps) — a duplicate of Dorothy from captions ("DOROTHY POKED THE BOY WITH HER
  PARASOL"). Covered by `dorothy`.
- **Long sentence-fragment "event" titles** — illustration-caption / chapter-line fragments, not
  named entities, so not given corpus entries.

Named cast that appears or is referenced but was **not** in the generated roster (so no page to
validate): the Cowardly Lion (present), Tik-tok (present, wound up by Dorothy), the Gump's Head
(present), the Braided Man and the dragonettes (encountered underground), and Glinda the Good
(referenced in Ozma's history). Aunt Em, though not on the roster, is included as an offstage entry
because she is a named person appearing only in the enchanted picture, paired with Uncle Henry.

## Signals are literal phrases, not descriptions

Each `hallucination_signals` entry is a substring a hallucinated page would literally contain, split
on commas, containing no comma, and never just the entity's own name — e.g. "Toto barked",
"Eureka is found guilty", "the Nome King befriends Dorothy", "the tunnel leads straight to Oz".
