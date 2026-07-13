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

Depuis STU-485 le stage accumule aussi le registre du tome dans le registre
série (library/<author>/<series>/registry.json, pendant de character_graph.json)
et écrit le delta d'accumulation par tome (registry_delta.json, pendant de
character_graph_delta.json). Un registre série illisible est laissé intact
(l'accumulation est sautée avec un warning) plutôt qu'écrasé.

Output (stdout): {"registry": {"path", "entities", "decisions", "warnings"},
                  "series_registry": {"path", "entities", "matched", "added",
                                      "decisions_added", "warnings"} | None}
Disk: processing_output/<slug>/registry.json
      processing_output/<slug>/registry_delta.json
      library/<author>/<series>/registry.json
"""
import json
import sys
from pathlib import Path


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
    # Extraction wraps each per-type file under its json_key ("persons_full",
    # …); unwrap it like relationship_extraction does, else no source_id ever
    # matches and every registry mention is silently dropped. Unwrapped files
    # (unit fixtures, older runs) keep working.
    full_registries: dict = {}
    for name in FULL_REGISTRY_FILES:
        data = _load_json(paths.processing / name)
        inner = data.get(name.removesuffix(".json"))
        full_registries.update(inner if isinstance(inner, dict) else data)

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

    series_summary = _accumulate_into_series(paths, registry)

    json.dump(
        {
            "registry": {
                "path": str(output_path),
                "entities": len(registry.entities),
                "decisions": len(registry.decisions),
                "warnings": registry.warnings,
            },
            "series_registry": series_summary,
        },
        sys.stdout,
        ensure_ascii=False,
    )


def _accumulate_into_series(paths, registry: Registry) -> dict | None:
    """Accumulate this tome's registry into the series registry (STU-485).

    Loads library/<author>/<series>/registry.json (starting empty when absent),
    folds the book registry in, writes the series registry atomically
    (write-to-temp + rename, same as the series character graph) and the
    per-book accumulation delta. An existing-but-unreadable series registry is
    left untouched: accumulation is skipped with a warning instead of clobbering
    tomes already accumulated.
    """
    series_path = paths.series_registry
    if series_path.exists():
        try:
            series = Registry.load(series_path)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            print(
                f"[write-registry] warning: series registry {series_path} unreadable "
                f"({e}) — accumulation skipped",
                file=sys.stderr,
            )
            return None
    else:
        series = Registry()

    delta = series.accumulate(registry)

    tmp = series_path.with_suffix(".json.tmp")
    try:
        series.save(tmp)
        tmp.rename(series_path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise

    delta_path = paths.book_registry_delta
    delta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(delta_path, "w", encoding="utf-8") as f:
        json.dump(delta, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(
        f"[write-registry] Series registry {series_path}: "
        f"{len(series.entities)} entities ({len(delta['matched'])} matched, "
        f"{len(delta['added'])} added, {len(delta['decisions_added'])} decisions)",
        file=sys.stderr,
    )
    for warning in delta["warnings"]:
        print(f"[write-registry] series warning: {warning}", file=sys.stderr)

    return {
        "path": str(series_path),
        "delta_path": str(delta_path),
        "entities": len(series.entities),
        "matched": len(delta["matched"]),
        "added": len(delta["added"]),
        "decisions_added": len(delta["decisions_added"]),
        "warnings": delta["warnings"],
    }


if __name__ == "__main__":
    main()
