#!/usr/bin/env python3
"""Stage: save-relationships

Lit le output de relationship-extraction depuis all_stage_outputs et l'écrit sur disk.
Permet aux scripts standalone (classify_relationships.py) de lire relationships.json.

Input (Studio stdin):
  all_stage_outputs["relationship-extraction"]: output du stage relationship-extraction

Output (stdout): même payload (pass-through)
Disk: processing_output/<slug>/relationships.json
"""
import json
import sys
from pathlib import Path


import yaml
from wiki_creator import studio_io
from wiki_creator.paths import book_paths_from_epub
from wiki_creator.types import Relationship, RelationshipBundle


def main() -> None:
    payload = json.load(sys.stdin)

    # Récupère le output de relationship-extraction
    # Studio expose les outputs précédents sous "previous_outputs" (dict stage_name → output)
    previous_outputs = payload.get("previous_outputs", payload.get("all_stage_outputs", {}))
    rel_output = previous_outputs.get("relationship-extraction", {})

    # Détermine le chemin du book depuis additional_context
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path", "")
    if not file_path:
        json.dump({"error": "missing file_path in additional_context"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    paths = book_paths_from_epub(file_path)
    paths.processing.mkdir(parents=True, exist_ok=True)
    output_path = paths.processing / "relationships.json"

    bundle = RelationshipBundle(
        entities=rel_output.get("entities", []),
        relationships=[Relationship(**r) for r in rel_output.get("relationships", [])],
        stats=rel_output.get("stats", {}),
        narrator=rel_output.get("narrator"),
    )
    studio_io.save_artifact(output_path, bundle, RelationshipBundle)

    print(f"[save-relationships] Written to {output_path}", file=sys.stderr)

    # Pass-through: re-émet le même payload pour les stages suivants
    json.dump(rel_output, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
