#!/usr/bin/env python3
"""
Stage: alias-adjudication — merge the alias pairs no lexical rule can see.

Script executor interface: reads JSON from stdin, writes JSON to stdout.

Post-step of the alias-adjudication split (STU-589). The LLM verdict arrives
from the `call: alias-adjudication-verdict` stage (native invocation, no
subprocess); this stage parses it, caches it, and re-emits the alias-resolution
payload with contextually-adjudicated PERSON merges applied. It is a separate
stage precisely because it is the only part of resolution that needs the
network: alias-resolution stays deterministic and offline, so `make golden`
and `make smoke` remain LLM-free by construction (STU-529).

Input:  { "all_stage_outputs": {"alias-resolution": {...}, "alias-adjudication-verdict": {...}} }
Output: the alias-resolution payload, merges applied.
"""

import json
import sys
from pathlib import Path

import yaml

from scripts.alias_resolution import _gather_contexts, _load_persons_full, _merge_entities
from wiki_creator import studio_io
from wiki_creator.alias_adjudication import (
    load_cached_merges,
    parse_merge_verdict,
    roster_rows,
    save_merge_cache,
)
from wiki_creator.lang import infer_language, load_lang_config

VERDICT_STAGE = "alias-adjudication-verdict"


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
    verdict_output: object | None,
    cache_path: Path,
    role_words: list[str],
) -> list[dict]:
    """Merge contextually-evidenced alias pairs, from cache or the call stage's verdict.

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
        if verdict_output is None:
            print(
                f"[alias-adjudication] WARNING: no verdict (call skipped or failed) — "
                f"merging nothing; "
                f"aliases among the {len(rows)} characters stay separate entities",
                file=sys.stderr,
            )
            return entities
        merges = parse_merge_verdict(verdict_output, rows)
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

    verdict_output = all_stage_outputs.get(VERDICT_STAGE)
    if verdict_output is None:
        verdict_output = previous_outputs.get(VERDICT_STAGE)

    paths = studio_io.paths_from_payload(payload)
    resolved = adjudicate_aliases(
        entities,
        persons_full=_load_persons_full(paths.processing),
        verdict_output=verdict_output,
        cache_path=paths.processing / "alias_adjudication.json",
        role_words=role_words,
    )

    json.dump({**source, "entities": resolved}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
