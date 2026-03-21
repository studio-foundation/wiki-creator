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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from wiki_creator.paths import book_paths_from_epub


def main() -> None:
    payload = json.load(sys.stdin)

    # Récupère le output de relationship-extraction
    all_stage_outputs = payload.get("all_stage_outputs", {})
    rel_output = all_stage_outputs.get("relationship-extraction", {})

    # Détermine le chemin du book depuis additional_context
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path", "")
    if not file_path:
        json.dump({"error": "missing file_path in additional_context"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    paths = book_paths_from_epub(file_path)
    paths.processing.mkdir(parents=True, exist_ok=True)
    output_path = paths.processing / "relationships.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(rel_output, f, ensure_ascii=False, indent=2)

    print(f"[save-relationships] Written to {output_path}", file=sys.stderr)

    # Pass-through: re-émet le même payload pour les stages suivants
    json.dump(rel_output, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
