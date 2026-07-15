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

## Tests

    pytest tests/ -q

Covers the scorer, corpus sampling, and surface->offset expansion — everything
except the API and model calls.
