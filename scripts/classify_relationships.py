#!/usr/bin/env python3
"""Standalone relationship classifier: one `studio run classify-relationships` per book.

Usage:
    python scripts/classify_relationships.py --book library/.../book.yaml
    python scripts/classify_relationships.py --book library/.../book.yaml --dry-run

Input:  processing_output/<slug>/relationships.json
Output: processing_output/<slug>/relationships_classified.json

The engine fans out one child run per pair (`map` stage, STU-589) with
`resume: true` (STU-605): a completed pair replays free on a re-run, a failed
pair is never cached and retries, and the resume key carries the classifier
prompt fingerprint so a prompt or vocabulary edit re-classifies every pair
(STU-560). RALPH retries and the classification-validation group live in the
child pipeline — the subprocess-level retry layer this script used to need
(`_CLASSIFIER_MAX_ATTEMPTS`) is gone from the production path.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


from wiki_creator import studio_io
from wiki_creator.page_templates import confidence_definitions, relationship_definitions
from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.registry import Registry
from wiki_creator.relationship_fold import fold_relationships
from wiki_creator.types import Relationship, RelationshipBundle
from scripts.relationship_extraction import (
    classifier_item_input,
    _should_classify_pair,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_AGENTS_DIR = PROJECT_ROOT / ".studio" / "agents"


def _classifier_fingerprint(*, book_config: dict, novel_summary: str, pre_typed: bool) -> str:
    """Fingerprint the config every verdict in the artifact was produced under.

    The resume state is the output artifact itself, keyed per pair — so before
    STU-589 an edited classifier prompt or a changed type/confidence vocabulary
    replayed the stale verdicts silently. This busts the whole resume when any of
    them moves (the pair evidence is the per-item input and already re-keys itself).
    """
    return studio_io.prompt_fingerprint(
        agents=[
            _AGENTS_DIR / "relationship-classifier.agent.yaml",
            _AGENTS_DIR / "relationship-classifier-validator.agent.yaml",
        ],
        config={
            "relationship_types": relationship_definitions(book_config=book_config),
            "confidence_levels": confidence_definitions(),
            "novel_summary": novel_summary,
            "pre_typed": pre_typed,
        },
    )


# Fields the LLM classifier is allowed to contribute to a relationship dict
# (relationship-classifier-item.contract.yaml required_fields ∩ Relationship).
# Everything else the freeform LLM JSON might carry (reasoning, notes,
# evidence_kind, …) is dropped so {**pair, **classification} can only produce a
# valid Relationship.
_KNOWN_CLASSIFICATION_KEYS = frozenset(
    {"relationship_type", "direction", "evolution", "key_moments", "evidence", "confidence"}
)

# STU-556: a pair discovered by the schema pass is already typed and directed
# (20/20 against a human gold on Eragon), so the demoted classifier contributes
# only prose and the confidence grade — it must not overwrite the type it was
# handed. A co-occurrence-fallback pair carries no type, so the classifier still
# types it (legacy path) via the full key set above.
_PROSE_KEYS = frozenset({"evolution", "key_moments", "confidence"})


def _select_input(processing: Path) -> tuple[Path, bool]:
    """Choose the relation graph to classify: the schema-discovered typed graph if
    present (STU-556), else the deterministic co-occurrence graph. Returns
    ``(path, pre_typed)`` — ``pre_typed`` is True when the pairs already carry a
    type the classifier must preserve rather than decide."""
    discovered = processing / "relationships_discovered.json"
    if discovered.exists():
        return discovered, True
    return processing / "relationships.json", False


def _merge_classification(pair: dict, classification: dict, *, pre_typed: bool) -> dict:
    """Fold the classifier's contribution onto a pair. For a discovered pair only
    prose + confidence are taken (the discovered type/direction/evidence stand);
    for a co-occurrence pair the classifier's type/direction too."""
    keys = _PROSE_KEYS if pre_typed else _KNOWN_CLASSIFICATION_KEYS
    contrib = {k: v for k, v in classification.items() if k in keys and v is not None}
    return {**pair, **contrib}

