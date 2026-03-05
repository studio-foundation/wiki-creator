#!/usr/bin/env python3
"""
Stage: Relationship Extraction (STU-229)
Builds a weighted co-occurrence graph between resolved PERSON entities.

Pipeline position:
  epub-parse → entity-extraction → entity-clustering → entity-resolution
  → relationship-extraction → wiki-generation

Input (via Studio context):
  previous_outputs.entity-resolution: { "entities": [{canonical_name, type, aliases, source_ids, relevant}] }
  Files read from repo root: persons_full.json, places_full.json, orgs_full.json

Output (stdout):
  {
    "relationships": [
      {
        "entity_a": "David Martín",
        "entity_b": "Pedro Vidal",
        "cooccurrence_count": 45,
        "chapters": ["ch01", "ch03"],
        "sample_contexts": ["Vidal tendit le manuscrit à Martín..."],
        "relationship_type": null,
        "direction": null,
        "evolution": null,
        "key_moments": []
      }
    ],
    "stats": {
      "total_pairs_checked": 120,
      "pairs_above_threshold": 18,
      "classified": 0,
      "window_size": 5,
      "threshold": 5
    }
  }

Standalone test:
  python scripts/relationship_extraction.py --test
  python scripts/relationship_extraction.py --test --classify
  python scripts/relationship_extraction.py --test --window 3 --threshold 2
"""

import json
import re
import sys


DEFAULT_WINDOW = 5
DEFAULT_THRESHOLD = 5


def build_cooccurrence_graph(
    entities: list[dict],
    mentions_by_entity: dict[str, dict[str, list[str]]],
    window_size: int = DEFAULT_WINDOW,
    threshold: int = DEFAULT_THRESHOLD,
) -> tuple[list[dict], dict]:
    """
    Build weighted co-occurrence graph between PERSON entities.

    Args:
        entities: resolved entities with canonical_name, aliases, relevant, type
        mentions_by_entity: {canonical_name: {chapter_id: [sentence, ...]}}
        window_size: sliding window of N sentences
        threshold: minimum co-occurrence count to include in output

    Returns:
        (relationships list, stats dict)
    """
    # Filter to PERSON entities that are relevant
    persons = [e for e in entities if e.get("type") == "PERSON" and e.get("relevant", True)]

    # Build lookup: all known names (canonical + aliases ≥4 chars) → canonical_name
    name_to_canonical: dict[str, str] = {}
    for entity in persons:
        canonical = entity["canonical_name"]
        key = canonical.lower()
        if key in name_to_canonical and name_to_canonical[key] != canonical:
            print(f"[WARN] Name collision: '{canonical}' conflicts with '{name_to_canonical[key]}'", file=sys.stderr)
        name_to_canonical[key] = canonical
        for alias in entity.get("aliases", []):
            if len(alias) >= 4:
                alias_key = alias.lower()
                if alias_key in name_to_canonical and name_to_canonical[alias_key] != canonical:
                    print(f"[WARN] Alias collision: '{alias}' maps to both '{name_to_canonical[alias_key]}' and '{canonical}'", file=sys.stderr)
                else:
                    name_to_canonical[alias_key] = canonical

    # Co-occurrence matrix: {(canonical_a, canonical_b): {"count": int, "chapters": set, "contexts": list}}
    cooc: dict[tuple[str, str], dict] = {}

    total_pairs_checked = len(persons) * (len(persons) - 1) // 2

    persons_canonical = {e["canonical_name"] for e in persons}

    # Build unified chapter sentences (deduplicated, order-preserved) across all entity mentions
    chapter_sentences: dict[str, list[str]] = {}
    for canonical, chapters in mentions_by_entity.items():
        if canonical not in persons_canonical:
            continue
        for chapter_id, sentences in chapters.items():
            if chapter_id not in chapter_sentences:
                chapter_sentences[chapter_id] = []
            for sent in sentences:
                if sent not in chapter_sentences[chapter_id]:
                    chapter_sentences[chapter_id].append(sent)

    # Slide window once per chapter
    for chapter_id, sentences in chapter_sentences.items():
        for i in range(len(sentences)):
            window = sentences[i : i + window_size]
            window_text = " ".join(window)

            # Find which entities appear in this window
            present: set[str] = set()
            for name, canon in name_to_canonical.items():
                if re.search(r'\b' + re.escape(name) + r'\b', window_text.lower()):
                    present.add(canon)

            # Record all pairs in this window
            present_list = sorted(present)
            for idx_a in range(len(present_list)):
                for idx_b in range(idx_a + 1, len(present_list)):
                    a, b = present_list[idx_a], present_list[idx_b]
                    key = (a, b)
                    if key not in cooc:
                        cooc[key] = {"count": 0, "chapters": set(), "contexts": []}
                    cooc[key]["count"] += 1
                    cooc[key]["chapters"].add(chapter_id)
                    if len(cooc[key]["contexts"]) < 3:
                        cooc[key]["contexts"].append(window[0])

    # Build output: filter by threshold, sort by count desc
    relationships = []
    for (a, b), data in cooc.items():
        if data["count"] >= threshold:
            relationships.append({
                "entity_a": a,
                "entity_b": b,
                "cooccurrence_count": data["count"],
                "chapters": sorted(data["chapters"]),
                "sample_contexts": data["contexts"],
                "relationship_type": None,
                "direction": None,
                "evolution": None,
                "key_moments": [],
            })

    relationships.sort(key=lambda r: r["cooccurrence_count"], reverse=True)

    pairs_above = len(relationships)
    stats = {
        "total_pairs_checked": total_pairs_checked,
        "pairs_above_threshold": pairs_above,
        "classified": 0,
        "window_size": window_size,
        "threshold": threshold,
    }

    return relationships, stats


