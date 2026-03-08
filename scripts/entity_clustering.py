#!/usr/bin/env python3
"""
Stage 2.5: Entity Clustering (deterministic, zero LLM)
Groups entity candidates by name similarity before LLM-based resolution.

Pipeline position:
  epub-parse → entity-extraction → **entity-clustering** → entity-resolution → wiki-generation

Input (via Studio context):
  previous_outputs.entity-extraction: { "entities_for_resolution": { entity_id: { type, raw_mentions, first_seen } } }

Output (stdout):
  {
    "clusters": [
      {
        "cluster_id": "cluster_001",
        "type": "PERSON",
        "canonical_mentions": ["Martín", "David Martín", "M. Martín", "Monsieur Martín", "David"],
        "entity_ids": ["entity_001", "entity_003", "entity_012", ...],
        "first_seen": "ch01"
      },
      ...
    ],
    "stats": {
      "input_entities": 549, "output_clusters": 7,
      "unclustered_wrapped": 2, "total_items": 9, "reduction_pct": 60
    }
  }

Standalone test mode:
  python scripts/entity_clustering.py --test
  Runs on hardcoded entities simulating Le Jeu de l'Ange.

Algorithm:
  1. Token overlap with title stripping (subset matching)
  2. Jaro-Winkler on normalized names (orthographic variants, threshold 0.92)
  3. Union-Find for transitive closure (A~B and B~C → {A,B,C})

Safety rules:
  - Single given names (1 token, ≤8 chars) only cluster with longer names, never with each other
  - Title prefixes (M., Monsieur, inspecteur, etc.) are stripped before comparison
  - Accents are normalized for comparison but preserved in output
"""

import json
import sys
import unicodedata
from collections import defaultdict

# --- Configuration ---

TITLE_PREFIXES = frozenset({
    # French
    "m.", "mr.", "mrs.", "mme", "mme.", "mlle", "mlle.",
    "monsieur", "madame", "mademoiselle",
    "père", "frère", "sœur", "saint", "sainte",
    "inspecteur", "commissaire", "capitaine", "colonel", "général",
    "professeur", "maître", "docteur",
    # Spanish (for translated works)
    "don", "doña", "señor", "señora", "señorita",
    # Generic
    "dr.", "dr", "le", "la", "les", "el", "los", "las",
})

JW_THRESHOLD = 0.92  # Jaro-Winkler threshold for orthographic variant matching

# Gender-discriminating title sets (subset of TITLE_PREFIXES)
MASCULINE_TITLES = frozenset({"m.", "mr.", "monsieur", "señor", "don"})
FEMININE_TITLES = frozenset({"mme", "mme.", "madame", "señora", "doña"})


# --- String utilities ---

def normalize_for_comparison(text: str) -> str:
    """Lowercase + strip accents for comparison (not for display)."""
    text = text.lower().strip()
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def tokenize_name(name: str) -> list[str]:
    """Strip title prefixes and tokenize a name."""
    tokens = name.lower().strip().split()
    while tokens and tokens[0] in TITLE_PREFIXES:
        tokens = tokens[1:]
    return [t for t in tokens if t]


def extract_leading_titles(name: str) -> frozenset[str]:
    """Return the set of title prefixes at the START of a name (stops at first non-title)."""
    tokens = name.lower().strip().split()
    result = set()
    for t in tokens:
        if t in TITLE_PREFIXES:
            result.add(t)
        else:
            break
    return frozenset(result)


def has_conflicting_gender_title(name1: str, name2: str) -> bool:
    """Rule 1: block merge if one name has a feminine title and the other a masculine title."""
    t1 = extract_leading_titles(name1)
    t2 = extract_leading_titles(name2)
    masc1, fem1 = bool(t1 & MASCULINE_TITLES), bool(t1 & FEMININE_TITLES)
    masc2, fem2 = bool(t2 & MASCULINE_TITLES), bool(t2 & FEMININE_TITLES)
    return (masc1 and fem2) or (fem1 and masc2)


