## Recommendation

Hand-written. The tables above are generated.

### The ticket asks the wrong question first

STU-467 proposes replacing co-occurrence discovery with GLiREL or schema-guided
LLM extraction, on the grounds that proximity is not relation. That premise is
sound and the ticket should stay open. But three measurements taken before any arm
ran say the comparison cannot decide anything yet, because the thing being
compared against is not doing what its name says.

**1. The window is not a text window.** `build_cooccurrence_graph` slides five
sentences over `chapter_sentences` and gates on `_MAX_DIRECT_INTERACTION_GAP`.
`chapter_sentences` is built by iterating `mentions_by_entity` — a dict keyed by
entity — so it is ordered by entity, then by position, and each entity contributes
at most three context sentences per chapter. Of 370 sentence pairs the window
reads as adjacent across two entities, the median real distance in the chapter is
**4151 characters**; 7% are actually adjacent prose. 173 of the 501 emitted pairs
are never within one sentence of each other anywhere in the book.

**2. So roughly a third of the graph is dict order.** Shuffle the roster, re-run
the same function on the same text with the same parameters: **28–33% of the pairs
change**. Entity insertion order carries no information about the book. This is not
a weak signal, it is a partly arbitrary one.

**3. The roster is wrong in both directions.** Discovery filters `type ==
"PERSON"` over the split-clusters typing. Of the 66 entities that pass, **26 are
not people** — `Ra'zac`, `Varden`, `Kull`, `Forsworn` (FACTION; 154/139/31/12
mentions), `Empire` (ORG), `Tronjheim`, `Farthen Dûr`, `Yazuac`, `Helgrind`
(PLACE), `Zar'roc`, `Isidar Mithrim` (OTHER). And **10 people are missing**,
including **Garrow** (112 mentions, the uncle who raises Eragon and whose death
drives the plot) typed ORG, **Durza** (35, the book's antagonist) typed ORG, and
`Katrina` typed EVENT. Precision 61%, recall 80%.

Garrow matters beyond the count. "Eragon is Garrow's nephew" is the ticket's own
example of the implicit relation co-occurrence cannot see — and no relation
extractor, however good, can find it, because the entity never reaches the graph.
GLiREL found it in a two-chapter smoke test the moment it was handed a roster
containing him.

### One of the ticket's premises did not survive

STU-467 lists "rate les relations implicites ou hors-champ (« son père », jamais
nommés dans la même phrase)" as a motivation. On this book it is close to empty.

Of 109 gold pairs, **7 are implicit** — never within one sentence of each other
anywhere in 60 chapters — and all seven are single-chapter walk-ons: Hrothgar and
Korgan, Baldor and Elain, Ajihad and Morzan. Over a novel, a real relation gets a
sentence naming both sooner or later. Eragon and Garrow, the example the ticket
reaches for, are textually adjacent in 17 chapters; the shipped pipeline misses
them for the entity reason above, not for a windowing one.

So the implicit stratum is 6% of the gold and all of it is marginal. No arm scores
above F1 0.07 there, on n=7 — that is noise, not a finding. The case for typed
discovery has to rest on type and direction, which is where GLiREL's real deficit
is, not on implicit reach.

### What the arms then showed

The numbers agree with the diagnosis, and more sharply than expected.

| arm | det F1 | det P | det R | type (e2e) | direction | pairs |
|---|---|---|---|---|---|---|
| `cooccurrence_shipped` | 0.200 | 0.122 | 0.560 | — | — | 501 |
| `cooccurrence_fixed` | **0.507** | 0.415 | 0.651 | — | — | 171 |
| `glirel` | 0.498 | 0.443 | 0.569 | 0.202 | 0.091 | 140 |
| `llm_schema` | 0.864 | 0.784 | 0.963 | 0.817 | 0.854 | 134 |

