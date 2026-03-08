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
import yaml
from wiki_creator.paths import book_paths_from_epub, BookPaths

# Keywords that indicate a genuine geographic entity — skip LLM for these
GEOGRAPHIC_KEYWORDS = frozenset({
    "rue", "avenue", "boulevard", "place", "quartier", "ville",
    "église", "eglise", "cathédrale", "cathedrale", "cimetière",
    "cimetiere", "gare", "marché", "marche", "pont", "tour",
    "château", "chateau", "palais", "hotel", "hôtel",
    "calle", "plaza", "barrio",  # Spanish geographic terms
})

DEFAULT_MODEL = "mistral:7b-instruct"

TYPE_TO_KEY = {
    "PLACE": "places_full",
    "ORG": "orgs_full",
}


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)


def is_obvious_geographic(name: str) -> bool:
    """Return True if the canonical name contains a geographic keyword."""
    tokens = name.lower().split()
    return bool(set(tokens) & GEOGRAPHIC_KEYWORDS)


def load_context_for_cluster(
    entity_ids: list[str],
    original_type: str,
    type_files: dict[str, str] | None = None,
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
    try:
        import requests
    except ImportError:
        print("Warning: requests not available, skipping Ollama call", file=sys.stderr)
        return None

    context_text = " ".join(context_sentences)
    prompt = (
        f"Given these sentences from a novel, is '{name}' a person, "
        f"a place, or an organization? "
        f"Reply with exactly one word: PERSON, PLACE, or ORG.\n"
        f"Sentences: {context_text}"
    )

    try:
        resp = requests.post(
            "http://localhost:11434/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=30,  # Ollama can be slow on first model load
        )
        resp.raise_for_status()
        reply = resp.json().get("response", "").upper()
        for label in ("PERSON", "PLACE", "ORG"):
            if re.search(rf"\b{label}\b", reply):
                return label
        return None
    except Exception as exc:
        print(f"Warning: Ollama call failed for '{name}': {exc}", file=sys.stderr)
        return None


def verify_clusters(
    clusters: list[dict],
    model: str = DEFAULT_MODEL,
    type_files: dict[str, str] | None = None,
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
        if not name or is_obvious_geographic(name):
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
    payload = json.load(sys.stdin)
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

    paths = _paths_from_payload(payload)
    type_files = {
        "PLACE": str(paths.processing / "places_full.json"),
        "ORG":   str(paths.processing / "orgs_full.json"),
    }

    model = input_data.get("ollama_model", DEFAULT_MODEL)
    corrections = verify_clusters(clusters, model=model, type_files=type_files)
    corrected_clusters = apply_corrections(clusters, corrections)

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