def is_single_given_name(tokens: list[str]) -> bool:
    """True if it's just a first name (1 short token). These are ambiguous."""
    return len(tokens) == 1 and len(tokens[0]) <= 8


def extract_surname_and_firstname(name: str) -> tuple[str, list[str]]:
    """
    Extract (surname, first_names) from a name after title stripping.
    Convention: last token = surname, all preceding tokens = first names.
    Returns normalized (lowercase, accent-stripped) tokens.
    """
    tokens = tokenize_name(name)
    if not tokens:
        return "", []
    normalized = [normalize_for_comparison(t) for t in tokens]
    if len(normalized) == 1:
        return normalized[0], []
    return normalized[-1], normalized[:-1]


# --- Similarity algorithms ---

def jaro_similarity(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    return (
        matches / len1 + matches / len2 + (matches - transpositions / 2) / matches
    ) / 3


def jaro_winkler(s1: str, s2: str, p: float = 0.1) -> float:
    jaro = jaro_similarity(s1, s2)
    prefix = sum(
        1 for i in range(min(4, len(s1), len(s2))) if s1[i] == s2[i]
    )
    return jaro + prefix * p * (1 - jaro)


# --- Matching rules ---

def should_cluster_tokens(name1: str, name2: str) -> bool:
    """Token-based matching: subset detection with title stripping."""
    t1 = tokenize_name(name1)
    t2 = tokenize_name(name2)
    if not t1 or not t2:
        return False

    s1, s2 = set(t1), set(t2)

    # Exact match after stripping titles
    if s1 == s2:
        return True

    # Subset match: one name is contained in the other
    if s1.issubset(s2) or s2.issubset(s1):
        # Safety: single given names don't match each other
        if is_single_given_name(t1) and is_single_given_name(t2):
            return False
        return True

    # Shared token when one side is simple (family name only)
    if s1 & s2 and (len(s1) == 1 or len(s2) == 1):
        if is_single_given_name(t1) and is_single_given_name(t2):
            return False
        return True

    return False


def should_cluster_jw(name1: str, name2: str) -> bool:
    """Jaro-Winkler on normalized full names (orthographic variants)."""
    t1 = tokenize_name(name1)
    t2 = tokenize_name(name2)
    # Same safety as token path: single given names don't match each other
    if is_single_given_name(t1) and is_single_given_name(t2):
        return False
    n1 = normalize_for_comparison(" ".join(t1))
    n2 = normalize_for_comparison(" ".join(t2))
    if not n1 or not n2:
        return False
    # Only match if names are roughly the same length (avoids "Mar" matching "Martín")
    if abs(len(n1) - len(n2)) > 3:
        return False
    return jaro_winkler(n1, n2) >= JW_THRESHOLD


def should_cluster(name1: str, name2: str) -> bool:
    """Combined matching with pre-filter rules for obvious wrong merges."""
    # Rule 1: conflicting gender titles → definitely different people
    if has_conflicting_gender_title(name1, name2):
        return False
    return should_cluster_tokens(name1, name2) or should_cluster_jw(name1, name2)


# --- Union-Find clustering ---

def build_clusters(entities: dict) -> tuple[list[dict], dict]:
    """
    Cluster entities by name similarity using Union-Find.
    Transitive closure: if A~B and B~C, then {A,B,C} are one cluster.

    Returns: (clusters_list, unclustered_entities)
    """
    parent = {eid: eid for eid in entities}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]  # path compression
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    # Compare all entity pairs via their mentions
    entity_ids = list(entities.keys())
    for i in range(len(entity_ids)):
        for j in range(i + 1, len(entity_ids)):
            ei, ej = entity_ids[i], entity_ids[j]
            # Only cluster same-type entities (PERSON with PERSON, PLACE with PLACE)
            if entities[ei].get("type") != entities[ej].get("type"):
                continue
            matched = False
            for mi in entities[ei]["raw_mentions"]:
                if matched:
                    break
                for mj in entities[ej]["raw_mentions"]:
                    if should_cluster(mi, mj):
                        union(ei, ej)
                        matched = True
                        break

    # Collect clusters
    raw_clusters = defaultdict(list)
    for eid in entity_ids:
        raw_clusters[find(eid)].append(eid)

    # Format output
    clusters_list = []
    unclustered = {}
    cluster_counter = 0

    for _root, members in sorted(raw_clusters.items(), key=lambda x: -len(x[1])):
        if len(members) == 1:
            # Single entity — unclustered
            eid = members[0]
            unclustered[eid] = entities[eid]
        else:
            cluster_counter += 1
            # Collect all mentions and find earliest first_seen
            all_mentions = []
            first_seen_chapters = []
            entity_type = entities[members[0]].get("type", "OTHER")
            total_mentions = 0

            for eid in members:
                all_mentions.extend(entities[eid]["raw_mentions"])
                fs = entities[eid].get("first_seen", "")
                if fs:
                    first_seen_chapters.append(fs)
                entity = entities[eid]
                total_mentions += entity.get(
                    "mention_count", len(entity.get("raw_mentions", []))
                )

            # Pick the mention with the most substantive tokens (after title stripping)
            # "David Martín" > "Monsieur Martín" (2 real tokens vs 1)
            def canonical_score(mention):
                tokens = tokenize_name(mention)
                return (len(tokens), len(" ".join(tokens)))

            canonical = max(all_mentions, key=canonical_score)

            clusters_list.append({
                "cluster_id": f"cluster_{cluster_counter:03d}",
                "type": entity_type,
                "canonical_candidate": canonical,
                "all_mentions": sorted(set(all_mentions), key=len, reverse=True),
                "entity_ids": members,
                "first_seen": min(first_seen_chapters) if first_seen_chapters else "",
                "entity_count": len(members),
                "total_mentions": total_mentions,
            })

    # Rule 2 post-processing: split clusters with conflicting first names
    clusters_list, unclustered = split_conflicting_first_names(clusters_list, unclustered, entities)
    clusters_list.sort(key=lambda c: c["total_mentions"], reverse=True)
    return clusters_list, unclustered


