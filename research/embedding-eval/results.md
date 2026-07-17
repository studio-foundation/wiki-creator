# STU-490 results — mention-window disambiguation is also negative

Model: `intfloat/multilingual-e5-small`. Fixture:
`tests/fixtures/embedding_golden_pairs.json` (8 pairs, 3 `same` / 5 `different`).
Separation criterion: **margin > 0** (a single cosine threshold splits `same` from
`different`). STU-468 baseline separation is nul.

```
arm               margin   min(same)  max(diff)  auroc  separates
full              -0.040   0.909      0.949      0.67   no      <- STU-468 baseline
full+meanrm       -0.448   -0.207     0.241      0.67   no
win±80            -0.044   0.903      0.948      0.60   no
win±80+meanrm     -0.450   -0.231     0.219      0.67   no
win±60            -0.043   0.904      0.947      0.33   no
win±60+meanrm     -0.394   -0.160     0.234      0.73   no
win±40            -0.040   0.900      0.940      0.53   no
win±40+meanrm     -0.403   -0.230     0.173      0.67   no
win±25            -0.041   0.900      0.941      0.40   no
win±25+meanrm     -0.374   -0.219     0.155      0.67   no
win±15            -0.025   0.904      0.929      0.60   no
win±15+meanrm     -0.237   -0.221     0.016      0.73   no
```

## Reading

- **Mention window does not separate.** Narrowing from the full sentence to ±15..80
  chars around the name leaves `same` and `different` fully overlapped (margin stays
  negative, best −0.025 at ±15 vs −0.040 baseline — inside the noise of an 8-pair
  set, AUROC granularity 1/15≈0.067). The topic/style domination STU-468 found is
  not in the surrounding scene words; e5-small collapses all English prose of one
  book to ~0.9 cosine regardless of who is named.
- **Mean-removal (contrastive proxy) makes it worse.** Subtracting the corpus mean
  over-separates in the wrong direction — `same` centroids are pushed apart harder
  than `different` (min(same) goes negative while max(diff) stays positive), so the
  threshold is unusable (margin −0.24..−0.45). AUROC never clears 0.73.
- **No arm both ranks and separates.** The two arms with AUROC 0.73 have the worst
  margins; no configuration gives a usable operating point.

## Verdict

STU-490's hypothesis is falsified on the acceptance fixture. The mention-window
representation is **not** a viable disambiguation signal over generalist e5-small
embeddings on same-book, same-language prose. Per the issue's fallback: document the
negative and leave the switch OFF. `wiki_creator/embedding_disambiguation.py` stays
opt-in / default OFF, unchanged.

## What was not tried (bounds of this negative)

- A **trained** contrastive head with a real same/different objective. There is no
  training data here (7 entities, 8 pairs); it needs a labelled roster across books,
  which is a separate build, not this spike.
- Windows sliced from a **full-book run** via STU-489 offsets rather than from the
  fixture's baked contexts. Equivalent for the research question (topic vs
  name-region), but a full-run eval would test more pairs. Not pursued because the
  representation shows no signal even at its most favourable ±15 window.
- A stronger/instruction-tuned or reranker-style model. Out of scope: the ticket
  asked whether *representation shape* (window, contrastive) rescues the STU-468
  backend, not whether a different backend would.
