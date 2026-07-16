#!/usr/bin/env python3
"""Freeze the bake-off's two inputs: the narrative chapters, and the entity roster.

The roster is taken from the pipeline's own relationship-extraction bundle —
PERSON + `relevant`, exactly the filter `build_cooccurrence_graph` applies. It is
handed unchanged to every arm, so the bake-off varies relation discovery and
nothing else. Swapping in a cleaner roster would measure a fix that is not
shipped, and would let a stronger NER take credit for a relation win.

It is dirty on purpose, and the dirt is data: split-clusters types entities
before entity-classification and the book's `entity_overrides` run, so Varden and
Empire (ORG) and Tronjheim and Farthen Dur (PLACE) sit in the PERSON roster. Every
arm sees the same dirt. Whether an arm can decline to relate Eragon to a valley is
part of what is being measured.

Usage:
    python build_corpus.py \\
        --processing-output ../../library/christopher_paolini/inheritance/processing_output/01_eragon \\
        --first-chapter id_7 --last-chapter id_66
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def narrative_chapters(order: list[dict], texts: dict[str, str], first: str, last: str) -> list[dict]:
    """Chapters between first and last inclusive, in book order.

    Text comes from chapters.json, not epub_data.json: that is the text
    entity-extraction ran on, so an arm and the baseline read the same bytes.
    Order and titles come from epub_data.json, which is the only artifact that
    keeps them (chapters.json is a flat id -> content map).

    Cut by id range, not by length or the section-filter tags: front/back matter
    carries real entities that are not this book's fiction (the Eldest preview
    names characters Eragon never meets), and a relation gold built over it would
    charge every arm for relations the book does not contain.
    """
    ids = [c["id"] for c in order]
    try:
        lo, hi = ids.index(first), ids.index(last)
    except ValueError as e:
        sys.exit(f"chapter id not found in epub_data: {e}")
    if lo > hi:
        sys.exit(f"--first-chapter {first} comes after --last-chapter {last}")

    kept = []
    for c in order[lo:hi + 1]:
        if c["id"] not in texts:
            sys.exit(f"{c['id']} is in epub_data but not chapters.json")
        kept.append({"id": c["id"], "title": c["title"], "text": texts[c["id"]]})
    return kept


def build_roster(bundle_entities: list[dict], classified: dict | None) -> list[dict]:
    """PERSON + relevant, with the post-classification type attached as metadata.

    `type` is what discovery actually filters on. `refined_type` is what the same
    entity is called once entity-classification and entity_overrides have run —
    carried so the report can say how much of the roster is mistyped, without
    letting that knowledge leak into any arm.
    """
    refined = {
        rec["canonical_name"]: rec.get("type")
        for rec in (classified or {}).get("entities", [])
        if rec.get("canonical_name")
    }

    return [
        {
            "canonical_name": e["canonical_name"],
            "aliases": sorted(set(e.get("aliases") or []) | {e["canonical_name"]}),
            "type": e.get("type"),
            "refined_type": refined.get(e["canonical_name"]),
        }
        for e in bundle_entities
        if e.get("type") == "PERSON" and e.get("relevant", True)
    ]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--processing-output", required=True)
    ap.add_argument("--first-chapter", required=True)
    ap.add_argument("--last-chapter", required=True)
    ap.add_argument("--corpus-out", default="corpus.jsonl")
    ap.add_argument("--roster-out", default="roster.json")
    args = ap.parse_args()

    root = args.processing_output
    with open(os.path.join(root, "chapters.json"), encoding="utf-8") as f:
        texts = json.load(f)["chapters"]
    with open(os.path.join(root, "epub_data.json"), encoding="utf-8") as f:
        order = json.load(f)["chapters"]
    with open(os.path.join(root, "relationships.json"), encoding="utf-8") as f:
        bundle = json.load(f)

    classified_path = os.path.join(root, "entities_classified.json")
    classified = None
    if os.path.exists(classified_path):
        with open(classified_path, encoding="utf-8") as f:
            classified = json.load(f)

    kept = narrative_chapters(order, texts, args.first_chapter, args.last_chapter)
    roster = build_roster(bundle["entities"], classified)

    with open(args.corpus_out, "w", encoding="utf-8") as f:
        for c in kept:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(args.roster_out, "w", encoding="utf-8") as f:
        json.dump(roster, f, ensure_ascii=False, indent=2)

    chars = sum(len(c["text"]) for c in kept)
    mistyped = [r for r in roster if r["refined_type"] not in (None, "PERSON")]
    print(f"{len(kept)} narrative chapters, {chars} chars -> {args.corpus_out}")
    print(f"{len(roster)} PERSON+relevant entities -> {args.roster_out}")
    print(f"  mistyped (refined_type != PERSON): {len(mistyped)} "
          f"{[(r['canonical_name'], r['refined_type']) for r in mistyped][:8]}")


if __name__ == "__main__":
    main()
