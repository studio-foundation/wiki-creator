# Does type + direction at discovery pay? (STU-540)

**Yes — buy schema-guided discovery. But not by bolting it in front of the
classifier, because the classifier is where the relations are being lost.**

STU-467's spike said *fix the window before buying anything*. STU-536 and STU-537
landed those fixes; this is the narrower question they unblocked, decided against a
human gold instead of an LLM one.

## The gold is a person now

The spike's caveat 1 was that `build_gold.py` is an LLM and `run_llm_schema.py` is
an LLM, so that arm partly graded itself. Lifting it did not need the 60-chapter
hand annotation the ticket budgeted for. It needed 111 keypresses, because a human
is only required where the arms *disagree* — agreement between an LLM and a regex
is not the confound.

Ariane adjudicated, blind to which arm claimed what, on the book's own text:
51 roster entries, 40 disputed pairs (20 sampled per arm), 20 typed pairs.

**The confound was pushing the other way.** Against the LLM gold, schema-guided
typing scored 0.817. Against a human: **20/20**. The spike understated it.

## The decision

Production is not co-occurrence. It is co-occurrence *plus* the per-pair
classifier, and STU-501 omits any pair the classifier leaves untyped — so the
pipeline already has a precision stage after the window. Scoring raw discovery
against a schema-guided LLM compares half a pipeline to a whole one. The arm that
decides is `run_cooccurrence_classified.py`: real discovery, real classifier, real
STU-501 filter — what a reader would actually have seen.

| | production (cooc + classifier) | llm_schema |
|---|---|---|
| pairs reaching the reader | 80 | **118** |
| pairs the other misses | 11 | **54** |
| precision on those (human-voted) | 3/3 | 18/19 = 0.947 |
| estimated real, unique | ~11 | **~51** |
| junk pairs (non-character or one person twice) | 0.087 | **0.017** |
| type + direction | (classifier, unmeasured here) | **20/20** |

Both arms agree on 62 pairs. Schema-guided discovery surfaces **~40 more real
relations than the shipping pipeline**, with 5x less junk. The classifier does not
rescue co-occurrence.

The production-only column is 3 voted rows. It is thin, and it is not what the
decision rests on — the 54-vs-11 asymmetry is, and no plausible reading of 3 rows
closes a 43-pair gap.

## What the measurement found that the ticket did not ask

**The classifier is the bottleneck, not the window.** It drops **84 of 169**
discovered pairs as untyped — half the graph, silently, because STU-501 then omits
them. Of the 12 dropped pairs Ariane judged, **8 were real and 4 were false**: it
destroys two true relations for every false one it removes. STU-536 fixed the
window and the loss simply moved downstream.

This changes the shape of the buy. `cost.md` prices schema discovery *feeding* the
classifier at 1.85x, but that design is self-defeating: the schema pass would be
cut in half by the same filter. It does not need to be. The schema pass already
emits type and direction at human-verified 20/20, so the classifier has no
existence question and no type question left to answer — only `evolution` and
`key_moments`, which are prose about an already-typed pair. A prose stage rejects
nothing.

So the work is not "insert an LLM before the classifier". It is "let discovery type
the pair, and demote the classifier to what only it does". That is a design, not a
flag, and it is the follow-up this decision opens.

## Costs

Measured in `cost.md`. The two calls are the same size (5972 vs 6274 tokens) and
STU-536 cut Eragon to 173 pairs against 174 chunks, so "one call per chunk" buys
roughly the call count the pipeline already makes: **1.07x** if discovery replaces
the classifier's typing, 1.85x if both run in full. 60% of every call, on both
architectures, is the injected Studio system prompt rather than book text.

## What this does not measure

- **Recall.** A pair neither arm found is invisible to arm-vs-arm adjudication.
  That is the price of not annotating 60 chapters, and it is why the numbers here
  are precision and counts, never F1.
- **One book, one annotator.** Eragon, held out, and the person who knows it.
  Nothing here says the ratio holds on Narnia.
- **The 62 agreed pairs.** Never adjudicated — they are assumed real, and both arms
  are credited for them equally.
- **GLiREL** stays out, on the spike's evidence (0.202 typing, 0.091 direction,
  nothing at all at its default threshold). A defeat that reads "not demonstrated":
  the label sweep was never run.

## Defects this surfaced

Both are live on `main`, neither is a relation-discovery problem, and the human
adjudication is what made them visible:

- **STU-549** — alias-resolution absorbs `Galbatorix`, `King Galbatorix` and
  `The Shade` into `Eragon`, and `Rider` into `Morzan`. The series antagonist has
  no wiki page; he is an alias of the protagonist. Mention counts are *not* merged,
  which is why no notability threshold ever flagged it.
- The classifier's 2:1 real-to-false drop rate, above.

`aliases.yaml` records the four roster entries that are one person under two names
(`Neal`/`Evan`/`The Shade`/`Carsaib`) — hand-written, because alias-resolution is
the stage that missed them, so no artifact knows.

## Reproduce

```bash
make run-extraction BOOK=library/christopher_paolini/inheritance/books/01_eragon.yaml
make run-resolution BOOK=library/christopher_paolini/inheritance/books/01_eragon.yaml
cd research/relation-eval
python build_corpus.py --processing-output ../../library/christopher_paolini/inheritance/processing_output/01_eragon \
                      --first-chapter id_7 --last-chapter id_66
python explicit_pairs.py --roster roster.json --out explicit_pairs.json
python runners/run_cooccurrence.py --arm fixed --roster roster.json
python runners/run_llm_schema.py --roster roster.json --explicit-pairs explicit_pairs.json --model claude-sonnet-5
cd ../.. && python research/relation-eval/runners/run_cooccurrence_classified.py \
    --book library/christopher_paolini/inheritance/books/01_eragon.yaml \
    --pairs research/relation-eval/predictions.cooccurrence_fixed.json \
    --out research/relation-eval/predictions.cooccurrence_classified.json
cd research/relation-eval
python adjudicate.py --corpus corpus.jsonl --roster roster.json
python vote.py
python score_adjudication.py --votes votes.json
```

**The oracle roster is gone.** `retype_roster.py` existed to undo spaCy's typing of
invented names; STU-537 does that upstream with GLiNER, and `build_corpus.py` now
reports `mistyped: 0` on the shipped roster. The arms run on what production
produces, which removes an LLM from the loop. `build_gold.py` is not run at all —
the adjudication replaced it, and it was the confound.
