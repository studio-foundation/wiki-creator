#!/usr/bin/env python3
"""
Stage: verify-entity-types (script executor, optional LLM)

Checks clusters typed PLACE or ORG that might actually be PERSON,
using Ollama (mistral:7b-instruct) for ambiguous cases.

Activated via input YAML flag: verify_entity_types: true
When false (default): pure pass-through, no Ollama call.

Input (Studio stdin):
  additional_context: YAML with verify_entity_types, ollama_model
  previous_outputs["entity-clustering"]: {clusters, stats}

Side reads (from project root):
  places_full.json  — context sentences for PLACE-typed entities
  orgs_full.json    — context sentences for ORG-typed entities

Output (stdout):
  {clusters, stats, type_corrections: [{cluster_id, name, from, to, context_snippet}]}
"""

import json
import re
import sys
from pathlib import Path
import yaml

from wiki_creator import studio_io
from wiki_creator.llm import ollama

# Keywords that indicate a genuine geographic entity — skip LLM for these. No
# vocabulary is hardcoded here (STU-518): the place-type nouns live in
# cue_words/<lang>.json `geographic_keywords`. Unknown language → empty set.
GEOGRAPHIC_KEYWORDS: frozenset[str] = frozenset()

DEFAULT_MODEL = "mistral:7b-instruct"

TYPE_TO_KEY = {
    "PLACE": "places_full",
    "ORG": "orgs_full",
}


def load_geographic_keywords(language: str | None = None) -> frozenset[str]:
    """Return the language's `geographic_keywords` from cue_words/{lang}.json."""
    if not language:
        return GEOGRAPHIC_KEYWORDS
    try:
        from wiki_creator.lang import load_lang_config
        lang_cfg = load_lang_config(language)
        return frozenset(w.lower() for w in lang_cfg.get("geographic_keywords", []))
    except Exception as exc:
        print(f"Warning: could not load cue_words for language {language!r}: {exc}", file=sys.stderr)
        return GEOGRAPHIC_KEYWORDS


def is_obvious_geographic(name: str, geographic_keywords: frozenset[str] = GEOGRAPHIC_KEYWORDS) -> bool:
    """Return True if the canonical name contains a geographic keyword."""
    tokens = name.lower().split()
    return bool(set(tokens) & geographic_keywords)


