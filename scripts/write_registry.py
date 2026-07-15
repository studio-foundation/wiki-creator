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
from wiki_creator import studio_io
from wiki_creator.canon import load_canon
from wiki_creator.naming import naming_policy
from wiki_creator.paths import book_paths_from_epub
from wiki_creator.registry import Registry
from wiki_creator.types import ClassifiedBundle, Splits

FULL_REGISTRY_FILES = (
    "persons_full.json",
    "places_full.json",
    "orgs_full.json",
    "events_full.json",
)


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
        classified_path = paths.processing / "entities_classified.json"
        if classified_path.exists():
            try:
                # Registry.from_artifacts consumes raw record dicts (Do NOT change
                # registry.py); to_dict here is a pure shape adapter after validation.
                alias_output = studio_io.to_dict(
                    studio_io.load_artifact(classified_path, ClassifiedBundle)
                )
            except json.JSONDecodeError:
                alias_output = {}

    splits_path = paths.processing / "splits.json"
    splits = studio_io.load_artifact(splits_path, Splits) if splits_path.exists() else Splits()
    # load_full_file unwraps each per-type file's json_key ("persons_full", …)
    # and validates against EntityFull, falling back to the raw payload for
    # unwrapped fixtures/older runs — else no source_id ever matches and every
    # registry mention is silently dropped.
    full_registries: dict = {}
    for name in FULL_REGISTRY_FILES:
        path = paths.processing / name
        if path.exists():
            full_registries.update(studio_io.load_full_file(path, name.removesuffix(".json")))

    # Registry.from_artifacts consumes raw record dicts; splits/full_registries
    # are already validated (load_artifact/load_full_file above), so to_dict
    # here is a pure shape adapter.
    registry = Registry.from_artifacts(
        studio_io.to_dict(splits), alias_output, studio_io.to_dict(full_registries),
        book_id, policy=naming_policy(ctx),
    )
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

    Cross-tome conflicts are arbitrated by the series canon policy (STU-512);
    a series with no canon.yaml keeps the historical rule (earlier tome wins).
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

    canon = load_canon(paths.series_canon)
    delta = series.accumulate(
        registry,
        later_tome_overrides=bool(canon and canon.later_tome_overrides),
    )

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
