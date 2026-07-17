# What the relationship classifier actually returns (STU-554)

STU-554 measures that half the discovered graph never reaches a page: a pair is
discovered, the classifier returns no usable type, and STU-501 correctly omits an
untyped relation from every reader-facing surface. `usable_relationship_type`
flattens four very different outcomes into one `None`, so "no usable type" named a
symptom and no cause:

- a real JSON `null` — the model read the excerpts and declined;
- the literal strings `"null"` / `"none"` — a contract or prompt defect;
- an empty string;
- a Studio failure that never reached the model at all.

Which one dominates decides the fix, so it is measured before any hypothesis.

    python runners/measure_classifier_verdicts.py \
      --book library/christopher_paolini/inheritance/books/01_eragon.yaml \
      --role-contexts --out /tmp/verdicts.eragon.json

Pairs come from the cached `relationships.json` and are filtered by the production
stage's own `_should_classify_pair`, so the rejection rate below is the pipeline's.

## The model declines. It does not fail.

Eragon, 255 classifiable pairs, `role_contexts` and `book_config` passed (the
`classify_relationships.py` path — see *the counter is vestigial* below):

| bucket | pairs | |
|---|---|---|
| `declined_null` | 141 | 55% |
| `typed` | 107 | 42% |
| `error:studio_output_json_parse_error` | 5 | 2% |
| `error:studio_run_timeout` | 2 | 1% |
| `sentinel_string` | 0 | — |
| `empty_string` | 0 | — |

**Zero sentinels, zero empty strings.** The rejection is not a contract defect, not
a prompt-format defect, and not a parsing defect: the model returns valid JSON and
refuses to type the pair. Widening the vocabulary was already ruled out by STU-554
itself (STU-472 and STU-477 were merged when the ticket's run happened). So the
remaining question is not *why does the answer break* — it is *should declining
mean deleting*, which is STU-554's piste 4, and it is the only piste the cause
supports.

The 55% here reproduces the ticket's 84/169 = 50% on a differently-built pair list,
so the defect is robust — it is not an artifact of the STU-540 run.

## Declining correlates with thin evidence — and that proves nothing yet

| excerpts in the pair's payload | decline rate |
|---|---|
| 1 | 55/68 = 81% |
| 2 | 44/61 = 72% |
| 3 | 15/34 = 44% |
| 12 | 2/16 = 12% |

| co-occurrence count | decline rate |
|---|---|
| 6–9 | 37/41 = 90% |
| 10–19 | 48/70 = 69% |
| 20+ | 50/130 = 38% |

The decline rate collapses as excerpts accumulate, which is what STU-554's piste 2
predicts. **It is also exactly what a working filter looks like**, and this table
cannot tell the two apart: few excerpts means a weak pair, and a weak pair may
genuinely have no relation to type. The correlation is confounded by construction,
so it must not be read as "the prompt starves the model" — that reading needs a
gold that says which declined pairs are real, and the only one that exists is
STU-540's 12 hand-judged pairs. Widen to Narnia (artifacts cached) before sizing a
fix on this axis.

## Two things found on the way, neither of them the defect

**7 pairs (3%) die on a Studio error, not on judgment** — 5 unparseable outputs, 2
timeouts — and the stage returns `success` regardless. Small next to the 55%, and a
separate defect: those pairs were never judged at all.

**`stats.classified` is vestigial.** STU-554 proposes reading it against
`pairs_above_threshold`. It is written only by
`relationship_extraction.classify_relationships`, which runs only when
`additional_context.classify` is true — and `classify` appears in no pipeline, no
input, and no book YAML. That path is dead in production; `classify_relationships.py`
(the wiki-preparation pre-step) does the real classification and writes no such
counter. On a real run `stats.classified` is always `0`, which is what the cached
Eragon `relationships.json` shows. Instrumenting the loss needs a counter that the
live path actually writes.
