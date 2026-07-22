# STU-635 — `ner.character_names` sweep over the flipped public_domain books

Method (STU-630): run the shipped extractor (GLiNER `urchade/gliner_large-v2.1`
at each book's threshold, no gazetteer = **baseline**), score PERSON recall
against a small hand roster of the novel's principals, and declare in
`ner.character_names` any **common-noun-named** character GLiNER's `person name`
label misses. Harness: `research/ner-eval/gazetteer_measure.py` (GLiNER + the
STU-630 gazetteer over the parsed chapters, PERSON roster out).

`WIKI_NER_DEVICE=auto HF_HUB_OFFLINE=1`, GLiNER t0.3, on the real EPUBs.

## Harness validation — Alice (STU-630's known gap)

| arm | hand-roster PERSON recall | missed |
|---|---|---|
| baseline (no gazetteer) | 13/22 | Caterpillar, Cheshire Cat, Dodo, Eaglet, Lory, Mouse, Pigeon, Rabbit, Cook |
| + `ner.character_names` | 20/22 | Cook, Rabbit |

Reproduces STU-630's 14/20 → 20/20: the gazetteer recovers the low-frequency
single-common-noun creature cast. This is the positive control — the harness
detects the gap where one exists.

## Sweep result: no other flipped book has the gap

Every `invented_names: true` public_domain book **except Alice** already reaches
complete PERSON recall on baseline GLiNER — no gazetteer entry is warranted.

| book | chapters | baseline PERSON recall (hand roster) | common-noun cast — all PERSON on baseline |
|---|---|---|---|
| Cthulhu | 1 | 8/8 human cast | cast is proper-named (Angell, Wilcox, Legrasse, Johansen, Castro) |
| Oz 1 — Wonderful Wizard | 26 | 13/13 | Scarecrow, Tin Woodman, Cowardly Lion, Wizard, Wicked Witch, Toto |
| Oz 2 — Marvelous Land | 25 | 11/11 | Woggle-Bug, Saw-Horse, Jack Pumpkinhead, Jinjur, Scarecrow, Tin Woodman |
| Oz 3 — Ozma of Oz | 3 | 11/11 | Nome King, Hungry Tiger, Tiktok, Billina, Langwidere |
| Oz 4 — Dorothy & Wizard | 3 | 10/10 | Sawhorse, Woggle-Bug, Nome King, Hungry Tiger, Eureka, Jim |
| Oz 5 — Road to Oz | 2 | 12/12 | Shaggy Man, Button-Bright, Polychrome, Johnny Dooit, Santa Claus |
| Oz 6 — Emerald City | 3 | 15/15 | Guph, Nome King, Shaggy Man, Kaliko, Miss Cuttenclip, Omby Amby |
| The Odyssey | 28 | 16/16 | Cyclops, Polyphemus, Scylla (365 PERSON entities, all proper-named) |

## Why Alice is the exception

Alice's missed cast are **low-frequency, single-common-noun creature names**
addressed with a determiner — "the Lory", "the Dormouse", "the Eaglet" — which
GLiNER's `person name` label under-scores at t0.3. Oz and the Odyssey name their
common-noun cast with forms GLiNER catches regardless: frequent (Scarecrow 70,
Nome King 72, Shaggy Man 40), distinctive/multi-word (Tin Woodman, Hungry Tiger,
Woggle-Bug, Cyclops), or both. The Odyssey and Cthulhu casts are proper-named
outright.

Non-PERSON entities were checked for individual characters buried under
PLACE/FACTION (the STU-537 typing shape): none. Oz's non-PERSON top entries are
correctly places (Emerald City, Kansas) and **groups** (Winkies, Munchkins,
Winged Monkeys, Kalidahs, Wheelers, Nomes) — collectives, not individuals. The
one proper-name typing quirk is `Cthulhu` itself typed PLACE (8 mentions) — a
named deity, not the common-noun recall gap this ticket targets, and forcing a
monster-god to PERSON is out of scope.

## Out of scope (not flipped)

Dracula, Journey/Voyage au centre de la terre, Notre-Dame de Paris are
`invented_names: false` (real-world-named casts, per STU-616) — they run spaCy,
not the GLiNER `person name` path, so the gazetteer question does not apply.

## Deliverable

No book YAML changes. The gap STU-630 closed on Alice does not generalize to the
rest of the flipped set; the measurement + this record are the result. Harness
committed for re-measurement when a new invented-world book is added.
