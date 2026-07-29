# Ground truth — *The Tin Woodman of Oz* (Oz book 12)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/12.txt`, from the Project Gutenberg EPUB) — never against memory or any
adaptation. Book 12 only: the tome in which the Tin Woodman goes back for the Munchkin girl he
abandoned, and finds she married a man glued together from his own discarded body.

## Files

| File | Entities |
|---|---|
| `tin_men.json` | Tin Woodman (Nick Chopper), Captain Fyter, Chopfyt, Nick Chopper's old Head |
| `travelers.json` | Woot the Wanderer, the Scarecrow, Polychrome |
| `mrs_yoop.json` | Mrs. Yoop |
| `nimmie_amee_and_kuklip.json` | Nimmie Amee, Ku-Klip |
| `road_encounters.json` | the Loons, Tommy Kwikstep, the Hip-po-gy-raf, the Dragons, the Jaguar, the Swynes and the Blue Rabbit |
| `emerald_city.json` | Ozma, Dorothy, Jinjur, Toto |
| `locations.json` | Yoop Castle, Loonville, the Invisible Country, the Wall of Solid Air, Ku-Klip's workshop |

25 entities.

## What this corpus is built to catch

1. **The Tin Woodman does not marry Nimmie Amee, and neither does Captain Fyter.** She is already
   married — to **Chopfyt**, the man Ku-Klip glued together from their own cast-off meat parts. She
   refuses to be Empress of the Winkies, says she is happy, and advises both of them to go home and
   forget her. This is the ending, and it is the single most reversible fact in the book;
   `nimmie_amee`, `tin_woodman`, `captain_fyter` and `chopfyt` each forbid the wrong version.

2. **Which parts went where.** Chopfyt wears **Captain Fyter's head** (Ku-Klip chose it blindly with
   his eyes shut) and **the Tin Woodman's right arm** (two warts on the little finger). Nick
   Chopper's own head is still alive on a cupboard shelf and denies all relationship with him. Whose
   heart is in Chopfyt cannot be told, because the parts had no tags. Each attribution is asserted on
   the entry that owns it and forbidden on the entry that does not.

3. **A Kind Heart, not a Loving Heart.** The Wizard's stock was low and there was only one heart in
   it. This is the reason the Tin Woodman travels out of *duty* rather than love, and he says so
   repeatedly. `tin_woodman` forbids the loving-heart version.

4. **Four transformations, three reversals, and the fourth is an exchange.** Ozma restores the
   Scarecrow and the Tin Woodman easily (yookoohoo magic could only make a straw bear of a straw man
   and a tin owl of a tin man), Polychrome only through a five-step chain, and **Woot not at all** —
   the Green Monkey must exist in Oz forever. He is freed only by Polychrome's idea of giving the
   form to Mrs. Yoop herself. `ozma`, `woot`, `polychrome` and `mrs_yoop` each forbid the shortcut,
   and `toto` and `dorothy` record the refused alternative.

5. **Mrs. Yoop cannot undo her own transformations.** She says so at breakfast and cites it as proof
   that even a clever Yookoohoo's powers are limited. She is a **yookoohoo**, explicitly not a Witch.
   And she is not destroyed or starved: she ends the book as the Green Monkey, unable to work magic.

6. **Everything in this book is escaped, not defeated.** The Loons are punctured and left, the
   Dragons are fled through a hole in the roof, the Jaguar is fed scrambled eggs, the Hip-po-gy-raf
   is paid in straw and keeps his word exactly, the Wall of Solid Air is gone under rather than
   through. Nothing is killed. Each entry forbids the violent version.

## Verified book-12-specific facts

- **The Magic Lace Apron** is the only thing that opens any door or window in Yoop Castle, and Woot
  uses it three more times outside — to escape the Jaguar into the earth, to escape the Dragons
  through the cavern roof.
- **Nimmie Amee built the Wall of Solid Air herself**, from the one magic formula she carried out of
  the Witch's house. It is her wall, not a captor's.
- **Ku-Klip's Magic Glue came from the dead Witch's house.** The Witch would not allow it used on
  either tin man, because she had enchanted the axe and the sword herself.
- **Tommy Kwikstep's twenty legs are a wasted wish**, spoken aloud without thinking, and Polychrome
  removes ten of them plus the corns from the remaining toes.
- **Captain Fyter does not go home with the Tin Woodman.** Ozma sends him into the Gillikin Country
  to keep order, since the Emperor would not be so distinguished with a double constantly beside him.

## Roster items skipped, and why

- **Bare generic titles** — `Emperor`, `Captain`, `Professor`, `King` — are omitted; `Captain` alone
  would bind Fyter and every soldier, and `Professor` spans Swyne and Wogglebug.
- **Unnamed walk-ons folded into their scene's entry**: the Winkie servants of the tin castle, the
  farm family who shelter them the first night, the individual Dragons beyond the Chief and his
  child, and the Nine Tiny Piglets (inside `the_swynes_and_blue_rabbit`).
- **Mr. Yoop** is caged far away and never appears; his facts live inside `mrs_yoop`.
- **The Wicked Witch of the East** is destroyed long before the book opens; her enchanted axe, sword,
  Silver Shoes and Magic Glue are recorded inside the entries of the people they affect.

## No roster alignment for this tome

The book-1..6 corpora were written against a generated roster. **Tomes 7–14 have never been run**,
so there is no roster to align to: this corpus is derived from the text alone, covering every entity
a reader would expect a page for.
