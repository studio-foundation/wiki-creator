# NER bake-off (STU-470)

Scores `wiki-ner-en` against alternatives on a book it was **not** trained on.
Research only — nothing here runs in the pipeline.

Verdict and numbers: [results.md](results.md).

## Why Eragon

`wiki-ner-en` is trained on `ner_dataset/*.jsonl` (narnia, hobbit, way-of-kings,
throne-of-glass). Scoring it on `models/dev.spacy` — a 20% split of that same
Haiku-annotated data — measures memorisation, and its own `meta.json` says 0.98.
Eragon appears in no split, so it is the only arm that answers the ticket's
question. It also has real ORG/FACTION density, which the training set lacks.

## Two axes, on purpose

- **detection** — span found, label ignored. Convention-free, so a zero-shot model
  is not penalised for cutting spans differently than the gold's annotator.
- **typing** — span found AND labelled correctly. Conventions matter here, which
  favours anything trained on the gold's annotator.

Reporting one number would hide the finding: stock spaCy detects at 0.87 and types
at 0.21.

## Setup

    pip install -r requirements.txt
    python -m spacy download en_core_web_sm

`models/`, `ner_dataset/`, the EPUBs, and `.studio/config.yaml` are all gitignored.
In a fresh worktree, symlink them from the main checkout and add them to
`.git/worktrees/<name>/info/exclude`.

## Run

    # 1. Parse the EPUB (writes processing_output/01_eragon/epub_data.json)
    python -c "import json,pathlib; y=pathlib.Path('../../library/christopher_paolini/inheritance/books/01_eragon.yaml').read_text(); print(json.dumps({'additional_context':y,'previous_outputs':{},'all_stage_outputs':{}}))" \
      | python ../../scripts/parse_epub.py > /dev/null

    # 2. Corpus — id_7..id_66 is Eragon's narrative span; the rest is front/back matter
    python build_corpus.py \
      --epub-data ../../library/christopher_paolini/inheritance/processing_output/01_eragon/epub_data.json \
      --first-chapter id_7 --last-chapter id_66 --chunks 120 --seed 42

    # 3. Gold (needs an API key; ~$3 of claude-opus-4-8)
    python build_gold.py

    # 4. Arms
    python runners/run_spacy.py --model ../../models/wiki-ner-en/model-best --name tok2vec
    python runners/run_spacy.py --model en_core_web_sm --name spacy_stock
    python runners/run_gliner.py            # sweeps labels, then runs the winners

    # 5. Report (recommendation.md is inlined; results.md is generated)
    python report.py

## Label selection (STU-521)

`results.md` answers which *arm* wins. Once GLiNER won, the question became which
*labels* to ship, and `runners/run_gliner.py`'s sweep does not answer that: it
asks each candidate alone and ranks it on detection recall, while deployment asks
every label at once, where they compete for the same spans.

`sweep_labels.py` scores each candidate in a full run with the other types'
current labels present, on typing F1, by coordinate ascent from STU-470's
selection:

    python sweep_labels.py          # ~8 min on an RTX 3060, needs corpus + gold

It moved every row (macro 0.840 -> 0.866, micro 0.891 -> 0.903):

| type | STU-470 | joint sweep | selected label |
|---|---|---|---|
| PERSON | 0.938 | 0.942 | `person name` |
| PLACE | 0.809 | 0.849 | `place name` |
| ORG | 0.792 | 0.920 | `kingdom, empire, or government` |
| FACTION | 0.726 | 0.753 | `people, race, or order` |

Read ORG's +13 with care: n=26 gold spans, the noisiest row in the table.
FACTION — the row that motivated the switch — held its STU-470 label against six
candidates.

The winners live in `base.yaml#entity_types.<TYPE>.gliner_label`, not here;
`gliner_labels.yaml` is only the candidate list. Same caveat as STU-470: labels
are selected on the gold they are scored against, so these are mildly optimistic.

## Per-book arm choice, without a gold (STU-535)

Everything above answers *which arm is better on Eragon*, against a gold that cost
~$3 and a day to build. `ner.invented_names` is declared **per book**, and no other
book has a gold — which is how Narnia ran spaCy while the world itself was typed
PERSON on all 40 mentions of it.

`run_arms.py` + `oracle_types.py` answer the cheaper question a book config
actually faces, on any book, for one LLM call:

    B=library/c_w_lewis/narnia/books/01-the_lion_the_witch_and_the_wardrobe.yaml
    python research/ner-eval/run_arms.py --book $B --arm spacy
    python research/ner-eval/run_arms.py --book $B --arm gliner_t0.5 --threshold 0.5
    python research/ner-eval/run_arms.py --book $B --arm gliner_t0.3 --threshold 0.3
    python research/ner-eval/oracle_types.py --book $B

(from the repo root — `paths.py` resolves a book path against the project root, not
the cwd, unlike this directory's STU-470 scripts. Needs the book already parsed.)

It is a different measurement, not a cheaper version of the one above:

|  | STU-470 corpus | this |
|---|---|---|
| unit | a span in the text | an entity in the pipeline's output |
| reference | annotated gold, ~$3/book | LLM verdict per candidate, one call |
| answers | which model finds and types spans best | which arm should this book declare |
| blind to | nothing in the sampled chunks | anything **no** arm found |

Narnia, 51 candidates at the book's `min_mentions_absolute`:

| arm | typing | PERSON prec / rec | PLACE prec / rec |
|---|---|---|---|
| spaCy `en_core_web_lg` | 22/51 | 22/30 · 22/31 | **0/1 · 0/3** |
| GLiNER, threshold 0.5 | 26/51 | 21/24 · 21/31 | 3/3 · 3/3 |
| GLiNER, threshold 0.3 | **32/51** | 24/28 · 24/31 | 3/5 · 3/3 |

Three things this method gets wrong if you let it:

- **A rubric that names an entity under test is not a measurement.** The first draft
  of the prompt said "Narnia is a PLACE" — scoring the arms against the author's
  verdict on the one entity in dispute. The shipped rubric defines the types and
  stops; the verdict held without the hint.
- **The union of arms is not the book.** An entity every arm missed is invisible
  here. Detection claims belong to the gold corpus above.
- **GLiNER's borderline spans are not deterministic.** Counts move by ±1 entity
  between identical runs; do not read a one-entity difference as a result.

### The public_domain flip (STU-616)

The same `run_arms` + `oracle_types` method, batched over the distributable
`public_domain/` invented-world books (Alice, The Call of Cthulhu, Oz ×6, The
Odyssey). All nine flipped to `invented_names: true` at threshold 0.3; the
real-world casts (Dracula, the Verne pair, Notre-Dame) stayed on spaCy. Numbers,
per-book PERSON/PLACE breakdown, and the reproduce command: [results_stu616.md](results_stu616.md)
(driver: `batch_all.sh`).

## Tests

    pytest tests/ -q

Covers the scorer, corpus sampling, and surface->offset expansion — everything
except the API and model calls.