def run_test_mode(window_size: int, threshold: int) -> None:
    """Run with hardcoded Le Jeu de l'Ange data."""
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín", "David"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "aliases": ["Vidal"], "relevant": True},
        {"canonical_name": "Andreas Corelli", "type": "PERSON", "aliases": ["Corelli"], "relevant": True},
        {"canonical_name": "Isabella", "type": "PERSON", "aliases": ["Isa"], "relevant": True},
        {"canonical_name": "Cristina", "type": "PERSON", "aliases": [], "relevant": True},
    ]

    mentions_by_entity = {
        "David Martín": {
            "ch01": [
                "Vidal tendit le manuscrit à Martín en souriant.",
                "Martín retrouva Vidal au café de la rue Fernando.",
                "Martín écrivit toute la nuit.",
                "Vidal encouragea Martín à continuer son roman.",
                "Martín pensait souvent à Isabella.",
            ],
            "ch02": [
                "Martín reçut une lettre de Corelli.",
                "Corelli proposa un contrat à Martín.",
                "Martín hésita longtemps avant d'accepter.",
                "Cristina observait Martín depuis le couloir.",
                "Martín ne remarqua pas Cristina.",
            ],
            "ch03": [
                "Isabella retrouva Martín dans le parc.",
                "Martín et Isabella parlèrent des heures.",
                "Vidal arriva et interrompit leur conversation.",
                "Martín regarda Vidal avec méfiance.",
                "Corelli attendait Martín dans son bureau.",
            ],
        },
        "Pedro Vidal": {
            "ch01": [
                "Vidal tendit le manuscrit à Martín en souriant.",
                "Martín retrouva Vidal au café de la rue Fernando.",
                "Vidal encouragea Martín à continuer son roman.",
                "Vidal rentra chez lui à minuit.",
            ],
            "ch03": [
                "Vidal arriva et interrompit leur conversation.",
                "Martín regarda Vidal avec méfiance.",
            ],
        },
        "Andreas Corelli": {
            "ch02": [
                "Martín reçut une lettre de Corelli.",
                "Corelli proposa un contrat à Martín.",
                "Martín hésita longtemps avant d'accepter.",
                "Corelli attendait Martín dans son bureau.",
            ],
            "ch03": [
                "Corelli attendait Martín dans son bureau.",
            ],
        },
        "Isabella": {
            "ch01": [
                "Martín pensait souvent à Isabella.",
            ],
            "ch03": [
                "Isabella retrouva Martín dans le parc.",
                "Martín et Isabella parlèrent des heures.",
                "Vidal arriva et interrompit leur conversation.",
            ],
        },
        "Cristina": {
            "ch02": [
                "Cristina observait Martín depuis le couloir.",
                "Martín ne remarqua pas Cristina.",
            ],
        },
    }

    relationships, stats = build_cooccurrence_graph(
        entities, mentions_by_entity, window_size, threshold
    )

    print(f"=== TEST MODE — relationship-extraction ===\n")
    print(f"Window size: {window_size}  |  Threshold: {threshold}\n")
    print(f"Top relationships (cooccurrence_count desc):\n")
    for rel in relationships[:20]:
        classified = f"  → {rel['relationship_type']}" if rel.get("relationship_type") else ""
        print(f"  {rel['entity_a']} ↔ {rel['entity_b']}")
        print(f"    count={rel['cooccurrence_count']}  chapters={rel['chapters']}{classified}")
        if rel.get("sample_contexts"):
            print(f"    sample: {rel['sample_contexts'][0][:80]}...")
        print()

    print(f"=== STATS ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    # Validation
    top_pairs = {
        (r["entity_a"], r["entity_b"]) for r in relationships
    } | {
        (r["entity_b"], r["entity_a"]) for r in relationships
    }
    expected = [
        ("David Martín", "Pedro Vidal"),
        ("David Martín", "Andreas Corelli"),
        ("David Martín", "Isabella"),
        ("David Martín", "Cristina"),
    ]
    print("\n=== VALIDATION ===")
    all_ok = True
    for a, b in expected:
        found = (a, b) in top_pairs or (b, a) in top_pairs
        status = "✓" if found else "✗ MISSING"
        print(f"  {status}  {a} ↔ {b}")
        if not found:
            all_ok = False
    print(f"\n{'All expected pairs found.' if all_ok else 'SOME PAIRS MISSING — check algorithm.'}")

    if "--classify" in sys.argv:
        print("\n=== CLASSIFY MODE ===")
        relationships = classify_relationships(relationships)
        classified_count = sum(1 for r in relationships if r.get("relationship_type"))
        print(f"Classified {classified_count}/{len(relationships)} relationships")
        for r in relationships[:5]:
            print(f"  {r['entity_a']} ↔ {r['entity_b']}: {r['relationship_type']} ({r['direction']})")
            if r.get("evolution"):
                print(f"    Evolution: {r['evolution']}")
        stats["classified"] = classified_count


def classify_relationships(relationships: list[dict]) -> list[dict]:
    """Classify relationships using Haiku. Fails gracefully per pair."""
    import anthropic

    client = anthropic.Anthropic()
    result = []

    for rel in relationships:
        contexts_text = "\n".join(
            f'{i+1}. "{ctx}"' for i, ctx in enumerate(rel["sample_contexts"][:3])
        )
        prompt = f"""Voici des extraits d'un roman où deux personnages apparaissent ensemble.
Personnage A : {rel['entity_a']}
Personnage B : {rel['entity_b']}
Cooccurrences : {rel['cooccurrence_count']}

Extraits :
{contexts_text}

Classifie leur relation. Réponds en JSON uniquement, sans markdown :
{{
  "relationship_type": "famille|mentor/protégé|amoureux|antagoniste|allié|employeur/employé|ami|connaissance|autre",
  "direction": "symétrique|A→B|B→A",
  "evolution": "en une phrase, comment la relation évolue",
  "key_moments": ["chXX: description courte"]
}}"""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            classification = json.loads(response.content[0].text)
            rel = {
                **rel,
                "relationship_type": classification.get("relationship_type"),
                "direction": classification.get("direction"),
                "evolution": classification.get("evolution"),
                "key_moments": classification.get("key_moments", []),
            }
        except Exception as e:
            print(f"  [WARN] classification failed for {rel['entity_a']}↔{rel['entity_b']}: {e}", file=sys.stderr)

        result.append(rel)

    return result


def _load_mentions_from_files() -> dict[str, dict[str, list[str]]]:
    """
    Load mentions_by_chapter from per-type entity files written by entity-extraction.
    Returns {first_raw_mention: {chapter_id: [sentences]}}.
    Files are read from the current working directory (where Studio runs).
    """
    import os

    mentions: dict[str, dict[str, list[str]]] = {}
    type_files = {
        "persons_full.json": "persons_full",
        "places_full.json": "places_full",
        "orgs_full.json": "orgs_full",
    }

    for filename, key in type_files.items():
        if not os.path.exists(filename):
            continue
        with open(filename, encoding="utf-8") as f:
            data = json.load(f)
        for entity_id, entry in data.get(key, {}).items():
            raw = entry.get("raw_mentions", [])
            name = raw[0] if raw else entity_id
            mentions[name] = entry.get("mentions_by_chapter", {})

    return mentions


def main() -> None:
    args = sys.argv[1:]

    window_size = DEFAULT_WINDOW
    threshold = DEFAULT_THRESHOLD

    if "--window" in args:
        idx = args.index("--window")
        window_size = int(args[idx + 1])

    if "--threshold" in args:
        idx = args.index("--threshold")
        threshold = int(args[idx + 1])

    if "--test" in args:
        run_test_mode(window_size, threshold)
        return

    payload = json.load(sys.stdin)

    prev_outputs = payload.get("previous_outputs", {})
    resolution_output = prev_outputs.get("entity-resolution", {})
    entities = resolution_output.get("entities", [])

    if not entities:
        json.dump({"error": "missing entity-resolution output"}, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    # Parse classify flag from additional_context (YAML string)
    import yaml
    do_classify = False
    raw_context = payload.get("additional_context", "")
    if raw_context:
        try:
            additional = yaml.safe_load(raw_context) or {}
            do_classify = bool(additional.get("classify", False))
        except Exception:
            pass

    mentions_by_entity = _load_mentions_from_files()

    relationships, stats = build_cooccurrence_graph(
        entities, mentions_by_entity, window_size, threshold
    )

    if do_classify:
        relationships = classify_relationships(relationships)
        stats["classified"] = sum(1 for r in relationships if r.get("relationship_type"))

    json.dump({
        "entities": entities,
        "relationships": relationships,
        "stats": stats,
    }, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
