#!/usr/bin/env python3
"""STU-635: PERSON-recall before/after `ner.character_names`, through the shipped
extractor. Research only.

Runs the exact production NER path (GLiNER at the book's threshold + the STU-630
gazetteer) over the parsed chapters and reports the PERSON roster. `--extra-names`
appends candidate gazetteer entries on top of whatever the book YAML already
declares, so one run measures "after" against a baseline run with none.

    python research/ner-eval/gazetteer_measure.py --book <yaml>                # before (yaml as-is)
    python research/ner-eval/gazetteer_measure.py --book <yaml> --extra-names "Scarecrow,Tin Woodman"

Needs the book parsed (epub_data.json) + the [models]/[gliner] extras.
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
from wiki_creator.ner import ner_config  # noqa: E402
from wiki_creator.nlp.gazetteer import attach as attach_gazetteer  # noqa: E402
from wiki_creator.nlp.gliner_ner import attach as attach_gliner  # noqa: E402
from wiki_creator.paths import book_paths_from_yaml  # noqa: E402


def load_chapters(book: str):
    config = yaml.safe_load(open(book, encoding="utf-8"))
    paths = book_paths_from_yaml(book)
    epub = json.load(open(os.path.join(paths.processing, "epub_data.json"), encoding="utf-8"))
    chapters = [c for c in epub["chapters"] if not c.get("frontmatter")]
    return chapters, config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--extra-names", default="", help="comma-separated candidate gazetteer names")
    args = ap.parse_args()

    chapters, config = load_chapters(args.book)
    ner = ner_config(config)
    extra = [n.strip() for n in args.extra_names.split(",") if n.strip()]
    names = list(ner.character_names) + extra

    nlp = spacy.load(config["spacy_model"])
    _ensure_sentencizer(nlp)
    attach_gliner(nlp, gliner_label_map(), model=ner.model, threshold=ner.threshold)
    attach_gazetteer(nlp, names)

    result = extract_entities(
        chapters,
        nlp,
        cue_words=_load_cue_words(book_language(config)),
        retag_from_context=False,  # invented_names path
    )
    entities = result["entities"]

    persons = [
        (e.get("mention_count", 0), sorted(set(e["raw_mentions"]))[0], e["raw_mentions"])
        for e in entities.values()
        if e["type"] == "PERSON"
    ]
    persons.sort(reverse=True)
    counts = Counter(e["type"] for e in entities.values())
    print(f"{len(chapters)} chapters -> {len(entities)} entities  {dict(counts)}")
    print(f"gazetteer names ({len(names)}): {names}")
    print(f"PERSON roster ({len(persons)}):")
    for cnt, first, raw in persons:
        forms = ", ".join(sorted(set(raw)))
        print(f"  {cnt:5d}  {forms}")


if __name__ == "__main__":
    main()
