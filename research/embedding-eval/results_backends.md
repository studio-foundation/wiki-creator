# STU-577 results — a stronger backend is also negative

Follow-up to STU-468 (whole-sentence context) and STU-490 (mention window /
mean-removal), which both falsified embedding disambiguation on one backend,
`intfloat/multilingual-e5-small`. Open question left by STU-490: is the *backend*
too weak, not only the representation shape?

Same fixture (`tests/fixtures/embedding_golden_pairs.json`, 8 pairs, 3 `same` /
5 `different`), same metric (margin = min(same) − max(different), positive ⇒ one
threshold separates; AUROC = fraction of pairs correctly ordered). Representation
pinned to STU-490's two extremes (`full`, `win±15`); mean-removal dropped
(STU-490 measured it unusable). Only the **backend** varies.

Backends: e5 {small, base, large, large-instruct}, bge-m3, gte-multilingual-base
(bi-encoders, cosine of centroids), plus two cross-encoders scoring each
(context_a, context_b) pair directly (bge-reranker-v2-m3, ms-marco-MiniLM),
aggregated mean/max — no centroid, so the topic direction is never baked into a
single vector.

```
arm                             margin   min(same)  max(diff)  auroc  sep  top `different` pair
e5-small/full                   -0.040   +0.909     +0.949     0.67   no   celaena/chaol   <- STU-468/490 baseline
e5-small/win±15                 -0.025   +0.904     +0.929     0.60   no   celaena/chaol
e5-base/full                    -0.038   +0.913     +0.951     0.73   no   celaena/chaol
e5-base/win±15                  -0.047   +0.892     +0.939     0.47   no   celaena/chaol
e5-large/full                   -0.048   +0.909     +0.957     0.67   no   celaena/chaol
e5-large/win±15                 -0.053   +0.879     +0.932     0.53   no   celaena/chaol
e5-large-instruct/full          -0.038   +0.934     +0.972     0.27   no   celaena/chaol
e5-large-instruct/win±15        -0.026   +0.909     +0.935     0.40   no   dorian/duke perrington
bge-m3/full                     -0.149   +0.660     +0.810     0.60   no   celaena/chaol
bge-m3/win±15                   -0.139   +0.544     +0.683     0.67   no   celaena/chaol
gte-multilingual/full           -0.103   +0.764     +0.867     0.87   no   celaena/chaol
gte-multilingual/win±15         -0.092   +0.624     +0.716     0.67   no   celaena/chaol
bge-reranker-v2-m3/full/mean    -0.009   +0.000     +0.010     0.53   no   celaena/chaol
bge-reranker-v2-m3/full/max     -0.155   +0.003     +0.158     0.53   no   celaena/chaol
bge-reranker-v2-m3/win±15/mean  -0.004   +0.000     +0.004     0.67   no   celaena/chaol
bge-reranker-v2-m3/win±15/max   -0.062   +0.001     +0.063     0.67   no   celaena/chaol
ms-marco-MiniLM/full/mean       -4.044   -8.964     -4.920     0.53   no   celaena/chaol
ms-marco-MiniLM/full/max        -5.752   -5.960     -0.208     0.73   no   celaena/chaol
ms-marco-MiniLM/win±15/mean     -0.120  -10.580    -10.459     0.87   no   dorian/duke perrington
ms-marco-MiniLM/win±15/max      -1.431   -9.466     -8.036     0.80   no   dorian/duke perrington
```

## Reading

- **No arm separates.** Every margin is negative; the best (`bge-reranker-v2-m3/
  win±15/mean`, −0.004) is a rounding step from zero but still on the wrong side,
  and its AUROC 0.67 is no better than e5-small's baseline. The switch criterion
  (margin > 0) is met by nothing.

- **Scaling e5 does not move the wall.** small → base → large → large-instruct all
  sit at margin −0.03..−0.05 with the `same`/`different` band jammed at ~0.9.
  large-instruct with a task-naming instruction is the *worst* ranker of the family
  (AUROC 0.27 full). Model *capacity* is not the missing ingredient.

- **A model with more spread ranks better but still can't split.**
  `gte-multilingual/full` spreads the band down (0.76 vs e5's 0.91) and reaches
  AUROC 0.87 — it *orders* same-above-different well — yet a single global
  threshold still fails, because `celaena/chaol` (0.867) sits above the weakest
  `same` pair (0.764). Ranking ≠ separating; the switch needs a threshold, not a
  ranking.

- **Cross-encoders do not rescue it.** Scoring the pair directly (the hypothesis
  that a centroid throws away the discriminative signal) lands the same verdict:
  bge-reranker collapses every pair toward 0 with `celaena/chaol` still on top;
  ms-marco produces uncalibrated logits that never separate.

- **The blocker is one pair, on every backend: `celaena/chaol`.** It is the top
  `different` pair in 16 of 20 arms. Celaena (the assassin) and Chaol (Captain of
  the Guard) share every scene in these contexts — same room, same dialogue, same
  prose register — so *context similarity* genuinely cannot distinguish them. This
  is not a weak embedding; it is the signal being absent from the representation
  the switch is built on. No backend can read identity out of shared-scene prose.

## Verdict

STU-490's residual hypothesis — a stronger backend rescues the switch — is
falsified. Across two bi-encoder families, an instruction-tuned model, and two
cross-encoders, no arm separates the fixture where e5-small failed. Per the
issue's criterion, document the negative and leave the switch OFF:
`wiki_creator/embedding_disambiguation.py` stays opt-in / default OFF, unchanged.

The three spikes now converge on the same conclusion from three axes
(representation, window/contrastive, backend): same-book same-language
mention-context embeddings do not disambiguate co-scene characters. The remaining
untried axis is a **trained** contrastive head with a real same/different
objective over a labelled cross-book roster — a separate build, not a spike, and
STU-539's contextual LLM adjudication already covers the pairs this would target.

## What was not tried (bounds of this negative)

- A **trained** head (out of scope: no labelled roster, needs a build). Same bound
  STU-490 recorded.
- A **generative LLM** judge on the pair — not an embedding backend, and already
  shipped as `alias-adjudication` (STU-539), which is why chasing an embedding
  switch further has no consumer waiting for it.
- Backends behind an API (OpenAI/Voyage/Cohere embeddings): not evaluated, the
  library corpus is gitignored and local-only, and the on-device negative across
  six open models is uniform enough that an API model clearing it is not a bet
  worth the wiring.
