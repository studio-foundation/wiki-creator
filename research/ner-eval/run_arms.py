#!/usr/bin/env python3
"""Extract a book's entities once per NER arm, through the shipped extractor.

Research only — nothing here runs in the pipeline.

Why not `runners/run_spacy.py` + `runners/run_gliner.py`: those score raw model
spans against the STU-470 gold, which needs an annotated corpus a book only has
if someone paid for one. This asks the cheaper question a book config actually
faces — *which arm should this book declare?* — over the pipeline's own output:
same `extract_entities`, same POS filter, same cue words, same
`retag_from_context` rule as production. What it measures is therefore the
deployed entity list, not the model.

    B=library/c_w_lewis/narnia/books/01-the_lion_the_witch_and_the_wardrobe.yaml
    python research/ner-eval/run_arms.py --book $B --arm spacy
    python research/ner-eval/run_arms.py --book $B --arm gliner_t0.3 --threshold 0.3

Run from the repo root: `paths.py` resolves a book path against the project root,
not the cwd, unlike this directory's STU-470 scripts.

Needs the book already parsed (`epub_data.json` in its processing_output) and the
`[models]` + `[gliner]` extras.
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import spacy  # noqa: E402
import yaml  # noqa: E402

from scripts.entity_extraction import _ensure_sentencizer, _load_cue_words, extract_entities  # noqa: E402
from wiki_creator.entity_taxonomy import gliner_label_map  # noqa: E402
from wiki_creator.lang import book_language  # noqa: E402
from wiki_creator.paths import book_paths_from_yaml  # noqa: E402


def load_chapters(book: str) -> tuple[list[dict], dict]:
    config = yaml.safe_load(open(book, encoding="utf-8"))
    paths = book_paths_from_yaml(book)
    epub = json.load(open(os.path.join(paths.processing, "epub_data.json"), encoding="utf-8"))
    chapters = [c for c in epub["chapters"] if not c.get("frontmatter")]
    return chapters, config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--arm", required=True, help="spacy | gliner")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--model", default="urchade/gliner_large-v2.1")
    ap.add_argument("--out-dir", default="research/ner-eval/arms")
    args = ap.parse_args()

    chapters, config = load_chapters(args.book)
    invented = args.arm != "spacy"

    nlp = spacy.load(config["spacy_model"])
    _ensure_sentencizer(nlp)
    if invented:
        from wiki_creator.nlp.gliner_ner import attach

        attach(nlp, gliner_label_map(), model=args.model, threshold=args.threshold)

    # retag_from_context mirrors the production rule (STU-537): the repair exists
    # for spaCy's typing and only misfires on a prompt-typed model.
    result = extract_entities(
        chapters,
        nlp,
        cue_words=_load_cue_words(book_language(config)),
        retag_from_context=not invented,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"entities_{args.arm}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(result["entities"], f, ensure_ascii=False, indent=1)

    counts = Counter(e["type"] for e in result["entities"].values())
    print(f"{len(chapters)} chapters -> {len(result['entities'])} entities -> {out}")
    print(f"  {dict(counts)}")


if __name__ == "__main__":
    main()
