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

**Do not adopt GLiREL or schema-LLM on the strength of the numbers above.** Not
because they lose — read the tables — but because a win over a baseline that is a
third dict-order noise is not evidence about relation extraction. It is evidence
about the bug. The two ideas the ticket names (type and direction at discovery;
dialogue-based signal) remain the right direction, and STU-467 should carry them
once there is a baseline worth beating.

### Issues this spike should spawn

- **bug** — `build_cooccurrence_graph` slides its window over an entity-ordered
  list; output depends on dict order (28–33% of pairs). Blocks STU-467.
- **bug** — `Garrow` (112 mentions), `Durza` (35) typed ORG; `Katrina` EVENT;
  `Ra'zac`/`Varden`/`Kull` typed PERSON. 26/66 of the PERSON roster are not people.
- **bug** — alias-resolution merged `Solembum` (the werecat) into `Eragon`.