# STU-496: how many per-entity role/status excerpts to surface to the classifier.
_MAX_ROLE_CONTEXTS = 6


def _entity_role_contexts(
    registry: Registry, max_per_entity: int = _MAX_ROLE_CONTEXTS
) -> dict[str, list[str]]:
    """Per-entity context sentences that establish role/status/faction (STU-496).

    Structural pairs (rival Champions, institutional employer, mediated killer)
    never share a dyadic scene, so the classifier needs each entity's own
    role-establishing excerpts. The first mention usually introduces the
    character with their title/role, so the earliest context is always kept;
    the rest are sampled evenly across the entity's mentions.
    """
    out: dict[str, list[str]] = {}
    for rec in registry.entities:
        seen: set[str] = set()
        contexts: list[str] = []
        for mention in rec.mentions:
            sentence = (mention.context or "").strip()
            if sentence and sentence not in seen:
                seen.add(sentence)
                contexts.append(sentence)
        if len(contexts) <= max_per_entity:
            out[rec.canonical_name] = contexts
        else:
            step = len(contexts) / max_per_entity
            out[rec.canonical_name] = [contexts[int(i * step)] for i in range(max_per_entity)]
    return out


_TIMEOUT_SECONDS = 7200


def _run_classify_fanout(items: list[dict], prompt_fingerprint: str) -> tuple[dict | None, str | None]:
    """One `studio run` fanning out over all classifiable pairs. Returns (map_output, error)."""
    payload = {"pairs": items, "prompt_fingerprint": prompt_fingerprint}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(payload, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name
    cmd = ["studio", "run", "classify-relationships", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        return None, "studio_cli_missing"
    except subprocess.TimeoutExpired:
        return None, "studio_run_timeout"
    finally:
        Path(input_path).unlink(missing_ok=True)
    if result.returncode != 0:
        return None, "studio_run_failed"
    map_output = studio_io.stage_output_from_stdout(result.stdout or "", "classify")
    if map_output is None:
        return None, "studio_run_output_missing"
    return map_output, None


def _save(output_path: Path, base: dict, classified: list[dict]) -> None:
    bundle = RelationshipBundle(
        entities=base.get("entities", []),
        relationships=[Relationship(**r) for r in classified],
        stats=base.get("stats", {}),
        narrator=base.get("narrator"),
    )
    studio_io.save_artifact(output_path, bundle, RelationshipBundle)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classify relationships via Studio (relationship-classifier-item pipeline)."
    )
    parser.add_argument(
        "--book", required=True,
        help="Path to book YAML, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Skip Studio calls, pass pairs through unchanged",
    )
    args = parser.parse_args()

    book_paths = book_paths_from_yaml(args.book)
    input_path, pre_typed = _select_input(book_paths.processing)
    output_path = book_paths.processing / "relationships_classified.json"

    if not input_path.exists():
        print(f"[ERROR] Input not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(
        f"[classify-relationships] Source: {input_path.name} "
        f"({'schema-discovered, typed' if pre_typed else 'co-occurrence, untyped'})",
        file=sys.stderr,
    )

    # dict-only boundary: the incremental per-pair classify/resume loop below
    # merges LLM classification dicts into relationship dicts (_load_done_keys/
    # _save stay dict-based for interrupted-run tolerance) — validated on load
    # here, converted back to plain dicts for that loop.
    bundle = studio_io.load_artifact(input_path, RelationshipBundle)
    data = studio_io.to_dict(bundle)
    relationships = data.get("relationships", [])
    entity_types = {e["canonical_name"]: e.get("type", "") for e in data.get("entities", [])}
    base = {k: v for k, v in data.items() if k != "relationships"}

    # STU-435: fold the co-occurrence graph onto canonical entities before
    # classifying. The graph is built at mention level (surface forms, pre
    # alias-resolution) so a single entity's edges are split across its aliases
    # (e.g. "Chaol Westfall" vs "Captain Westfall"). registry.alias_table()
    # collapses them so each canonical pair is classified exactly once, on the
    # summed cooccurrence signal instead of two weak fragments.
    registry_path = book_paths.processing / "registry.json"
    role_contexts: dict[str, list[str]] = {}
    if registry_path.exists():
        registry = Registry.load(registry_path)
        before = len(relationships)
        relationships = fold_relationships(relationships, registry)
        # Registry types are refined (post entity-classification) — prefer them.
        entity_types = {rec.canonical_name: rec.entity_type for rec in registry.entities}
        role_contexts = _entity_role_contexts(registry)
        print(
            f"[classify-relationships] Folded {before} surface edges into "
            f"{len(relationships)} canonical pairs via registry.alias_table()",
            file=sys.stderr,
        )
    else:
        print(
            f"[classify-relationships] registry.json not found ({registry_path}) — "
            "classifying unfolded surface edges, no role contexts (STU-496)",
            file=sys.stderr,
        )

    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}
    novel_summary = book_cfg.get("novel_summary") or ""

    fingerprint = _classifier_fingerprint(
        book_config=book_cfg, novel_summary=novel_summary, pre_typed=pre_typed
    )
    base_stats = dict(base.get("stats") or {})
    base_stats["classifier_prompt"] = fingerprint
    base["stats"] = base_stats

    to_classify = [r for r in relationships if _should_classify_pair(r, entity_types)]
    passthrough = [r for r in relationships if not _should_classify_pair(r, entity_types)]
    print(
        f"[classify-relationships] {len(relationships)} pairs total | "
        f"{len(passthrough)} non-interpersonal (pass through) | "
        f"{len(to_classify)} to classify",
        file=sys.stderr,
    )

    if args.dry_run or not to_classify:
        _save(output_path, base, passthrough + to_classify)
        print(
            f"[classify-relationships] {'Dry run — ' if args.dry_run else ''}"
            f"{len(relationships)} pairs passed through",
            file=sys.stderr,
        )
        return

    items = [
        classifier_item_input(
            pair,
            novel_summary=novel_summary,
            role_contexts_a=role_contexts.get(pair.get("entity_a", ""), []),
            role_contexts_b=role_contexts.get(pair.get("entity_b", ""), []),
            book_config=book_cfg,
        )
        for pair in to_classify
    ]
    map_output, error = _run_classify_fanout(items, fingerprint)

    classified: list[dict] = list(passthrough)
    if error:
        # STU-562: an unjudged Studio failure is stamped, never conflated with a
        # decline — the whole fan-out failing stamps every classifiable pair, so
        # downstream still gets an artifact and a re-run retries them all.
        print(
            f"[classify-relationships] WARNING: {error} — stamping "
            f"{len(to_classify)} pairs classification_error",
            file=sys.stderr,
        )
        classified.extend({**pair, "classification_error": error} for pair in to_classify)
    else:
        results_by_index: dict[int, dict] = {}
        for result in map_output.get("results") or []:
            if isinstance(result, dict) and isinstance(result.get("index"), int):
                results_by_index[result["index"]] = result
        for i, pair in enumerate(to_classify):
            result = results_by_index.get(i)
            label = f"{pair.get('entity_a', '?')}↔{pair.get('entity_b', '?')}"
            if result and result.get("status") == "success" and isinstance(result.get("output"), dict):
                merged = _merge_classification(pair, result["output"], pre_typed=pre_typed)
                print(f"  [CLF]  {label} → {merged.get('relationship_type') or 'null'}", file=sys.stderr)
            else:
                item_error = (result or {}).get("error") or "no_result"
                merged = {**pair, "classification_error": str(item_error)}
                print(f"  [WARN] {label}: {item_error} — will retry next run", file=sys.stderr)
            classified.append(merged)
        resumed = map_output.get("resumed", 0)
        if resumed:
            print(f"[classify-relationships] {resumed} pairs served from resume cache", file=sys.stderr)

    _save(output_path, base, classified)
    succeeded = sum(1 for r in classified if r.get("relationship_type") is not None)
    errored = sum(1 for r in classified if r.get("classification_error"))
    summary = f"\n[classify-relationships] Done — {len(classified)} total, {succeeded} classified"
    if errored:
        summary += f", {errored} unjudged (Studio error)"
    print(summary, file=sys.stderr)


if __name__ == "__main__":
    main()
