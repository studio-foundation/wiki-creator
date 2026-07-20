# STU-576 results — a trained contrastive head is also negative, and says why

Third and last lever on the STU-468 line. STU-468 falsified whole-sentence cosine,
STU-490 the mention window, STU-577 the backend. All three kept the *untrained*
cosine of a generalist model; this one replaces it with a real discriminative
objective (supervised InfoNCE over entity labels) on a projection above the frozen
e5-small backbone.

## The blocking prerequisite did not exist

The issue states a labelled cross-book roster is a separate build and "le vrai coût".
Measured against the real artifacts, it is already on disk: `*_full.json` persists
`mention_spans_by_chapter` (STU-489), one `{surface, start, end}` per occurrence into
the chapter text in `chapters.json`. Grouping those spans by canonical entity **is**
the label.

| cache | entities (≥8 windows) | windows |
| -- | -- | -- |
| `01_eragon` | 62 | 6932 |
| `01-the_lion_the_witch_and_the_wardrobe` | 15 | 1030 |
| `01-throne-of-glass` | 3 | 34 — 5-chapter subset cache, unusable |

STU-490 concluded "7 entities / 8 pairs, no training set" from the committed
*fixture*, which was chosen for hermeticity, not from a run. Same shape as STU-539's
premise error: a subset artifact answered a different question than the one asked.

The 41 hand-written gold characters (`library/*/*/books/ground-truth/`) are **not**
the training set either, and cannot be: only 6 of 41 still have ≥2 distinct surface
forms separated in the extraction, because clustering already folded the aliases into
one entity. The gold's value here is nil — the registry's own clusters carry the same
labels, at 200× the volume.

## Protocol

Windows are **masked over the mention itself** (`[NAME]`). Leaving the name in makes
the task string-matching: STU-490's `win±K` kept it, which is why its `different`
pairs still scored 0.949 — that arm never tested disambiguation.

Each entity's windows are split into two halves **by chapter**, so a `same` pair is
two centroids of one person built from disjoint scenes. Eval is **leave-one-book-out**;
an in-domain arm (train and eval on the held-out book) is carried as a leak control —
without it, "the head learnt nothing" and "there is nothing to learn" are the same
number. 3 seeds, mean ± sd.

```
arm                                margin           auroc           fixture  same/diff

-- held out: 01-the_lion_the_witch_and_the_wardrobe  (15 entities)
raw (no head)                      -0.085 ±0.000   0.645 ±0.000   -0.019   15/210
head, in-domain (leak control)     -0.061 ±0.006   0.916 ±0.024   -0.013   15/210
head, trained on 62 held-in ids    -0.083 ±0.017   0.725 ±0.012   -0.032   15/210

-- held out: 01_eragon  (62 entities)
raw (no head)                      -0.084 ±0.000   0.680 ±0.000   -0.019   60/3540
head, in-domain (leak control)     -0.111 ±0.012   0.940 ±0.006   -0.032   60/3540
head, trained on 15 held-in ids    -0.069 ±0.003   0.698 ±0.011   -0.013   60/3540
```

## Reading

- **The objective works.** In-domain AUROC goes 0.68 → 0.940 and 0.645 → 0.916. The
  representation is not degenerate and the training loop is not broken; a head over
  frozen e5-small can rank same-person pairs above different-person ones for
  identities it has seen. Neither prior spike could say this.
- **Transfer is real but small, and needs identities.** 62 held-in ids lift Narnia
  0.645 → 0.725; 15 held-in ids lift Eragon 0.680 → 0.698, inside the seed spread.
  More books would buy more ranking. They would not buy the criterion:
- **Margin is negative in every arm — including in-domain, at 0.94 AUROC.** No single
  threshold separates `same` from `different`, even when the head has memorised the
  cast. The operating point is per-entity, not global, and `EmbeddingJudge.propose`
  needs a global one (`DEFAULT_PROPOSE_THRESHOLD = 0.86`). So this is not a
  data-quantity result that a bigger corpus fixes.
- **Ticket criterion failed.** On the committed 8-pair fixture, masked: raw −0.019,
  best head −0.013. Never positive.

## Why the whole line is dead, not just this arm

Masking removes the name, training removes everything learnable — and the residual
failure changes shape. Under raw cosine the blocking pair is `celaena / chaol`
(STU-577's finding: the assassin and the Captain of the Guard share every scene). With
masking + head, that pair falls to 6th and the blocker becomes `captain westfall /
chaol`:

```
head    +0.992 same       the assassin / celaena
        +0.990 same       dorian havilliard / dorian
        +0.980 different  celaena / dorian
        +0.973 different  chaol / duke perrington
        +0.967 same       captain westfall / chaol     <- blocks
```

Two of three `same` pairs are now at the very top; the one that fails is the
name-versus-title pair. That is not noise, it is the definition of the task:
**a character carries a second name precisely because it is used in different
situations.** Captain Westfall is named on duty, Chaol in private. A representation
whose whole content is the situation is measuring the thing that *differs* between two
aliases of one person. Context similarity is not identity, and no amount of contrastive
training on context can make it be.

This is also why alias-adjudication (STU-539/543) succeeds where this fails: it reads
a sentence that *asserts* the identity ("Lillian Gordaina was Celaena Sardothien"),
which is a claim about the world, not a similarity between two contexts.

## Verdict

Negative on the issue's stated criterion (`margin > 0`). Documented; the switch stays
default OFF — `wiki_creator/embedding_disambiguation.py` is untouched, still opt-in.
With STU-468 (context), STU-490 (window), STU-577 (backend) and this (objective), all
four axes of the embedding approach are measured and none separates. Recommend closing
the line rather than opening a fifth arm.

## Bounds of this negative

- **Two books, 77 identities.** 13 of 16 library books have no span cache, so
  leave-one-book-out is leave-one-of-two-out. Extraction is deterministic and offline,
  so widening the corpus is machine time, not labelling — but the in-domain margin
  says more identities would move AUROC, not the threshold.
- **Frozen backbone.** Fine-tuning e5-small end to end was not tried. It would raise
  in-domain fit, which is already 0.94 and already not the constraint.
- **The fixture is Throne of Glass only**, and its `01-throne-of-glass` cache is a
  5-chapter subset, so the acceptance fixture could not be re-derived at full-book
  scale. Re-extracting it needs GLiNER (`invented_names: true`, STU-521).