def _make_cluster(cluster_id: str, eids: list[str], entities: dict) -> dict:
    """Build a cluster dict from a list of entity IDs."""
    all_mentions = []
    first_seen_chapters = []
    total_mentions = 0
    entity_type = entities[eids[0]].get("type", "OTHER") if eids else "OTHER"

    for eid in eids:
        entity = entities[eid]
        all_mentions.extend(entity.get("raw_mentions", []))
        fs = entity.get("first_seen", "")
        if fs:
            first_seen_chapters.append(fs)
        total_mentions += entity.get("mention_count", len(entity.get("raw_mentions", [])))

    def canonical_score(mention):
        tokens = tokenize_name(mention)
        return (len(tokens), len(" ".join(tokens)))

    canonical = max(all_mentions, key=canonical_score) if all_mentions else eids[0]

    return {
        "cluster_id": cluster_id,
        "type": entity_type,
        "canonical_candidate": canonical,
        "all_mentions": sorted(set(all_mentions), key=len, reverse=True),
        "entity_ids": eids,
        "first_seen": min(first_seen_chapters) if first_seen_chapters else "",
        "entity_count": len(eids),
        "total_mentions": total_mentions,
    }


def split_conflicting_first_names(
    clusters: list[dict],
    unclustered: dict,
    entities: dict,
) -> tuple[list[dict], dict]:
    """
    Rule 2 post-processing: split clusters where multiple full-name entities
    share a surname but have incompatible first names, or where bare-surname
    entities have conflicting gender titles (e.g. Mme Vidal vs M. Vidal both
    transitively merged via bare "Vidal").

    Strategy:
    - For each multi-entity cluster, group full-name entities by (surname, first_name_set).
    - If there are 2+ distinct first-name groups for the same surname → split.
    - Bare-surname entities (no first name) with no gender title go into the most
      populated first-name group.
    - Bare-surname entities WITH gender titles are assigned to their gender group
      (feminine together, masculine together); if a cluster has mixed-gender
      bare-surname entities with no full-name disambiguator, they are split by gender.
    - If it's a tie, log a warning to stderr.
    - New sub-clusters get reassigned cluster_ids.
    """
    new_clusters = []
    cluster_counter = [0]

    def next_cluster_id() -> str:
        cluster_counter[0] += 1
        return f"cluster_{cluster_counter[0]:03d}"

    for cluster in clusters:
        if cluster["entity_count"] < 2:
            new_clusters.append(cluster)
            continue

        # Group entities: full-name (has first name) vs bare-surname (surname only)
        # For bare-surname entities, also track their gender from title prefix
        by_surname: dict[str, list[tuple[frozenset, str]]] = {}
        # bare_surname: list of (eid, gender_group) where gender_group is
        # "masc", "fem", or "neutral"
        bare_surname_eids: list[tuple[str, str]] = []

        for eid in cluster["entity_ids"]:
            mention = entities[eid]["raw_mentions"][0] if entities[eid].get("raw_mentions") else eid
            surname, firsts = extract_surname_and_firstname(mention)
            if not surname or not firsts:
                # Determine gender from title prefix
                titles = extract_leading_titles(mention)
                if titles & MASCULINE_TITLES:
                    gender = "masc"
                elif titles & FEMININE_TITLES:
                    gender = "fem"
                else:
                    gender = "neutral"
                bare_surname_eids.append((eid, gender))
                continue
            by_surname.setdefault(surname, []).append((frozenset(firsts), eid))

        # Check for conflict: same surname, 2+ distinct first-name groups
        split_happened = False
        for surname, entries in by_surname.items():
            distinct_groups: dict[frozenset, list[str]] = {}
            for firsts_set, eid in entries:
                distinct_groups.setdefault(firsts_set, []).append(eid)

            if len(distinct_groups) < 2:
                continue  # no conflict for this surname

            split_happened = True
            sorted_groups = sorted(distinct_groups.items(), key=lambda x: -len(x[1]))

            # Assign bare-surname entities to the largest first-name group
            if bare_surname_eids:
                if len(sorted_groups) >= 2 and len(sorted_groups[0][1]) == len(sorted_groups[1][1]):
                    print(
                        f"Warning: ambiguous bare-surname cluster for '{surname}' "
                        f"— cannot deterministically assign to first-name group, "
                        f"logging for LLM resolution",
                        file=sys.stderr,
                    )
                sorted_groups[0][1].extend(eid for eid, _gender in bare_surname_eids)

            for _firsts_set, eids in sorted_groups:
                new_clusters.append(_make_cluster(next_cluster_id(), eids, entities))

            break  # handle one surname conflict per cluster

        if not split_happened:
            # Check for gender conflict among bare-surname entities when no
            # full-name conflict was detected (e.g. "Mme Vidal" + "M. Vidal" +
            # "Vidal" all merged transitively).
            masc_eids = [eid for eid, g in bare_surname_eids if g == "masc"]
            fem_eids = [eid for eid, g in bare_surname_eids if g == "fem"]
            neutral_eids = [eid for eid, g in bare_surname_eids if g == "neutral"]
            full_name_eids = [eid for entries in by_surname.values() for _, eid in entries]

            if masc_eids and fem_eids:
                # Split by gender: masculine group gets full-name entities and neutrals
                # (best guess: a bare "Vidal" is more likely the main male character)
                masc_group = masc_eids + full_name_eids + neutral_eids
                fem_group = fem_eids
                split_happened = True
                new_clusters.append(_make_cluster(next_cluster_id(), masc_group, entities))
                new_clusters.append(_make_cluster(next_cluster_id(), fem_group, entities))
            else:
                # No conflict found — re-assign a fresh cluster_id for consistency
                new_clusters.append(_make_cluster(next_cluster_id(), cluster["entity_ids"], entities))

    return new_clusters, unclustered


