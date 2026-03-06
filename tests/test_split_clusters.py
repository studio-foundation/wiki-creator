"""Tests for scripts/split_clusters.py."""
import sys, os, json, subprocess
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.split_clusters import split_clusters


MULTI_PERSON = {
    "cluster_id": "cluster_001", "type": "PERSON", "entity_count": 3,
    "canonical_candidate": "David Martín",
    "all_mentions": ["David Martín", "M. Martín", "Martín"],
    "entity_ids": ["e001", "e002", "e003"],
    "first_seen": "ch01", "total_mentions": 50,
}
MULTI_PLACE = {
    "cluster_id": "cluster_002", "type": "PLACE", "entity_count": 2,
    "canonical_candidate": "Barcelone",
    "all_mentions": ["Barcelone", "Barcelona"],
    "entity_ids": ["e040", "e041"],
    "first_seen": "ch01", "total_mentions": 30,
}
SINGLE_PERSON = {
    "cluster_id": "single_e010", "type": "PERSON", "entity_count": 1,
    "canonical_candidate": "Piquillo",
    "all_mentions": ["Piquillo"],
    "entity_ids": ["e010"],
    "first_seen": "ch09", "total_mentions": 2,
}
SINGLE_ORG = {
    "cluster_id": "single_e020", "type": "ORG", "entity_count": 1,
    "canonical_candidate": "Lumière",
    "all_mentions": ["Lumière"],
    "entity_ids": ["e020"],
    "first_seen": "ch05", "total_mentions": 1,
}


def test_multi_clusters_routed_by_type():
    result = split_clusters([MULTI_PERSON, MULTI_PLACE, SINGLE_PERSON, SINGLE_ORG])
    assert result["PERSON"] == [MULTI_PERSON]
    assert result["PLACE"] == [MULTI_PLACE]
    assert result["ORG"] == []


def test_singles_pre_resolved():
    result = split_clusters([MULTI_PERSON, SINGLE_PERSON, SINGLE_ORG])
    singles = result["singles_resolved"]
    assert len(singles) == 2
    ids = {s["source_ids"][0] for s in singles}
    assert ids == {"e010", "e020"}


def test_single_resolved_shape():
    result = split_clusters([SINGLE_PERSON])
    s = result["singles_resolved"][0]
    assert s["canonical_name"] == "Piquillo"
    assert s["type"] == "PERSON"
    assert s["aliases"] == ["Piquillo"]
    assert s["source_ids"] == ["e010"]
    assert s["relevant"] is True


def test_multi_clusters_not_in_singles():
    result = split_clusters([MULTI_PERSON, SINGLE_PERSON])
    single_ids = [s["source_ids"][0] for s in result["singles_resolved"]]
    assert "e001" not in single_ids
    assert "e002" not in single_ids


def test_all_types_present_in_output():
    result = split_clusters([])
    for t in ("PERSON", "PLACE", "ORG", "EVENT", "OTHER"):
        assert t in result
        assert isinstance(result[t], list)
    assert "singles_resolved" in result


def test_stats_counts():
    result = split_clusters([MULTI_PERSON, MULTI_PLACE, SINGLE_PERSON, SINGLE_ORG])
    assert result["stats"]["singles"] == 2
    assert result["stats"]["multi_PERSON"] == 1
    assert result["stats"]["multi_PLACE"] == 1


def test_unknown_type_routed_to_other():
    unknown_cluster = {
        "cluster_id": "cluster_999", "type": "CREATURE", "entity_count": 2,
        "canonical_candidate": "Dragon",
        "all_mentions": ["Dragon", "Le Dragon"],
        "entity_ids": ["e099", "e100"],
        "first_seen": "ch01", "total_mentions": 5,
    }
    result = split_clusters([unknown_cluster])
    assert result["OTHER"] == [unknown_cluster]
    assert "CREATURE" not in result


def test_studio_interface():
    """Integration: Studio stdin/stdout contract."""
    payload = json.dumps({
        "previous_outputs": {
            "entity-clustering": {
                "clusters": [MULTI_PERSON, SINGLE_PERSON]
            }
        }
    })
    result = subprocess.run(
        [sys.executable, "scripts/split_clusters.py"],
        input=payload, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "singles_resolved" in out
    assert "PERSON" in out
