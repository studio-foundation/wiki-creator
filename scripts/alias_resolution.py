#!/usr/bin/env python3
"""
Stage: alias-resolution

Consumes resolved entities from resolve-clusters and conservatively merges PERSON
entities when local mention context contains strong alias or reveal evidence.
"""

import json
import re
import sys
from pathlib import Path

import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from wiki_creator.paths import book_paths_from_epub, BookPaths

_PATTERN_TEMPLATES = (
    r"\byou may call me {b}\b",
    r"\balso known as {b}\b",
    r"\bformerly known as {b}\b",
    r"\bcalled (?:him|her|them) {b}\b",
    r"\b{a}[^.]{{0,80}}\banother name[^.]{{0,80}}\b{b}\b",
    r"\b{a}[^.]{{0,80}}\bunder another name[^.]{{0,80}}\b{b}\b",
)

_REVEAL_WORDS = (
    "another name",
    "other name",
    "under another name",
    "true name",
    "real name",
    "hidden identity",
    "alias",
)


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)


def _empty_stats() -> dict:
    return {
        "candidates_considered": 0,
        "merges_applied": 0,
        "merges_by_method": {"pattern": 0, "cooccurrence": 0, "llm": 0},
        "ambiguous_pairs": 0,
        "llm_attempts": 0,
        "llm_confirmed": 0,
        "llm_failed": 0,
    }


def _load_persons_full(processing_dir: Path) -> dict:
    path = processing_dir / "persons_full.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("persons_full", {})


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _entity_names(entity: dict) -> list[str]:
    names = [entity.get("canonical_name", "")]
    names.extend(entity.get("aliases", []))
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        cleaned = str(name or "").strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _gather_contexts(entity: dict, persons_full: dict) -> list[str]:
    snippets: list[str] = []
    for source_id in entity.get("source_ids", []):
        entry = persons_full.get(source_id, {})
        for mentions in entry.get("mentions_by_chapter", {}).values():
            for snippet in mentions:
                if isinstance(snippet, str) and snippet.strip():
                    snippets.append(snippet.strip())
    return snippets


def _pick_canonical_name(entity_a: dict, entity_b: dict, persons_full: dict) -> str:
    counts: dict[str, int] = {}
    for entity in (entity_a, entity_b):
        for name in _entity_names(entity):
            counts[name] = 0
    for entity in (entity_a, entity_b):
        contexts = " ".join(_gather_contexts(entity, persons_full)).lower()
        for name in counts:
            counts[name] += contexts.count(name.lower())
    return sorted(
        counts,
        key=lambda name: (-counts[name], -len(name.split()), -len(name), name.lower()),
    )[0]


def _merge_entities(entity_a: dict, entity_b: dict, evidence: dict, persons_full: dict) -> dict:
    canonical = _pick_canonical_name(entity_a, entity_b, persons_full)
    alias_names = sorted({name for entity in (entity_a, entity_b) for name in _entity_names(entity)}, key=str.lower)
    source_ids = sorted({sid for entity in (entity_a, entity_b) for sid in entity.get("source_ids", [])})
    merged_from = [
        entity.get("canonical_name", "")
        for entity in (entity_a, entity_b)
        if entity.get("canonical_name") and entity.get("canonical_name") != canonical
    ]
    return {
        "canonical_name": canonical,
        "type": "PERSON",
        "aliases": alias_names,
        "source_ids": source_ids,
        "relevant": bool(entity_a.get("relevant", True) or entity_b.get("relevant", True)),
        "alias_resolution": {
            "merged_from": merged_from,
            "evidence": [evidence],
            "confidence": evidence["confidence"],
            "method": evidence["method"],
        },
    }


