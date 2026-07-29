# Ground truth — *Rinkitink in Oz* (Oz book 10)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against the
extracted tome text (`oztext/10.txt`, from the Project Gutenberg EPUB) — never against memory. Book
10 only: the tome in which the pearl island of Pingaree is destroyed by the warriors of Regos and
Coregos, and Prince Inga sets out with a fat King and a talking goat to get his parents back.

## Files

| File | Entities |
|---|---|
| `pingaree_royals.json` | Inga, King Kitticut, Queen Garee |
| `rinkitink_and_bilbil.json` | Rinkitink, Bilbil (Prince Bobo) |
| `magic_pearls.json` | Blue Pearl, Pink Pearl, White Pearl |
| `regos_and_coregos.json` | King Gos, Queen Cor, Captain Buzzub |
| `nikobob_family.json` | Nikobob, Zella |
| `nome_kingdom.json` | Kaliko, Klik, the Long-Eared Hearer and the Lookout |
| `oz_rescuers.json` | Dorothy, the Wizard, Ozma, Glinda |
| `locations.json` | Pingaree, Regos, Coregos, Gilgad, the Three Trick Caverns |
| `minor_and_offstage.json` | Choggenmugger, Pinkerbloo, the Mermaid Queen, the banquet guests |

29 entities.

## What this corpus is built to catch

1. **Three pearls, three distinct powers, and they are constantly swapped.** **Blue = strength.
   Pink = protection. White = speech and advice.** The plot depends on the distinction at least six
   times, and the single most consequential moment in the book is Inga lending away the *Pink* one
   before entering the Three Trick Caverns. Each pearl's entry forbids the other two powers by name,
   and `three_trick_caverns` forbids "Inga is protected" from the location's side as well.

2. **Inga never rescues his own parents.** He conquers Regos, frees every slave in the mines,
   survives three caverns that have killed everyone else for hundreds of years — and still fails.
   **Dorothy frees King Kitticut and Queen Garee**, by lifting the lid of a basket of eggs. This is
   the book's real ending and the easiest thing in it to get wrong; `inga`, `dorothy`, `kaliko`,
   `kitticut` and `garee` each forbid the wrong agent from their own side.

3. **Bilbil is Prince Bobo, the Wizard finds him, and Glinda is the one who restores him.** The
   Wizard states plainly that he cannot do it — the magician is dead and the anti-charm lost. Glinda
   succeeds only through a chain of five transformations (goat → lamb → ostrich → tottenhot → mifket
   → man), the direct attempt having been "an utter failure". `bilbil`, `the_wizard` and `glinda`
   each forbid the shortcut version.

4. **Nobody kills King Gos or Queen Cor.** They flee, they win their bet with Kaliko, and they are
   **drowned in a storm at sea** — a fact that reaches the reader only through Dorothy reading
   Glinda's Record Book. Both entries forbid capture, death by Inga, and repentance.

5. **The rewards nobody takes.** Nikobob refuses a crown on his bended knees and then refuses to be
   made rich, arguing that poverty is what has kept him safe. Rinkitink refuses to reign and is
   dragged home anyway. Bilbil refuses at first to be disenchanted. Each refusal is recorded because
   a summarizer's instinct is to reverse them.

6. **Offstage names promoted to present characters (STU-716).** The **Mermaid Queen** is backstory
   only. **Gilgad is never visited.** The **Long-Eared Hearer and the Lookout** appear in a single
   scene. And the strongest case in the whole Oz corpus: **the Scarecrow is explicitly absent from
   Ozma's banquet** — the text says so in as many words, and says he met the party only weeks later.
   `banquet_guests` forbids his attendance.

## Verified book-10-specific facts

- **The pearls work only on the person carrying them**, which is why Kitticut is helpless — he is
  seized in the act of reaching for them, exactly the danger he had described to his son.
- **Zella carries both pearls across Regos without knowing it** and becomes briefly invulnerable and
  immensely strong; her father does the same and destroys Choggenmugger. Neither ever learns why.
- **The Nome King in this book is Kaliko, not Ruggedo.** He is candid rather than cruel — he tells
  King Kitticut to his face that Gos's story is a lie and that he is keeping him anyway — and he
  refuses on principle to touch anyone under Ozma's protection.
- **Rinkitink's protection is total and entirely passive**: he walks through falling rocks, a
  self-weaving golden net, an opened trapdoor over the Bottomless Gulf and a room full of flying
  knives, and reads his scroll through most of it.
- **Nikobob's advice, not anyone's magic, shapes the settlement of the Twin Islands.** The council
  finds his common sense "both shrewd and sensible" and profits much by his words.

## Roster items skipped, and why

- **Bare generic titles** — `King`, `Queen`, `Prince`, `Captain` — are omitted; this book has four
  Kings (Kitticut, Rinkitink, Gos, Kaliko) and two Queens (Garee, Cor) and the bare tokens would
  bind wildly.
- **Unnamed walk-ons folded into their scene's entry**: Nikobob's wife, the old sweeping woman who
  throws the shoe on the dust-heap, the slave driver and overseers of Coregos, the guards of the
  mines, and the forty rowers of Queen Cor's barge.
- **The hairy red giant of the third Trick Cavern** is unnamed and is recorded inside
  `three_trick_caverns` rather than given an entry.
- **Boboland** is named only as the country Bilbil comes from and is never visited, so it is
  recorded inside `bilbil` rather than given a location entry.

## No roster alignment for this tome

The book-1..6 corpora were written against a generated roster. **Tomes 7–14 have never been run**,
so there is no roster to align to: this corpus is derived from the text alone, covering every entity
a reader would expect a page for.