# --- Test mode ---

TEST_ENTITIES = {
    "entity_001": {"type": "PERSON", "raw_mentions": ["Martín"], "first_seen": "ch01"},
    "entity_002": {"type": "PERSON", "raw_mentions": ["David Martín"], "first_seen": "ch01"},
    "entity_003": {"type": "PERSON", "raw_mentions": ["M. Martín"], "first_seen": "ch03"},
    "entity_004": {"type": "PERSON", "raw_mentions": ["Monsieur Martín"], "first_seen": "ch05"},
    "entity_005": {"type": "PERSON", "raw_mentions": ["David"], "first_seen": "ch02"},
    "entity_010": {"type": "PERSON", "raw_mentions": ["Sempere"], "first_seen": "ch02"},
    "entity_011": {"type": "PERSON", "raw_mentions": ["Sempere junior"], "first_seen": "ch04"},
    "entity_012": {"type": "PERSON", "raw_mentions": ["M. Sempere"], "first_seen": "ch03"},
    "entity_013": {"type": "PERSON", "raw_mentions": ["Daniel Sempere"], "first_seen": "ch06"},
    "entity_020": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
    "entity_021": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
    "entity_022": {"type": "PERSON", "raw_mentions": ["Monsieur Vidal"], "first_seen": "ch02"},
    "entity_030": {"type": "PERSON", "raw_mentions": ["Isabella"], "first_seen": "ch10"},
    "entity_031": {"type": "PERSON", "raw_mentions": ["Corelli"], "first_seen": "ch08"},
    "entity_032": {"type": "PERSON", "raw_mentions": ["Andreas Corelli"], "first_seen": "ch08"},
    "entity_040": {"type": "PLACE", "raw_mentions": ["Barcelona"], "first_seen": "ch01"},
    "entity_041": {"type": "PLACE", "raw_mentions": ["Barcelone"], "first_seen": "ch01"},
    "entity_050": {"type": "PERSON", "raw_mentions": ["Cristina"], "first_seen": "ch12"},
    "entity_051": {"type": "PERSON", "raw_mentions": ["Cristina Sagnier"], "first_seen": "ch12"},
    "entity_060": {"type": "PERSON", "raw_mentions": ["Grandes"], "first_seen": "ch15"},
    "entity_061": {"type": "PERSON", "raw_mentions": ["Víctor Grandes"], "first_seen": "ch15"},
    "entity_062": {"type": "PERSON", "raw_mentions": ["inspecteur Grandes"], "first_seen": "ch16"},
    # Noise that should stay unclustered
    "entity_070": {"type": "ORG", "raw_mentions": ["Intoxiqué"], "first_seen": "ch05"},
    "entity_071": {"type": "PERSON", "raw_mentions": ["Piquillo"], "first_seen": "ch09"},
}


