# STU-468 — Eval Results (negative)

**Date:** 2026-07-12
**Verdict:** the designed centroid-cosine approach does **not** discriminate
character identity within a single book. Infrastructure shipped opt-in and
**defaults OFF**. Do not enable without a working representation.

## What was tested

Model: `intfloat/multilingual-e5-small` (real, on GPU/CPU). Representation:
per-entity centroid = L2-normalized mean of the entity's mention-context
sentence embeddings (`passage:` prefix). Score: cosine between two entities'
centroids. Data: self-contained golden fixture
`tests/fixtures/embedding_golden_pairs.json` — real throne-of-glass mention
contexts baked in (`processing_output/` is gitignored), 8 labelled PERSON
pairs (3 same, 5 different), including the flagship unlock (`the assassin` ↔
`Celaena`, zero char overlap) and the flagship veto (`Dorian` ↔ `Duke
Perrington`).

Reproduce: `pip install -e '.[embeddings]' && python scripts/tune_embedding_thresholds.py`

## Result

```
cosine  label      pair
0.949  different  celaena / chaol              <- most-similar pair is DIFFERENT
0.947  same       dorian havilliard / dorian
0.923  same       the assassin / celaena       <- the unlock, but below 3 different pairs
0.914  different  dorian / duke perrington     <- the veto target
0.912  different  chaol / duke perrington
0.909  same       captain westfall / chaol     <- below dorian/perrington
0.907  different  dorian havilliard / duke perrington
0.906  different  celaena / dorian
```

All eight pairs fall in a narrow band **0.906–0.949**. Same-person and
different-person pairs are **interleaved**: no threshold separates them. Best
F1 (τ=0.92) is precision 0.67 / recall 0.67 — unusable.

- **Proposer** at any τ that catches the true aliases (≤0.923) also merges
  `celaena / chaol` (0.949, different). Unusable.
- **Veto** at τ≤0.90 is inert (every pair scores higher); to veto
  `dorian / duke perrington` (0.914) requires τ>0.914, which also vetoes the
  true aliases `captain westfall / chaol` (0.909) and `the assassin / celaena`
  is borderline (0.923). Cannot separate.

## Why

Within one novel, every mention context shares the same setting and vocabulary
(castle, competition, Adarlan, court). e5 sentence embeddings capture
**topic/domain**, not **character identity**. Two different characters who
appear in the same scenes have near-identical context distributions — hence
`celaena / chaol` (different, co-present in most scenes) scores highest.

## Data limitation

Stored mention contexts are 2–3 full sentences with **no character offsets**
(`entity_extraction.py`; `Mention.start/end` are always `None`). The one signal
that might discriminate — a tight window around the mention token capturing what
the character *does/is*, rather than the whole shared-setting sentence — cannot
be extracted from the current artifacts. Adding offsets upstream is a
prerequisite for any future attempt.

## Decision

Ship the infrastructure (module, judge, alias-resolution wiring, tests) as
**inert, opt-in, default-OFF**. It is correct and tested; only the
representation is non-viable on this data. The eval did its job — it falsified
the central hypothesis before the feature was enabled.

Follow-up options (new issue): (a) add mention offsets + embed a tight window;
(b) contrastive / discriminative scoring against a background distribution;
(c) accept that lexical + LLM confirmation is the ceiling for intra-book
disambiguation and drop the embedding path.
