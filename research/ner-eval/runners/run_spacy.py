#!/usr/bin/env python3
"""spaCy runner — serves both arms, they differ only by model path.

    python runners/run_spacy.py --model models/wiki-ner-en/model-best --name tok2vec
    python runners/run_spacy.py --model en_core_web_sm --name spacy_stock

`spacy_stock` is the control arm: it shows what a generic press-trained pipeline
gives on fiction, i.e. what the custom model bought in the first place.
"""
import argparse
import os
import sys
import time

import spacy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from corpus_io import read_corpus, write_predictions  # noqa: E402
from mapping import map_spacy  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--name", required=True, help="arm name; writes predictions.<name>.jsonl")
    ap.add_argument("--corpus", default="corpus.jsonl")
    args = ap.parse_args()

    nlp = spacy.load(args.model)
    print(f"{args.name}: {args.model} | pipeline={nlp.pipe_names} | "
          f"ner labels={sorted(nlp.get_pipe('ner').labels)}")

    corpus = read_corpus(args.corpus)
    started = time.perf_counter()
    records = [
        {"id": case["id"], "spans": map_spacy(doc.ents)}
        for case, doc in zip(corpus, nlp.pipe([c["text"] for c in corpus]))
    ]
    elapsed = time.perf_counter() - started

    write_predictions(f"predictions.{args.name}.jsonl", records)
    print(f"{args.name}: {elapsed:.1f}s for {len(corpus)} chunks")


if __name__ == "__main__":
    main()
