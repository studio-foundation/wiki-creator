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

## Tests

    pytest tests/ -q

Covers the scorer, corpus sampling, and surface->offset expansion — everything
except the API and model calls.