def _detect_pattern_match(entity_a: dict, entity_b: dict, persons_full: dict) -> dict | None:
    contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    names_a = _entity_names(entity_a)
    names_b = _entity_names(entity_b)
    for snippet in contexts:
        lowered = snippet.lower()
        for name_a in names_a:
            for name_b in names_b:
                if name_a.lower() == name_b.lower():
                    continue
                for template in _PATTERN_TEMPLATES:
                    pattern = template.format(a=re.escape(name_a.lower()), b=re.escape(name_b.lower()))
                    if re.search(pattern, lowered):
                        return {
                            "method": "pattern",
                            "confidence": "high",
                            "snippet": snippet,
                        }
    return None


def _detect_reveal_signal(entity_a: dict, entity_b: dict, persons_full: dict) -> dict | None:
    contexts = _gather_contexts(entity_a, persons_full) + _gather_contexts(entity_b, persons_full)
    names_a = [name.lower() for name in _entity_names(entity_a)]
    names_b = [name.lower() for name in _entity_names(entity_b)]
    matches: list[str] = []
    seen_a = False
    seen_b = False
    for snippet in contexts:
        lowered = snippet.lower()
        has_a = any(name in lowered for name in names_a)
        has_b = any(name in lowered for name in names_b)
        if not (has_a or has_b):
            continue
        if any(word in lowered for word in _REVEAL_WORDS):
            matches.append(snippet)
            seen_a = seen_a or has_a
            seen_b = seen_b or has_b
    if len(matches) >= 2 and seen_a and seen_b:
        return {
            "method": "cooccurrence",
            "confidence": "medium",
            "snippet": matches[0],
        }
    return None


def resolve_aliases(
    entities: list[dict],
    persons_full: dict,
    narrator=None,
    llm_confirmer=None,
) -> dict:
    stats = _empty_stats()
    resolved: list[dict] = []
    consumed: set[int] = set()

    for index, entity in enumerate(entities):
        if index in consumed:
            continue
        if entity.get("type") != "PERSON" or not entity.get("relevant", True):
            resolved.append(entity)
            continue

        merged = None
        for candidate_index in range(index + 1, len(entities)):
            if candidate_index in consumed:
                continue
            candidate = entities[candidate_index]
            if candidate.get("type") != "PERSON" or not candidate.get("relevant", True):
                continue

            stats["candidates_considered"] += 1
            evidence = _detect_pattern_match(entity, candidate, persons_full)
            if evidence:
                merged = _merge_entities(entity, candidate, evidence, persons_full)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["pattern"] += 1
                consumed.add(candidate_index)
                break

            reveal = _detect_reveal_signal(entity, candidate, persons_full)
            if not reveal:
                continue

            if llm_confirmer is None:
                stats["ambiguous_pairs"] += 1
                continue

            stats["llm_attempts"] += 1
            try:
                decision = llm_confirmer({
                    "entity_a": entity,
                    "entity_b": candidate,
                    "evidence": reveal,
                }) or {}
            except Exception:
                stats["llm_failed"] += 1
                stats["ambiguous_pairs"] += 1
                continue

            if decision.get("same_person"):
                merged_evidence = {
                    "method": "llm",
                    "confidence": decision.get("confidence", "medium"),
                    "snippet": decision.get("evidence", reveal["snippet"]),
                }
                merged = _merge_entities(entity, candidate, merged_evidence, persons_full)
                stats["merges_applied"] += 1
                stats["merges_by_method"]["llm"] += 1
                stats["llm_confirmed"] += 1
                consumed.add(candidate_index)
                break

            stats["ambiguous_pairs"] += 1

        resolved.append(merged or entity)

    return {"entities": resolved, "narrator": narrator, "stats": stats}


def main() -> None:
    payload = json.load(sys.stdin)
    previous_outputs = payload.get("previous_outputs", {})
    resolve_output = previous_outputs.get("resolve-clusters", {})
    entities = resolve_output.get("entities", [])
    narrator = resolve_output.get("narrator")

    persons_full = {}
    try:
        paths = _paths_from_payload(payload)
        persons_full = _load_persons_full(paths.processing)
    except ValueError:
        persons_full = {}

    result = resolve_aliases(entities, persons_full=persons_full, narrator=narrator)
    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