def load_context_for_cluster(
    entity_ids: list[str],
    original_type: str,
    type_files: dict[str, str] | None = None,
    search_dirs: list[str] | None = None,
    max_sentences: int = 3,
) -> list[str]:
    """
    Load up to max_sentences context snippets for the given entity_ids
    from the appropriate *_full.json file.

    type_files: mapping of entity type to full file path (default: root-level files).
    Returns a flat list of sentence strings.
    """
    if type_files is None:
        type_files = {
            "PLACE": "places_full.json",
            "ORG": "orgs_full.json",
        }
        if search_dirs:
            type_files = {
                entity_type: str(Path(search_dirs[0]) / filename)
                for entity_type, filename in type_files.items()
            }

    json_key = TYPE_TO_KEY.get(original_type)
    file_path = type_files.get(original_type)
    if not file_path or not json_key:
        return []

    data: dict = {}
    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f).get(json_key, {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    sentences: list[str] = []
    for eid in entity_ids:
        entity = data.get(eid, {})
        mentions_by_chapter = entity.get("mentions_by_chapter", {})
        for chapter_sents in mentions_by_chapter.values():
            sentences.extend(chapter_sents)
            if len(sentences) >= max_sentences:
                return sentences[:max_sentences]

    return sentences[:max_sentences]


def apply_corrections(clusters: list[dict], corrections: list[dict]) -> list[dict]:
    """
    Apply type corrections to clusters in-place (returns new list).
    corrections: [{cluster_id, from, to}]
    """
    correction_map = {c["cluster_id"]: c["to"] for c in corrections}
    result = []
    for cluster in clusters:
        cid = cluster["cluster_id"]
        if cid in correction_map:
            cluster = dict(cluster)
            cluster["type"] = correction_map[cid]
        result.append(cluster)
    return result


def _call_ollama(name: str, context_sentences: list[str], model: str) -> str | None:
    """
    Ask Ollama to classify `name` as PERSON, PLACE, or ORG.
    Returns "PERSON", "PLACE", "ORG", or None on failure.
    """
    context_text = " ".join(context_sentences)
    prompt = (
        f"Given these sentences from a novel, is '{name}' a person, "
        f"a place, or an organization? "
        f"Reply with exactly one word: PERSON, PLACE, or ORG.\n"
        f"Sentences: {context_text}"
    )

    reply = ollama.generate(prompt, model=model, timeout=30)  # Ollama can be slow on first model load
    if reply is None:
        print(f"Warning: Ollama call failed for '{name}'", file=sys.stderr)
        return None
    reply = reply.upper()
    for label in ("PERSON", "PLACE", "ORG"):
        if re.search(rf"\b{label}\b", reply):
            return label
    return None


def verify_clusters(
    clusters: list[dict],
    model: str = DEFAULT_MODEL,
    type_files: dict[str, str] | None = None,
    geographic_keywords: frozenset[str] = GEOGRAPHIC_KEYWORDS,
) -> list[dict]:
    """
    Identify and return corrections for clusters that should be reclassified.
    Returns list of {cluster_id, name, from, to, context_snippet}.
    """
    corrections = []

    for cluster in clusters:
        original_type = cluster.get("type", "OTHER")
        if original_type not in ("PLACE", "ORG"):
            continue

        name = cluster.get("canonical_candidate", "")
        if not name or is_obvious_geographic(name, geographic_keywords):
            continue

        entity_ids = cluster.get("entity_ids", [])
        context = load_context_for_cluster(entity_ids, original_type, type_files)
        if not context:
            continue

        new_type = _call_ollama(name, context, model)
        if new_type == "PERSON":
            snippet = context[0][:80] if context else ""
            print(
                f"[VERIFY] {name}: {original_type} → PERSON "
                f"(context: \"{snippet}...\")",
                file=sys.stderr,
            )
            corrections.append({
                "cluster_id": cluster["cluster_id"],
                "name": name,
                "from": original_type,
                "to": "PERSON",
                "context_snippet": snippet,
            })

    return corrections


def main() -> None:
    payload = studio_io.read_payload()
    input_data = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    enabled = input_data.get("verify_entity_types", False)

    clustering_output = payload.get("previous_outputs", {}).get("entity-clustering", {})
    clusters = clustering_output.get("clusters", [])
    stats = clustering_output.get("stats", {})

    if not enabled:
        json.dump(
            {"clusters": clusters, "stats": stats, "type_corrections": []},
            sys.stdout,
            ensure_ascii=False,
        )
        return

    paths = studio_io.paths_from_payload(payload, strict=False)
    type_files = None
    if paths is not None:
        type_files = {
            "PLACE": str(paths.processing / "places_full.json"),
            "ORG":   str(paths.processing / "orgs_full.json"),
        }

    from wiki_creator.lang import book_language
    try:
        language = book_language(input_data)
    except Exception:
        language = None
    geographic_keywords = load_geographic_keywords(language)

    model = input_data.get("ollama_model", DEFAULT_MODEL)
    corrections = verify_clusters(
        clusters, model=model, type_files=type_files, geographic_keywords=geographic_keywords
    )
    corrected_clusters = apply_corrections(clusters, corrections)

    # Persist corrections for wiki-resolution restarts (STU-302)
    if paths is not None:
        paths.processing.mkdir(parents=True, exist_ok=True)
        corrections_path = paths.processing / "entity_type_corrections.json"
        with open(corrections_path, "w", encoding="utf-8") as _f:
            json.dump(corrections, _f, ensure_ascii=False)

    json.dump(
        {
            "clusters": corrected_clusters,
            "stats": stats,
            "type_corrections": corrections,
        },
        sys.stdout,
        ensure_ascii=False,
    )


if __name__ == "__main__":
    main()