def run_test_mode() -> None:
    print("Running entity clustering on test data...\n", file=sys.stderr)

    clusters, unclustered = build_clusters(TEST_ENTITIES)

    print("=== CLUSTERS ===\n")
    for c in clusters:
        print(
            f"  {c['cluster_id']} [{c['type']}] "
            f"({c['entity_count']} entités, first_seen={c['first_seen']}, total_mentions={c['total_mentions']})"
        )
        print(f"    canonical: {c['canonical_candidate']}")
        print(f"    mentions:  {c['all_mentions']}")
        print()

    print(f"=== UNCLUSTERED ({len(unclustered)}) ===\n")
    for eid, entity in unclustered.items():
        print(f"  [{eid}] {entity['raw_mentions']} ({entity['type']})")

    total = len(TEST_ENTITIES)
    output_count = len(clusters) + len(unclustered)
    print(f"\n=== STATS ===")
    print(f"  Input entities:    {total}")
    print(f"  Output clusters:   {len(clusters)}")
    print(f"  Unclustered:       {len(unclustered)}")
    print(f"  Total output:      {output_count}")
    print(f"  Reduction:         {100 - 100 * output_count // total}%")


# --- Studio pipeline interface ---

def run_live_mode() -> None:
    """Live mode: read the latest extraction-*.jsonl and run clustering on real data."""
    import glob

    jsonl_files = sorted(glob.glob("extraction-*.jsonl"), reverse=True)
    if not jsonl_files:
        print("No extraction-*.jsonl file found. Run make test-extraction first.", file=sys.stderr)
        sys.exit(1)

    latest = jsonl_files[0]
    print(f"Reading {latest}...\n", file=sys.stderr)

    entities = {}
    with open(latest, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            mention_count = sum(len(v) for v in e.get("mentions_by_chapter", {}).values())
            entities[e["id"]] = {
                "type": e["type"],
                "raw_mentions": e["raw_mentions"],
                "first_seen": e.get("first_seen", ""),
                "mention_count": mention_count or len(e.get("raw_mentions", [])),
            }

    clusters, unclustered = build_clusters(entities)
    all_clusters = sorted(clusters + [
        {
            "cluster_id": f"single_{eid}",
            "type": entity.get("type", "OTHER"),
            "canonical_candidate": entity["raw_mentions"][0] if entity.get("raw_mentions") else eid,
            "all_mentions": entity.get("raw_mentions", []),
            "entity_ids": [eid],
            "entity_count": 1,
            "first_seen": entity.get("first_seen", ""),
            "total_mentions": entity.get("mention_count", len(entity.get("raw_mentions", []))),
        }
        for eid, entity in unclustered.items()
    ], key=lambda c: c["total_mentions"], reverse=True)

    total = len(entities)
    output_count = len(all_clusters)
    multi = [c for c in all_clusters if c["entity_count"] > 1]

    print(f"=== LIVE CLUSTERING — {latest} ===\n")
    print(f"Top 20 clusters (multi-entités, par total_mentions) :\n")
    for c in multi[:20]:
        print(
            f"  {c['cluster_id']} [{c['type']}] "
            f"{c['entity_count']}→1  {c['total_mentions']} mentions  {c['canonical_candidate']}"
        )
        print(f"    {c['all_mentions']}")
        print()

    print(f"=== STATS ===")
    print(f"  Input entities:    {total}")
    print(f"  Multi-clusters:    {len(multi)}")
    print(f"  Unclustered:       {len(all_clusters) - len(multi)}")
    print(f"  Total output:      {output_count}")
    print(f"  Reduction:         {100 - 100 * output_count // total if total else 0}%")


def main() -> None:
    if "--test" in sys.argv:
        run_test_mode()
        return

    if "--live" in sys.argv:
        run_live_mode()
        return

    payload = json.load(sys.stdin)

    # Get entities from previous stage output
    prev_outputs = payload.get("previous_outputs", {})
    extraction_output = prev_outputs.get("entity-extraction", {})
    entities = extraction_output.get("entities_for_resolution", {})

    if not entities:
        json.dump({"error": "missing entities_for_resolution in previous stage output"}, sys.stdout)
        sys.exit(1)

    clusters, unclustered = build_clusters(entities)

    total = len(entities)

    single_clusters = [
        {
            "cluster_id": f"single_{eid}",
            "type": entity.get("type", "OTHER"),
            "canonical_candidate": entity["raw_mentions"][0] if entity.get("raw_mentions") else eid,
            "all_mentions": entity.get("raw_mentions", []),
            "entity_ids": [eid],
            "entity_count": 1,
            "first_seen": entity.get("first_seen", ""),
            "total_mentions": entity.get(
                "mention_count", len(entity.get("raw_mentions", []))
            ),
        }
        for eid, entity in unclustered.items()
    ]
    all_clusters = sorted(clusters + single_clusters, key=lambda c: c["total_mentions"], reverse=True)

    result = {
        "clusters": all_clusters,
        "stats": {
            "input_entities": total,
            "output_clusters": len(clusters),
            "unclustered_wrapped": len(unclustered),
            "total_items": len(all_clusters),
            "reduction_pct": 100 - 100 * len(all_clusters) // total if total > 0 else 0,
        },
    }

    if result["stats"]["reduction_pct"] == 0 and result["stats"]["input_entities"] > 10:
        print(
            f"Warning: reduction_pct=0 with {result['stats']['input_entities']} input entities — "
            "no clustering occurred, check clustering thresholds",
            file=sys.stderr,
        )

    json.dump(result, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
