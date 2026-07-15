## Recommendation

**Replace `wiki-ner-en` with GLiNER zero-shot (`urchade/gliner_large-v2.1`), with the
labels in the sweep table.** All three of the spike's questions resolve, but not in
the shape the ticket posed them.

### 1. Keeping tok2vec is not an option — it does not generalise at all

`wiki-ner-en` reports `ents_f: 0.9808` in its own `meta.json`. On Eragon it detects
**5.6% of gold spans**. Not "a notch below state of the art": near-zero. It finds
nothing in `Eragon rode toward Carvahall with Saphira.` while finding every entity
in `Celaena Sardothien was escorted to Endovier.` — a book it was trained on.

The cause is in the training config and the dataset, not the architecture:

- `models/config_en.cfg` sets `vectors = null` and `include_static_vectors = false`.
  With no pretrained embeddings there is no way to learn that an unseen capitalised
  token in subject position behaves like a name.
- `ner_dataset/*.jsonl` contains **99 distinct PERSON surfaces** across 4 books.
  The 2481 PERSON spans are those 99 names repeated (Lucy x300, Edmund x220,
  Aslan x184).

99 strings and no vectors can only be memorised. The 0.98 is memorisation measured
on the memorised books.

This has been invisible because **only `throne-of-glass` declares
`spacy_model: models/wiki-ner-en/model-best`** — and throne-of-glass is in the
training set. The other 13 books use `en_core_web_lg`. The custom NER has only ever
run on the one book it knows by heart.

### 2. Fine-tuning a transformer on the existing dataset would not fix it

The ticket asks what a transformer fine-tune on `ner_dataset/` would cost. The
dataset is the bottleneck, not the architecture: 99 distinct names cannot teach
generalisation to any architecture. A fine-tune would buy a better-interpolating
lexicon.

Meanwhile GLiNER scores **0.891 typing F1 with zero training**. A fine-tune would
have to beat that to be worth a dataset-expansion campaign plus a permanent
retraining obligation on every ontology change. Recommend not pursuing it, and
closing that question rather than carrying it.

### 3. GLiNER wins both axes, and is the only arm that can do FACTION

| | detection F1 | typing F1 |
|---|---|---|
| tok2vec | 0.105 | 0.080 |
| spacy_stock | 0.870 | 0.206 |
| **gliner** | **0.901** | **0.891** |

The stock/GLiNER gap is the whole point. `en_core_web_lg`-class models **find**
entities (0.870) and then **mistype** them (0.206) — "Eragon" comes back as `ORG`,
"Carvahall" as `PERSON`. Since 13 of 14 books run stock spaCy today, that 0.206 is
the closest thing we have to the pipeline's current real typing quality.

FACTION is the sharpest case: **stock scores 0.000, by construction** — no stock
NER emits a FACTION label, and `base.yaml#entity_types` maps nothing onto it except
a literal `FACTION`. STU-505 made FACTION a first-order type; nothing in production
can currently populate it. GLiNER reaches 0.726 typing F1 on 222 gold spans just by
being asked for `people, race, or order`.

That generalises: with GLiNER, the type vocabulary becomes a prompt, not a training
run. Adding `ARTIFACT` or `SPELL` to `base.yaml` becomes an edit to
`gliner_labels.yaml` instead of a dataset campaign.

### Cost

17.5s for 120 chunks (182k chars) on the RTX 3060, versus 5.7s for tok2vec — about
3x slower, on a stage that is not the pipeline's bottleneck. Runs locally; no API
call, no data leaving the machine.

### What this spike does not settle

- **Label wording is load-bearing and only coarsely swept.** `faction` scores 0.509;
  `people, race, or order` scores 0.662 — 15 points from a rephrase. FACTION (0.726)
  and ORG (0.792) are the weakest typing rows and are the ones most likely to move
  with better labels. Sweep them properly against the real taxonomy before wiring.
- **EVENT is unmeasured** (n=2). Ship the GLiNER swap without an EVENT claim.
- **Gold is unadjudicated.** A human pass over a sample of the 1740 spans would put
  an error bar on every number here.
- **The 3-point detection gap (0.901 vs 0.870) is not the reason to switch** — the
  68-point typing gap is. If a cheaper path to correct types existed on top of stock
  spaCy, it would be worth pricing; the post-NER retagging layer
  (`_retag_entity_type_from_context`) is arguably already that attempt, and FACTION
  shows its ceiling.
