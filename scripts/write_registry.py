#!/usr/bin/env python3
"""Stage: write-registry (STU-441, EntityRegistry pas 1)

Reconstruit le registre d'identité depuis les artefacts existants et écrit
processing_output/<slug>/registry.json. Lecture seule : aucun changement de
comportement du pipeline — rien ne consomme le registre avant STU-435 (pas 3).

Input (Studio stdin):
  all_stage_outputs["entity-classification"]: output du stage entity-classification
  (fallback : entities_classified.json sur disque, le même stage matérialisé — pour
  les runs repris). Les deux portent le même jeu d'entités (alias + provenance de
  fusion identiques), avec les entity_type raffinés par la classification : la source
  est donc la même que le run soit live ou repris.

Output (stdout): {"registry": {"path", "entities", "decisions", "warnings"}}
Disk: processing_output/<slug>/registry.json
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import yaml
from wiki_creator.paths import book_paths_from_epub
from wiki_creator.registry import Registry

FULL_REGISTRY_FILES = (
    "persons_full.json",
    "places_full.json",
    "orgs_full.json",
    "events_full.json",
)


def _load_json(path: Path) -> dict:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    return {}


def main() -> None:
    payload = json.load(sys.stdin)
    previous_outputs = payload.get("previous_outputs", payload.get("all_stage_outputs", {}))

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path", "")
    if not file_path:
        json.dump({"error": "missing file_path in additional_context"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    paths = book_paths_from_epub(file_path)
    # Provenance stamp (STU-484): the book slug derived by book_paths_from_epub
    # (== processing dir name). Every mention/record in this book's registry
    # carries it, aligning identity provenance with the series graph's `books`.
    book_id = paths.processing.name

    # Read the classified entity set so the registry is identical whether the run
    # is live (stage output in memory) or resumed (entities_classified.json on
    # disk — the same entity-classification stage materialised). Both carry the
    # alias_resolution merge-evidence block, so audit provenance is preserved.
    alias_output = previous_outputs.get("entity-classification") or {}
    if not alias_output.get("entities"):
        alias_output = _load_json(paths.processing / "entities_classified.json")

    splits = _load_json(paths.processing / "splits.json")
    full_registries: dict = {}
    for name in FULL_REGISTRY_FILES:
        full_registries.update(_load_json(paths.processing / name))

    registry = Registry.from_artifacts(splits, alias_output, full_registries, book_id)
    output_path = paths.processing / "registry.json"
    registry.save(output_path)

    print(
        f"[write-registry] Written {len(registry.entities)} entities, "
        f"{len(registry.decisions)} decisions to {output_path}",
        file=sys.stderr,
    )
    for warning in registry.warnings:
        print(f"[write-registry] warning: {warning}", file=sys.stderr)

    json.dump(
        {
            "registry": {
                "path": str(output_path),
                "entities": len(registry.entities),
                "decisions": len(registry.decisions),
                "warnings": registry.warnings,
            }
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
