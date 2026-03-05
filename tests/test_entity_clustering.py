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
    # "Martin" vs "Martín" — accent variant
    assert should_cluster_jw("Martin", "Martín") is True

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
