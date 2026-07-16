#!/usr/bin/env python3
"""Re-type every extracted entity to build the oracle roster.

This is an ORACLE, not a proposed fix. It exists because the benchmark cannot ask
its question without one, and it never runs in the pipeline.

Why it is needed. Relation discovery filters `type == "PERSON"` over the split-
clusters typing, and that typing puts Garrow (112 mentions, the uncle who raises
Eragon) and Durza (35, the book's antagonist) in ORG, and Katrina in EVENT. Gold
annotated against that roster would be forbidden from ever naming Eragon/Garrow —
the ticket's own example of the implicit relation co-occurrence cannot see. Every
arm would then score identically blind, and the benchmark would report that the
mechanism does not matter, because it had rigged the roster so it could not.

So the gold is annotated against the oracle roster, every arm is handed the oracle
roster, and the shipped pipeline's own roster is kept as a separate arm. The
deficit between them is the price of the entity layer, reported next to — not
mixed into — the relation-discovery numbers.

Two entity buckets are deliberately not reconciled: an animal with a name
(Snowfire, Cadoc — horses; Saphira — a dragon who speaks) is a judgment call the
prompt makes explicit rather than leaving to the model's taste, because Saphira
carries the book's central relationship and dropping her would be worse than
keeping two horses.

Usage:
    python retype_roster.py \\
        --processing-output ../../library/christopher_paolini/inheritance/processing_output/01_eragon
"""
import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from claude_cli import DEFAULT_MODEL, complete_json  # noqa: E402
from wiki_creator.entity_taxonomy import ner_types  # noqa: E402

TYPES = list(ner_types()) + ["OTHER"]
_CONTEXT_CHARS = 220


def load_entities(root: str) -> list[dict]:
    out = []
    for path in sorted(glob.glob(os.path.join(root, "*_full.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        bucket = next(iter(data))
        for eid, rec in data[bucket].items():
            contexts = [s for sents in rec.get("mentions_by_chapter", {}).values() for s in sents]
            out.append({
                "id": eid,
                "names": rec.get("raw_mentions", []),
                "shipped_type": rec.get("type"),
                "mentions": rec.get("mention_count", 0),
                "context": (contexts[0][:_CONTEXT_CHARS] if contexts else ""),
            })
    return sorted(out, key=lambda e: -e["mentions"])


def prompt_for(entities: list[dict]) -> str:
    rows = "\n".join(
        f'{e["id"]} | names={e["names"]} | {e["mentions"]} mentions | context: {e["context"]!r}'
        for e in entities
    )
    return f"""You are re-typing the entities a NER pipeline extracted from the novel "Eragon"
(Christopher Paolini, book 1 of the Inheritance Cycle), to build the reference
roster for a relation-extraction benchmark. The pipeline's own types are wrong
often enough that they are shown only as a hint you should feel free to overrule.

Valid types: {", ".join(TYPES)}

Rules:
- PERSON = an individual being with a name who can hold a relationship: humans,
  elves, dwarves, dragons, Shades, werecats. Saphira is a PERSON. A named animal
  a character rides or keeps (a horse) is a PERSON too — it is an individual, and
  drawing the line at "speaks" would be arbitrary in a book where dragons do.
- FACTION = a people, race, order, or informal group (the Varden, Urgals, Ra'zac,
  the Forsworn).
- ORG = a formal body: a kingdom, an army, an institution (the Empire).
- PLACE = a location: a city, valley, mountain, forest, lake, river.
- EVENT = a named or clearly-delimited happening (the Battle of Farthen Dur).
- OTHER = anything that fits none of the above: an object, a sword, a gem, a
  spell, a word of the ancient language, a title, or a common noun the extractor
  mistook for a name.
- Judge by the names and the context line, not by the pipeline's type.
- Return one verdict for EVERY id listed. Do not skip any.

Entities:

{rows}

Reply with ONLY a JSON object, no prose and no code fence:

{{"verdicts": [{{"id": "entity_001", "type": "<one of: {", ".join(TYPES)}>", "canonical_name": "<the best display name among its names>"}}]}}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--processing-output", required=True)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", default="roster_oracle.json")
    ap.add_argument("--verdicts-out", default="retype_verdicts.json")
    args = ap.parse_args()

    entities = load_entities(args.processing_output)
    by_id = {e["id"]: e for e in entities}

    payload = complete_json(prompt_for(entities), model=args.model)
    verdicts = {v["id"]: v for v in payload.get("verdicts", []) if v.get("id") in by_id}

    missing = [eid for eid in by_id if eid not in verdicts]
    if missing:
        sys.exit(f"the annotator skipped {len(missing)} entities: {missing[:10]}")

    with open(args.verdicts_out, "w", encoding="utf-8") as f:
        json.dump([{**by_id[i], **v} for i, v in verdicts.items()], f, ensure_ascii=False, indent=2)

    roster = [
        {
            "canonical_name": verdicts[e["id"]].get("canonical_name") or e["names"][0],
            "aliases": sorted(set(e["names"])),
            "source_ids": [e["id"]],
            "type": "PERSON",
            "shipped_type": e["shipped_type"],
            "mentions": e["mentions"],
        }
        for e in entities
        if verdicts[e["id"]]["type"] == "PERSON"
    ]
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(roster, f, ensure_ascii=False, indent=2)

    moved_in = [r for r in roster if r["shipped_type"] != "PERSON"]
    moved_out = [e for e in entities
                 if e["shipped_type"] == "PERSON" and verdicts[e["id"]]["type"] != "PERSON"]
    print(f"{len(entities)} extracted entities -> {len(roster)} PERSON (oracle) -> {args.out}")
    print(f"  shipped said PERSON, oracle disagrees: {len(moved_out)}")
    for e in moved_out[:12]:
        print(f"    {str(e['names'][:2]):32} {e['mentions']:4} mentions -> {verdicts[e['id']]['type']}")
    print(f"  shipped missed, oracle says PERSON: {len(moved_in)}")
    for r in sorted(moved_in, key=lambda r: -r["mentions"])[:12]:
        print(f"    {r['canonical_name']:24} {r['mentions']:4} mentions (was {r['shipped_type']})")


if __name__ == "__main__":
    main()