Read this table with caveat 1 open, because `llm_schema` is not comparable to the
rest. The gold is built by an LLM; `llm_schema` is an LLM. Its 0.864/0.817/0.854
is in large part a measure of two LLM runs agreeing on what a relation is and how
to type it — a different model (sonnet vs the gold's opus) and a production-shaped
task blunt that, nothing removes it. Its number is an upper bound on the *method*,
not a measurement anyone can bank. What it does establish is a ceiling: typed,
directed discovery in one pass is achievable, and the two non-LLM arms are far
below it.

**The comparison that survives the confound is the three non-LLM rows, and among
them the finding is co-occurrence.** Sliding the window over the chapter instead
of over an entity-ordered list takes detection F1 from 0.200 to 0.507 — two and a
half times — and lands level with GLiREL. Almost all of it is precision: 0.122 to
0.415. The shipped arm emits 501 pairs to find 61 of the gold's 109; the fixed arm
emits 171 to find 71. Its extra recall is free.

That is the answer to "GLiREL or co-occurrence": they tie on detection, the axis
where they are comparable, and one of them is a change to how one list is built.

GLiREL does buy something co-occurrence cannot give at any price: a type at
discovery, where `build_cooccurrence_graph` emits `None` by construction. But it
buys it weakly — 0.202 end-to-end, with a threshold picked by looking at the gold
and labels that were never swept — and it cannot supply direction at all: 0.091,
because it emits a directed head -> tail triple and most relations are
`symétrique`. The pipeline needs direction. On the evidence here the typed-discovery
prize goes to schema-LLM, not GLiREL — but only the ceiling is demonstrated, not
the margin, and it is the one arm the gold flatters.

### What to do

**Fix the mechanism before shopping for a replacement.** In order:

1. **Slide the window over the chapter.** The sentences should be the chapter's,
   in the chapter's order — not a per-entity sample stitched in dict order. This is
   the `cooccurrence_fixed` arm, and it is a small change to one function.
   Everything else in the mechanism (count, chapter floor, adjacency gate, negation
   filter) is kept.
2. **Fix the entity typing.** `Garrow` and `Durza` are ORG. This is upstream of
   STU-467 and is the binding constraint on every arm, including the ones the
   ticket wants to buy. It is also not this ticket's work — it belongs with
   STU-470/521 (NER) and the classification stage.

Then re-run this bake-off. The arms and the gold are built; re-scoring is minutes.

Then re-run this bake-off and decide about GLiREL and schema-LLM against a
baseline worth beating. **Do not decide on the numbers above.** A win over an arm
that is a third dict-order noise is evidence about the bug, not about relation
extraction — and the one arm that wins decisively is the one the gold flatters.
The ideas the ticket names (type and direction at discovery; dialogue-based
signal) stay right; only the comparison is not yet decidable.

**If the fix lands and typed discovery is still wanted, the shortlist is
schema-LLM, not GLiREL.** GLiREL was the ticket's headline candidate on the
grounds of being a fast local encoder, and it is — but it needs a label sweep and
a threshold calibration before it emits anything at all, and it structurally
cannot express `symétrique`. Its ceiling on type (0.202) sits below what the fixed
window already gives on detection for free. A GLiREL loss here reads "not
demonstrated" (caveat 2), so this is not a verdict — but it is not the cheap win
the ticket assumed either.

The honest next measurement, if that path is taken: score schema-LLM against a
**human-annotated** gold on a subset. Everything else in this harness can be
reused; only `build_gold.py` changes. Nothing else removes caveat 1, and caveat 1
is the only thing standing between "schema-LLM at 0.86" and a decision.

### Issues this spike should spawn

- **bug** — `build_cooccurrence_graph` slides its window over an entity-ordered
  list; output depends on dict order (28–33% of pairs). Blocks STU-467.
- **bug** — `Garrow` (112 mentions), `Durza` (35) typed ORG; `Katrina` EVENT;
  `Ra'zac`/`Varden`/`Kull` typed PERSON. 26/66 of the PERSON roster are not people.
- **bug** — alias-resolution merged `Solembum` (the werecat) into `Eragon`.
