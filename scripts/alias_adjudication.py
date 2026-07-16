#!/usr/bin/env python3
"""
Stage: alias-adjudication — merge the alias pairs no lexical rule can see.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Runs between alias-resolution and entity-classification, and re-emits the
alias-resolution payload with contextually-adjudicated PERSON merges applied. It
is a separate stage precisely because it is the only part of resolution that
needs the network: alias-resolution stays deterministic and offline, so
`make golden` and `make smoke` remain LLM-free by construction (STU-529).

Input:  { "all_stage_outputs": {"alias-resolution": {...}} }
Output: the alias-resolution payload, merges applied.
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from scripts.alias_resolution import _gather_contexts, _load_persons_full, _merge_entities
from wiki_creator import studio_io
from wiki_creator.alias_adjudication import (
    load_cached_merges,
    parse_merge_verdict,
    render_roster,
    roster_rows,
    save_merge_cache,
)
from wiki_creator.lang import infer_language, load_lang_config

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TIMEOUT_SECONDS = 600


def _run_alias_adjudication(rows: list[dict], book_title: str) -> tuple[list[dict], str | None]:
    """Adjudicate the roster with one `studio run`. Returns (merges, error)."""
    item_input = {"book_title": book_title, "roster": render_roster(rows)}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as tmp:
        yaml.safe_dump(item_input, tmp, sort_keys=False, allow_unicode=True)
        input_path = tmp.name

    cmd = ["studio", "run", "alias-adjudication-item", "--input-file", input_path, "--json"]
    try:
        result = subprocess.run(
            cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS
        )
    except FileNotFoundError:
        return [], "studio_cli_missing"
    except subprocess.TimeoutExpired:
        return [], "studio_run_timeout"
    finally:
        Path(input_path).unlink(missing_ok=True)

    if result.returncode != 0:
        return [], "studio_run_failed"
    run_payload = studio_io.extract_first_json_object(result.stdout or "")
    if run_payload is None:
        return [], "studio_output_json_parse_error"

    stage_output = studio_io.extract_stage_output_from_run_payload(run_payload, "alias-adjudication-item")
    if stage_output is None:
        run_id = str(run_payload.get("id") or "").strip()
        if run_id:
            stage_output = studio_io.load_studio_stage_output(run_id, "alias-adjudication-item")
    if stage_output is None:
        return [], "studio_run_output_missing"

    return parse_merge_verdict(stage_output, rows), None


def _apply_merges(
    entities: list[dict],
    persons: list[dict],
    merges: list[dict],
    persons_full: dict,
    role_words: list[str],
) -> list[dict]:
    """Fold each merge pair into one entity, keeping roster order.

    A name already consumed by an earlier merge is skipped rather than chained:
    the classifier judged the roster it was shown, and A=B plus B=C is not a
    verdict it was asked for.
    """
    # Keyed over the roster, not over `entities`: a PERSON and a PLACE may legally
    # share a canonical_name (STU-506), and only the PERSON was adjudicated.
    by_name = {entity["canonical_name"]: entity for entity in persons}
    consumed: set[str] = set()
    merged_by_name: dict[str, dict] = {}
    for merge in merges:
        name_a, name_b = merge["a"], merge["b"]
        if name_a in consumed or name_b in consumed:
            print(
                f"[alias-adjudication] skipping {name_a} = {name_b}: "
                "one side is already merged",
                file=sys.stderr,
            )
            continue
        evidence = {
            "method": "context_adjudication",
            "confidence": "medium",
            "snippet": merge["quote"],
        }
        merged = _merge_entities(
            by_name[name_a], by_name[name_b], evidence, persons_full, role_words=role_words
        )
        consumed.update({name_a, name_b})
        merged_by_name[name_a] = merged
        merged_by_name[name_b] = merged
        print(
            f"[alias-adjudication]   {name_a} = {name_b} "
            f"-> {merged['canonical_name']} ({merge['reason']})",
            file=sys.stderr,
        )

    roster = {id(entity) for entity in persons}
    resolved: list[dict] = []
    emitted: set[int] = set()
    for entity in entities:
        merged = merged_by_name.get(entity["canonical_name"]) if id(entity) in roster else None
        if merged is None:
            resolved.append(entity)
        elif id(merged) not in emitted:
            emitted.add(id(merged))
            resolved.append(merged)
    return resolved


def adjudicate_aliases(
    entities: list[dict],
    persons_full: dict,
    book_title: str,
    cache_path: Path,
    role_words: list[str],
) -> list[dict]:
    """Merge contextually-evidenced alias pairs, from cache or one LLM call.

    Never raises and never merges on a failure: a book whose verdict cannot be
    obtained keeps every entity separate, loudly.
    """
    persons = [
        entity for entity in entities
        if entity.get("type") == "PERSON" and entity.get("relevant", True)
    ]
    if len(persons) < 2:
        return entities

    contexts = {
        entity["canonical_name"]: _gather_contexts(entity, persons_full) for entity in persons
    }
    rows = roster_rows(persons, contexts)
    merges = load_cached_merges(cache_path, rows)
    if merges is None:
        merges, error = _run_alias_adjudication(rows, book_title)
        if error:
            print(
                f"[alias-adjudication] WARNING: {error} — merging nothing; "
                f"aliases among the {len(rows)} characters stay separate entities",
                file=sys.stderr,
            )
            return entities
        save_merge_cache(cache_path, rows, merges)

    print(
        f"[alias-adjudication] {len(merges)} merge(s) over a {len(rows)}-character roster",
        file=sys.stderr,
    )
    if not merges:
        return entities
    return _apply_merges(entities, persons, merges, persons_full, role_words)


def main() -> None:
    payload = studio_io.read_payload()
    all_stage_outputs = payload.get("all_stage_outputs", {})
    previous_outputs = payload.get("previous_outputs", {})
    source = (
        all_stage_outputs.get("alias-resolution")
        or previous_outputs.get("alias-resolution")
        or payload.get("previous_stage_output")
        or {}
    )
    entities = source.get("entities", [])

    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    export_categories = ctx.get("export", {}).get("categories", {})
    language = export_categories.get("language") or infer_language(ctx.get("spacy_model", ""))
    lang_cfg = load_lang_config(language) if language else {}
    classification_cfg = ctx.get("classification", {}) or {}
    role_words = list(dict.fromkeys(
        list(classification_cfg.get("role_words", []))
        + [w.lower() for w in lang_cfg.get("person_cue_words", [])]
    ))

    paths = studio_io.paths_from_payload(payload)
    resolved = adjudicate_aliases(
        entities,
        persons_full=_load_persons_full(paths.processing),
        book_title=str(ctx.get("title") or paths.processing.name),
        cache_path=paths.processing / "alias_adjudication.json",
        role_words=role_words,
    )

    json.dump({**source, "entities": resolved}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
