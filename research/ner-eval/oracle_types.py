#!/usr/bin/env python3
"""Type every arm's entities with an LLM oracle, then score the arms against it.

Research only — nothing here runs in the pipeline.

This is the STU-537 method (`research/relation-eval/retype_roster.py`) turned on
the NER arms themselves and generalised to any book: a book with no annotated
gold still has an oracle available, because typing a name a reader knows is a
question the LLM answers from the novel it has read.

Two rules keep the number honest.

**The rubric never names an entity under test.** It defines the types and stops.
Writing "Narnia is a PLACE" into the prompt would be scoring the arms against my
own verdict on the one entity in dispute — the eval would then be a formality
around a decision already made in its rubric. Types are defined by what they are;
the model applies them.

**The candidate set is the union of the arms**, so an entity only one arm found
counts as a miss against the other, not as a free pass. What no arm found is
invisible to this method — it measures the arms against each other, not against
the book. That is the price of not having a gold, and it is why detection claims
belong to STU-470's corpus and not here.

    python research/ner-eval/run_arms.py --book <book.yaml> --arm spacy
    python research/ner-eval/run_arms.py --book <book.yaml> --arm gliner_t0.3 --threshold 0.3
    python research/ner-eval/oracle_types.py --book <book.yaml>

Run from the repo root (see run_arms.py).
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "relation-eval"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from claude_cli import DEFAULT_MODEL, complete_json  # noqa: E402

from wiki_creator.entity_taxonomy import ner_types  # noqa: E402
from wiki_creator.paths import book_paths_from_yaml  # noqa: E402

TYPES = list(ner_types()) + ["OTHER"]
CONTEXT_CHARS = 220

RUBRIC = """- PERSON = an individual being who can hold a relationship: a human, a talking
  beast, a god, a monster. A designation used as the name of one individual
  counts; a named animal counts.
- FACTION = a people, race, order, or informal group.
- ORG = a formal body: a kingdom, an army, an institution.
- PLACE = a location: a world, a country, a city, a building, a landmark, a body
  of water.
- EVENT = a named or clearly-delimited happening.
- OTHER = anything else: an object, a title used generically, a bare common noun
  or plural the extractor mistook for a name, an adjective, a fragment of a name."""


def load_arms(out_dir: str) -> dict[str, dict]:
    arms = {}
    for path in sorted(glob.glob(os.path.join(out_dir, "entities_*.json"))):
        name = os.path.basename(path)[len("entities_"):-len(".json")]
        arms[name] = json.load(open(path, encoding="utf-8"))
    if not arms:
        sys.exit(f"no arms in {out_dir}/ — run run_arms.py first")
    return arms


def build_union(arms: dict[str, dict], min_mentions: int) -> dict[str, dict]:
    union: dict[str, dict] = {}
    for arm, entities in arms.items():
        for rec in entities.values():
            if rec["mention_count"] < min_mentions:
                continue
            name = rec["raw_mentions"][0]
            contexts = [s for sents in rec.get("mentions_by_chapter", {}).values() for s in sents]
            entry = union.setdefault(name, {
                "name": name,
                "context": contexts[0][:CONTEXT_CHARS] if contexts else "",
                "arms": {},
            })
            entry["arms"][arm] = {"type": rec["type"], "mentions": rec["mention_count"]}
    return union


def prompt_for(union: dict[str, dict], title: str, author: str) -> str:
    rows = "\n".join(
        f'{i} | {e["name"]!r} | context: {e["context"]!r}'
        for i, e in enumerate(union.values())
    )
    return f"""You are typing the entity candidates a NER pipeline extracted from the novel
"{title}" by {author}, to build the reference roster for a NER benchmark. Judge
each candidate on its name and its context line, from your knowledge of the novel.

Valid types: {", ".join(TYPES)}

{RUBRIC}

Rules:
- Judge what the candidate IS in the novel, not what a pipeline called it.
- A candidate that is not an entity at all — a stray capitalised word, a plural
  common noun, part of a longer name — is OTHER.
- Return one verdict for EVERY id listed. Do not skip any.

Candidates:

{rows}

Reply with ONLY a JSON object, no prose and no code fence:

{{"verdicts": [{{"id": 0, "type": "<one of: {", ".join(TYPES)}>"}}]}}
"""


def score(union: dict[str, dict], arms: dict[str, dict]) -> None:
    total = len(union)
    print(f"\n{'arm':16}{'typing':>10}", end="")
    for t in ("PERSON", "PLACE"):
        print(f"{t + ' prec':>13}{t + ' rec':>12}", end="")
    print()
    for arm in arms:
        found = [e for e in union.values() if arm in e["arms"]]
        ok = sum(1 for e in found if e["arms"][arm]["type"] == e["oracle"])
        print(f"{arm:16}{f'{ok}/{total}':>10}", end="")
        for t in ("PERSON", "PLACE"):
            tp = sum(1 for e in found if e["arms"][arm]["type"] == t and e["oracle"] == t)
            predicted = sum(1 for e in found if e["arms"][arm]["type"] == t)
            gold = sum(1 for e in union.values() if e["oracle"] == t)
            print(f"{f'{tp}/{predicted}':>13}{f'{tp}/{gold}':>12}", end="")
        print()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--arms-dir", default="research/ner-eval/arms")
    ap.add_argument("--min-mentions", type=int, default=3,
                    help="the book YAML's min_mentions_absolute — below it, no entity ships")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default="research/ner-eval/arms/oracle.json")
    args = ap.parse_args()

    paths = book_paths_from_yaml(args.book)
    epub = json.load(open(os.path.join(paths.processing, "epub_data.json"), encoding="utf-8"))
    arms = load_arms(args.arms_dir)
    union = build_union(arms, args.min_mentions)

    payload = complete_json(prompt_for(union, epub["title"], epub["author"]), model=args.model)
    verdicts = {int(v["id"]): v["type"] for v in payload.get("verdicts", [])}
    names = list(union)
    missing = [names[i] for i in range(len(names)) if i not in verdicts]
    if missing:
        sys.exit(f"the annotator skipped {len(missing)}: {missing[:10]}")
    unknown = {t for t in verdicts.values() if t not in TYPES}
    if unknown:
        sys.exit(f"the annotator invented types: {sorted(unknown)}")
    for i, name in enumerate(names):
        union[name]["oracle"] = verdicts[i]

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(list(union.values()), f, ensure_ascii=False, indent=1)
    print(f"{len(union)} candidates typed by {args.model} -> {args.out}")
    score(union, arms)


if __name__ == "__main__":
    main()
