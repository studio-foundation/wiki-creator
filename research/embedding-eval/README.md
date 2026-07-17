# embedding-eval (STU-490)

Spike: retry semantic entity disambiguation with a **mention-window** representation
after STU-468 falsified the whole-sentence-context embedding (band 0.906–0.949,
nul separation, dominated by scene topic).

`measure.py` reuses the committed fixture
`tests/fixtures/embedding_golden_pairs.json` (the STU-468 baseline-to-beat), so the
eval is hermetic. Each entity's name/alias occurs verbatim in every one of its
baked contexts, so a tight window centred on the located name is sliced without the
run's STU-489 offsets — those matter for production wiring, not the research
question "does narrowing to the name-window remove the topic signal?".

Arms, scored on the 8 golden pairs (3 `same`, 5 `different`):

- `full` — STU-468 baseline (whole context, cosine).
- `win±K` — char window around the name, K ∈ {80,60,40,25,15}.
- `+meanrm` — subtract the corpus mean vector before cosine (removes the dominant
  shared-topic direction; the cheap contrastive proxy, no trained head — 7 entities
  is no training set).

Metrics: **margin** = min(cosine over `same`) − max(cosine over `different`)
(positive ⇒ one threshold separates cleanly); **AUROC** = fraction of
(same, different) pairs correctly ordered.

Run (needs the `embeddings` extra + the cached e5-small):

```bash
HF_HUB_OFFLINE=1 PYTHONPATH=$(pwd) python research/embedding-eval/measure.py
```

## Result: negative (see results.md)

No arm separates. Best margin −0.025 (`win±15`), best AUROC 0.73 — both within
noise of the STU-468 baseline (margin −0.040, AUROC 0.67). The mention window does
not rescue e5-small disambiguation; mean-removal makes the threshold unusable.
**Switch stays default OFF** (`embedding_disambiguation` is opt-in and untouched).
