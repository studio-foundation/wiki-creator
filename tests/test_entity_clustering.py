"""Tests for scripts/entity_clustering.py — deterministic entity clustering."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.entity_clustering import (
    normalize_for_comparison,
    tokenize_name,
    is_single_given_name,
    should_cluster_tokens,
    should_cluster_jw,
    should_cluster,
    build_clusters,
    extract_leading_titles,
    has_conflicting_gender_title,
)


# --- normalize_for_comparison ---

def test_normalize_strips_accents():
    assert normalize_for_comparison("Martín") == "martin"

def test_normalize_lowercases():
    assert normalize_for_comparison("BARCELONE") == "barcelone"

def test_normalize_strips_leading_trailing_spaces():
    assert normalize_for_comparison("  Vidal  ") == "vidal"


# --- tokenize_name ---

def test_tokenize_strips_monsieur():
    assert tokenize_name("Monsieur Martín") == ["martín"]

def test_tokenize_strips_inspecteur():
    assert tokenize_name("inspecteur Grandes") == ["grandes"]

def test_tokenize_strips_don():
    assert tokenize_name("Don Quijote") == ["quijote"]

def test_tokenize_keeps_full_name():
    assert tokenize_name("David Martín") == ["david", "martín"]

def test_tokenize_empty_after_strip():
    # If only a title remains, should return empty list
    assert tokenize_name("M.") == []


# --- is_single_given_name ---

def test_is_single_given_name_true():
    assert is_single_given_name(["David"]) is True

def test_is_single_given_name_false_two_tokens():
    assert is_single_given_name(["David", "Martín"]) is False

def test_is_single_given_name_false_long_token():
    # 9 chars — above threshold
    assert is_single_given_name(["Alejandro"]) is False


# --- should_cluster_tokens ---

def test_cluster_tokens_subset_match():
    # "Martín" ⊂ "David Martín"
    assert should_cluster_tokens("Martín", "David Martín") is True

def test_cluster_tokens_title_stripped():
    # "M. Martín" → ["martín"], "David Martín" → ["david", "martín"] → subset
    assert should_cluster_tokens("M. Martín", "David Martín") is True

def test_cluster_tokens_two_single_names_dont_match():
    # "David" and "Pedro" — both single given names, should NOT match
    assert should_cluster_tokens("David", "Pedro") is False

def test_cluster_tokens_single_name_matches_longer():
    # "Vidal" (family name, 1 token) matches "Pedro Vidal"
    assert should_cluster_tokens("Vidal", "Pedro Vidal") is True

def test_cluster_tokens_no_match():
    assert should_cluster_tokens("Corelli", "Sempere") is False


# --- should_cluster_jw ---

def test_cluster_jw_barcelona_barcelone():
    # Orthographic variant (French/Spanish)
    assert should_cluster_jw("Barcelona", "Barcelone") is True

def test_cluster_jw_martin_accent():
    # "Martin" vs "Martín" are both single given names — guard blocks them from matching
    assert should_cluster_jw("Martin", "Martín") is False
    # Multi-token names with accent difference should still match
    assert should_cluster_jw("David Martin", "David Martín") is True

def test_cluster_jw_different_names():
    # Clearly different names should not match
    assert should_cluster_jw("Vidal", "Sempere") is False

def test_cluster_jw_length_guard():
    # Length diff > 3 chars → reject regardless of similarity
    assert should_cluster_jw("Mar", "Martín") is False


# --- build_clusters end-to-end ---

def test_build_clusters_martin_family():
    """Five Martín variants must end up in one cluster."""
    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Martín"], "first_seen": "ch01"},
        "e002": {"type": "PERSON", "raw_mentions": ["David Martín"], "first_seen": "ch01"},
        "e003": {"type": "PERSON", "raw_mentions": ["M. Martín"], "first_seen": "ch03"},
        "e004": {"type": "PERSON", "raw_mentions": ["Monsieur Martín"], "first_seen": "ch05"},
        "e005": {"type": "PERSON", "raw_mentions": ["David"], "first_seen": "ch02"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}: {clusters}"
    assert set(clusters[0]["entity_ids"]) == {"e001", "e002", "e003", "e004", "e005"}


def test_build_clusters_sempere_all_in_one():
    """All Sempere variants (grand-père, père, Daniel) must be in one cluster for LLM to split."""
    entities = {
        "e010": {"type": "PERSON", "raw_mentions": ["Sempere"], "first_seen": "ch02"},
        "e011": {"type": "PERSON", "raw_mentions": ["Sempere junior"], "first_seen": "ch04"},
        "e012": {"type": "PERSON", "raw_mentions": ["M. Sempere"], "first_seen": "ch03"},
        "e013": {"type": "PERSON", "raw_mentions": ["Daniel Sempere"], "first_seen": "ch06"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}"
    assert set(clusters[0]["entity_ids"]) == {"e010", "e011", "e012", "e013"}


def test_build_clusters_different_types_dont_merge():
    """PERSON and PLACE with same name should NOT be clustered together."""
    entities = {
        "e040": {"type": "PLACE", "raw_mentions": ["Barcelona"], "first_seen": "ch01"},
        "e041": {"type": "PLACE", "raw_mentions": ["Barcelone"], "first_seen": "ch01"},
        "e099": {"type": "PERSON", "raw_mentions": ["Barcelona"], "first_seen": "ch01"},
    }
    clusters, unclustered = build_clusters(entities)
    # e040 and e041 cluster together (PLACE), e099 stays alone (PERSON)
    place_cluster = next((c for c in clusters if "e040" in c["entity_ids"]), None)
    assert place_cluster is not None
    assert "e099" not in place_cluster["entity_ids"]


def test_build_clusters_unclustered_stays_alone():
    """Unique names with no similar counterpart stay unclustered."""
    entities = {
        "e071": {"type": "PERSON", "raw_mentions": ["Piquillo"], "first_seen": "ch09"},
        "e072": {"type": "PERSON", "raw_mentions": ["Zubiri"], "first_seen": "ch14"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 0
    assert set(unclustered.keys()) == {"e071", "e072"}


def test_build_clusters_transitive_closure():
    """A~B and B~C must result in {A,B,C} in one cluster (Union-Find)."""
    entities = {
        "eA": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
        "eB": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
        "eC": {"type": "PERSON", "raw_mentions": ["Monsieur Vidal"], "first_seen": "ch02"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 1
    assert set(clusters[0]["entity_ids"]) == {"eA", "eB", "eC"}


def test_build_clusters_canonical_picks_most_complete():
    """canonical_candidate should be the most token-rich name after title stripping."""
    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
        "e002": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
        "e003": {"type": "PERSON", "raw_mentions": ["Monsieur Vidal"], "first_seen": "ch02"},
    }
    clusters, _ = build_clusters(entities)
    assert clusters[0]["canonical_candidate"] == "Pedro Vidal"


# --- extract_leading_titles ---

def test_extract_leading_titles_mme():
    assert "mme" in extract_leading_titles("Mme Vidal")

def test_extract_leading_titles_monsieur():
    assert "monsieur" in extract_leading_titles("Monsieur Vidal")

def test_extract_leading_titles_no_title():
    assert extract_leading_titles("Pedro Vidal") == frozenset()

def test_extract_leading_titles_stops_at_first_non_title():
    assert extract_leading_titles("M. Vidal") == frozenset({"m."})


# --- has_conflicting_gender_title ---

def test_gender_conflict_mme_vs_m():
    assert has_conflicting_gender_title("Mme Vidal", "M. Vidal") is True

def test_gender_conflict_madame_vs_monsieur():
    assert has_conflicting_gender_title("Madame Dupont", "Monsieur Dupont") is True

def test_gender_conflict_senora_vs_senor():
    assert has_conflicting_gender_title("Señora Ramos", "Señor Ramos") is True

def test_gender_conflict_reversed():
    assert has_conflicting_gender_title("M. Vidal", "Mme Vidal") is True

def test_no_gender_conflict_same_title():
    assert has_conflicting_gender_title("Mme Vidal", "Mme Dupont") is False

def test_no_gender_conflict_no_title():
    assert has_conflicting_gender_title("Pedro Vidal", "Vidal") is False

def test_no_gender_conflict_mme_vs_no_title():
    assert has_conflicting_gender_title("Mme Vidal", "Pedro Vidal") is False


# --- should_cluster with Rule 1 ---

def test_should_cluster_blocks_mme_vs_m():
    assert should_cluster("Mme Vidal", "M. Vidal") is False

def test_should_cluster_blocks_madame_vs_monsieur():
    assert should_cluster("Madame Vidal", "Monsieur Vidal") is False

def test_should_cluster_allows_mme_variants():
    assert should_cluster("Mme Vidal", "Mme de Vidal") is True


def test_main_warns_when_no_reduction_and_many_entities():
    """main() must print a stderr warning when reduction_pct==0 with >10 input entities."""
    import subprocess
    import json as _json
    import sys

    # 11 completely unique entities — nothing will cluster
    # Names are deliberately dissimilar (different lengths, no shared prefix)
    # so Jaro-Winkler and token overlap both fail to group them
    distinct_names = [
        "Aardvark", "Benzene", "Calypso", "Driftwood", "Eggnog",
        "Fjord", "Guacamole", "Harpoon", "Igloo", "Jabiru", "Kestrel",
    ]
    entities = {
        f"entity_{i:03d}": {
            "type": "PERSON",
            "raw_mentions": [distinct_names[i - 1]],
            "first_seen": f"ch{i:02d}",
            "mention_count": 1,
        }
        for i in range(1, 12)  # 11 entities
    }
    payload = _json.dumps({
        "additional_context": "",
        "previous_outputs": {
            "entity-extraction": {
                "entities_for_resolution": entities,
            }
        },
    })
    result = subprocess.run(
        [sys.executable, "scripts/entity_clustering.py"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr={result.stderr}"
    assert "reduction_pct=0" in result.stderr, (
        f"Expected reduction_pct warning in stderr. Got: {result.stderr!r}"
    )
