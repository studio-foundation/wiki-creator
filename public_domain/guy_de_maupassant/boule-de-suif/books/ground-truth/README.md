# Ground truth — *Boule de Suif* (book 1)

Corpus for step 1b of the `validate-wiki-run` skill. Every fact here was verified against
`processing_output/01-boule-de-suif/epub_data.json`, the text the pipeline itself reads — never
against memory. This book was added as a second small, cheap public-domain fixture (after Alice
and Peter Rabbit) that exercises the `fr` language path: one continuous, un-chaptered novella,
~13,400 words / 83,000 characters.

## The epub was trimmed from a Gutenberg anthology

The source Gutenberg file (`pg10746`) is not a standalone edition of *Boule de Suif* — it is a
Maupassant *Œuvres complètes* volume bundling eleven other short stories (*L'Épave*, *Découverte*,
*Un Parricide*, *Le Rendez-vous*, *Bombard*, *Le Pain maudit*, *Les Sabots*, *La Bûche*,
*Magnétisme*, *Divorce*, *Une Soirée*) after it. The committed `01-boule-de-suif.epub` has had the
second content spine file (all eleven other stories) and everything past the *Boule de Suif*
heading in the first spine file removed at the zip/XML level — the story text itself
(`BOULE DE SUIF` to `L'Épave`'s heading) is untouched, byte-for-byte the same 82,984-character
block Gutenberg shipped. The Project Gutenberg header and footer license boilerplate are both kept
intact, unmodified, per redistribution terms.

## Files

| File | Entities |
|---|---|
| `boule_de_suif.json` | Boule de Suif / Élisabeth Rousset |
| `loiseau_household.json` | M. Loiseau, Mme Loiseau |
| `carre_lamadon_household.json` | M. Carré-Lamadon, Mme Carré-Lamadon |
| `breville_household.json` | le comte Hubert de Bréville, la comtesse de Bréville |
| `cornudet.json` | Cornudet |
| `follenvie_household.json` | M. Follenvie, Mme Follenvie |
| `totes.json` | Tôtes (the inn where the standoff happens) |
| `minor_and_offstage.json` | Mme d'Étrelles |

10 on-page named characters + 1 place + 1 offstage mention. This is the book's entire named cast;
see the deliberate omissions below for who and what was left out, and why.

## What this corpus is built to catch

1. **The central plot direction reversed.** The Prussian officer detains the whole coach at the inn
   in Tôtes until Boule de Suif sleeps with him; she refuses for days, is worn down by a coordinated
   persuasion campaign from her fellow travelers, and gives in. A run must not invert this (her
   refusing permanently, the officer being punished, the travelers apologizing) or soften what is
   actually being demanded of her.
2. **The ending's bitter irony flattened.** Having secured everyone's freedom, Boule de Suif is
   shunned by the whole party the next morning and left crying, hungry and unacknowledged in the
   coach — including by Cornudet, the one character who condemned the group's pressure campaign as
   "une infamie" but still doesn't share his food with her at the end. A softened, reconciled, or
   redemptive ending is a hallucination, not a plot summary.
3. **Historical/rhetorical name-dropping mistaken for book characters.** During the persuasion
   campaign the travelers cite Judith and Holopherne, Lucrèce and Sextus, Cléopâtre, Hannibal, and
   later Jeanne d'Arc, du Guesclin and Napoléon Ier as rhetorical examples and political daydreams —
   none of them are characters *in* this book, appear on no page, and have no in-story facts. A run
   creating a page for "Cléopâtre" as if she travels in the coach, or attributing any in-story event
   to one of these names, is a fabrication this corpus is built to catch.
4. **Household identity confusion.** Four married couples share a surname each (Loiseau,
   Carré-Lamadon, Bréville, Follenvie); a run must keep each spouse's distinct opinions, actions and
   dialogue attributed to the right one — e.g. it is Mme Loiseau, not her husband, who argues most
   bluntly that Boule de Suif has no right to refuse "since it's her trade"; it is the count, not
   Carré-Lamadon, who personally walks arm-in-arm with Boule de Suif to make the campaign's final
   appeal.
5. **Political-allegiance swap.** Boule de Suif is an outspoken Bonapartist; Cornudet is the
   republican democrat contemptuous of Napoléon III ("Badinguet"). These are opposite and load-bearing
   to a scene (her flaring up at his jab) — swapping them is a concrete, checkable error.

## Deliberate omission: the two nuns and the Prussian officer

Both are constantly present and load-bearing to the plot (the elder nun's argument about divine
forgiveness is what finally breaks Boule de Suif's resistance; the officer is the antagonist of the
whole standoff), but neither is ever given a stable proper name to write ground truth against. The
text calls them only "les bonnes soeurs" / "la religieuse" and "l'officier prussien" throughout —
lowercase common-noun descriptions, not names. One exception: the elder nun mentions in passing that
her younger companion is "la chère soeur Saint-Nicéphore" — a real name, but it occurs exactly once
in the whole book, well under `min_mentions_absolute: 3`, and there is no other page for it to
qualify or refute. Per the same reasoning as Peter Rabbit's unnamed mouse, cat and sparrows: a
common-noun or single-mention alias would either poison the substring lookup against unrelated prose
(`la religieuse`, `l'officier` are generic enough to appear anywhere) or bind to no page at all. None
of the three get a `ner.character_names` config entry either, for the same reason Peter Rabbit's
unnamed creatures didn't — forcing recognition of a generic descriptive phrase as PERSON would create
false-positive matches elsewhere in the text, not just at this character's real mentions.

## Deliberate omission: historical and rhetorical name-drops

Cléopâtre, Judith, Holopherne, Lucrèce, Sextus, Hannibal ("Annibal"), Jeanne d'Arc, du Guesclin and
Napoléon Ier are all cited by the travelers as historical or legendary analogies during the
persuasion campaign, or as wistful political daydreams about France's future savior. None of them are
characters in this book's story — they never appear, speak, or act on the page. They are deliberately
*not* given ground-truth entries (there is nothing to verify facts against — they have no in-book
facts), and are instead named in "What this corpus is built to catch" above as the exact failure mode
a run inventing pages for them would represent.

## Deliberate omission: Boule de Suif's own child, and bit-part background figures

Her child, raised by peasants at Yvetot, is mentioned once and never named. The village bedeau, the
coachman, the Prussian soldiers doing chores in the street, and the innkeeper's serving girls are all
described only by role, never by name. Same reasoning as above: no stable alias, left out rather than
forced.

## One same-file alias collision, justified rather than fixed

`m_loiseau`'s only literal alias in the text is the bare surname `Loiseau` (used ~50 times) — the
text never once writes "M. Loiseau" as a standalone form (only the joint introduction "M. et Mme
Loiseau"). That makes it, unavoidably, a substring of `mme_loiseau`'s alias `Mme Loiseau`. Unlike the
Peter-Rabbit `Mr. McGregor` / `McGregor's garden` case, there is no alternative literal form to switch
to here — the text simply doesn't use one. Both entities live in the same file with `m_loiseau` listed
first (the shorter-binding entry), per the skill's rule 2; the linter's alias-collision WARN for this
pair is expected and is not a corpus bug.

## Verified behaviour

Not yet exercised against a run — no live pipeline run has been made on this book (per
`CLAUDE.local.md`, this skill never runs the pipeline). The linter (`lint_ground_truth.py`) has been
run clean; the audit gates (`audit_run.py gt-validate`, zero-false-positive and poisoned-page checks)
are the user's to run once a real run exists. Until then, treat the roster, page set and extraction
quality as unmeasured, per the skill's step 8.
