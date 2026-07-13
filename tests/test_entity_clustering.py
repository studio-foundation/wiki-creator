"""Tests for scripts/entity_clustering.py — deterministic entity clustering."""
import sys
import os

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
    extract_surname_and_firstname,
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
    # All three merge because the names resolve to one cluster; dominant type stays PLACE.
    place_cluster = next((c for c in clusters if "e040" in c["entity_ids"]), None)
    assert place_cluster is not None
    assert "e099" in place_cluster["entity_ids"]
    assert place_cluster["type"] == "PLACE"


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


def test_build_clusters_mixed_types_merge_when_names_match():
    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Arobynn"], "first_seen": "ch01", "mention_count": 2},
        "e002": {"type": "PLACE", "raw_mentions": ["Arobynn Hamel"], "first_seen": "ch01", "mention_count": 1},
    }

    clusters, unclustered = build_clusters(entities)

    assert not unclustered
    assert len(clusters) == 1
    assert set(clusters[0]["entity_ids"]) == {"e001", "e002"}


def test_build_clusters_mixed_type_uses_dominant_mention_weight():
    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Arobynn"], "first_seen": "ch01", "mention_count": 5},
        "e002": {"type": "PLACE", "raw_mentions": ["Arobynn Hamel"], "first_seen": "ch01", "mention_count": 1},
    }

    clusters, _ = build_clusters(entities)

    assert clusters[0]["type"] == "PERSON"


def test_build_clusters_mixed_type_tie_uses_fixed_precedence():
    entities = {
        "e001": {"type": "PLACE", "raw_mentions": ["Arobynn"], "first_seen": "ch01", "mention_count": 2},
        "e002": {"type": "PERSON", "raw_mentions": ["Arobynn Hamel"], "first_seen": "ch01", "mention_count": 2},
    }

    clusters, _ = build_clusters(entities)

    assert clusters[0]["type"] == "PERSON"


def test_build_clusters_place_not_absorbed_into_person_title():
    """STU-473: a PLACE toponym sitting in a person's title after a connector
    ('King of Adarlan') must NOT fold the PLACE entity into the PERSON.
    Contrast with a bare surname ('Arobynn Hamel', no connector) which still
    merges via test_build_clusters_mixed_type_tie_uses_fixed_precedence."""
    entities = {
        "e_king": {"type": "PERSON", "raw_mentions": ["King of Adarlan"], "first_seen": "ch01", "mention_count": 10},
        "e_place": {"type": "PLACE", "raw_mentions": ["Adarlan"], "first_seen": "ch01", "mention_count": 20},
    }
    clusters, unclustered = build_clusters(entities, language="en")

    def members_of(eid):
        for c in clusters:
            if eid in c["entity_ids"]:
                return frozenset(c["entity_ids"])
        return frozenset({eid})

    assert members_of("e_place") != members_of("e_king")
    assert "Adarlan" not in members_of("e_king")


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


# --- extract_surname_and_firstname ---

def test_extract_surname_and_firstname_full_name():
    surname, firsts = extract_surname_and_firstname("Cristina Sagnier")
    assert surname == "sagnier"
    assert firsts == ["cristina"]

def test_extract_surname_and_firstname_no_first():
    surname, firsts = extract_surname_and_firstname("Sagnier")
    assert surname == "sagnier"
    assert firsts == []

def test_extract_surname_and_firstname_with_title():
    # Title stripped before extraction
    surname, firsts = extract_surname_and_firstname("M. Sagnier")
    assert surname == "sagnier"
    assert firsts == []

def test_extract_surname_and_firstname_three_tokens():
    surname, firsts = extract_surname_and_firstname("A. C. Vidal")
    assert surname == "vidal"
    assert firsts == ["a.", "c."]


# --- build_clusters AC tests ---

def test_build_clusters_sagnier_family_separated():
    """AC1: Cristina Sagnier and Manuel Sagnier must be in SEPARATE clusters."""
    entities = {
        "e_cs": {"type": "PERSON", "raw_mentions": ["Cristina Sagnier"], "first_seen": "ch12"},
        "e_ms": {"type": "PERSON", "raw_mentions": ["Manuel Sagnier"], "first_seen": "ch05"},
        "e_s":  {"type": "PERSON", "raw_mentions": ["Sagnier"], "first_seen": "ch04"},
        "e_mlle": {"type": "PERSON", "raw_mentions": ["Mlle Cristina"], "first_seen": "ch13"},
    }
    clusters, unclustered = build_clusters(entities)

    def cluster_of(eid):
        for c in clusters:
            if eid in c["entity_ids"]:
                return c["cluster_id"]
        return None

    cs_cluster = cluster_of("e_cs")
    ms_cluster = cluster_of("e_ms")

    assert cs_cluster is not None, "Cristina Sagnier should be in a cluster"
    assert ms_cluster is not None, "Manuel Sagnier should be in a cluster"
    assert cs_cluster != ms_cluster, (
        f"Cristina Sagnier and Manuel Sagnier must be in different clusters, "
        f"but both are in {cs_cluster}"
    )


def test_build_clusters_mme_vidal_separated_from_m():
    """AC2: Mme Vidal must not be in the same cluster as M. Vidal."""
    entities = {
        "e_mme":   {"type": "PERSON", "raw_mentions": ["Mme Vidal"], "first_seen": "ch10"},
        "e_m":     {"type": "PERSON", "raw_mentions": ["M. Vidal"], "first_seen": "ch01"},
        "e_pedro": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
        "e_vidal": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
        "e_don":   {"type": "PERSON", "raw_mentions": ["Don Pedro"], "first_seen": "ch03"},
    }
    clusters, unclustered = build_clusters(entities)

    all_items = list(clusters) + [
        {"cluster_id": f"unc_{eid}", "entity_ids": [eid]}
        for eid in unclustered
    ]

    def cluster_of(eid):
        for c in all_items:
            if eid in c["entity_ids"]:
                return c["cluster_id"]
        return None

    mme_cluster = cluster_of("e_mme")
    m_cluster = cluster_of("e_m")

    assert mme_cluster != m_cluster, "Mme Vidal must not be with M. Vidal"


def test_build_clusters_pedro_vidal_aliases_stay_together():
    """AC3: Pedro Vidal, Don Pedro, Vidal, M. Vidal stay in one cluster (legitimate aliases)."""
    entities = {
        "e_pedro": {"type": "PERSON", "raw_mentions": ["Pedro Vidal"], "first_seen": "ch01"},
        "e_don":   {"type": "PERSON", "raw_mentions": ["Don Pedro"], "first_seen": "ch03"},
        "e_vidal": {"type": "PERSON", "raw_mentions": ["Vidal"], "first_seen": "ch01"},
        "e_m":     {"type": "PERSON", "raw_mentions": ["M. Vidal"], "first_seen": "ch02"},
    }
    clusters, unclustered = build_clusters(entities)
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}: {[c['entity_ids'] for c in clusters]}"
    assert set(clusters[0]["entity_ids"]) == {"e_pedro", "e_don", "e_vidal", "e_m"}


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


def test_cluster_jw_same_surname_different_firstname_blocked():
    # "Cristina Sagnier" vs "Manuel Sagnier": surname-driven match → should NOT cluster
    assert should_cluster_jw("Cristina Sagnier", "Manuel Sagnier") is False


def test_cluster_jw_same_full_name_variant_allowed():
    # Legitimate accent variant → should cluster
    assert should_cluster_jw("David Martín", "David Martin") is True


def test_cluster_jw_different_surname_not_blocked_by_rule3():
    # Different surname → normal JW, Rule 3 doesn't apply
    assert should_cluster_jw("Barcelona", "Barcelone") is True


def test_build_clusters_logs_warning_for_ambiguous_bare_surname(capsys):
    """AC5: When a bare-surname entity bridges two distinct first-name clusters of equal size,
    a warning is printed to stderr."""
    entities = {
        "e_cs": {"type": "PERSON", "raw_mentions": ["Cristina Sagnier"], "first_seen": "ch12"},
        "e_ms": {"type": "PERSON", "raw_mentions": ["Manuel Sagnier"], "first_seen": "ch05"},
        "e_s":  {"type": "PERSON", "raw_mentions": ["Sagnier"], "first_seen": "ch04"},
    }
    # Both first-name groups have 1 entity each (equal) → warning expected
    clusters, unclustered = build_clusters(entities)
    captured = capsys.readouterr()
    assert "ambiguous" in captured.err.lower() or "warning" in captured.err.lower(), (
        f"Expected an ambiguity warning in stderr. Got: {captured.err!r}"
    )


def test_captain_westfall_clusters_with_chaol_westfall():
    """STU-275: title-prefixed 'Captain Westfall' must cluster with 'Chaol Westfall'."""
    from scripts.entity_clustering import build_clusters

    entities = {
        "e1": {"type": "PERSON", "raw_mentions": ["Chaol Westfall"], "first_seen": "ch01"},
        "e2": {"type": "PERSON", "raw_mentions": ["Captain Westfall"], "first_seen": "ch02"},
        "e3": {"type": "PERSON", "raw_mentions": ["Westfall"], "first_seen": "ch03"},
    }
    clusters, unclustered = build_clusters(entities, language="en")
    assert len(clusters) == 1, f"Expected 1 cluster, got {len(clusters)}: {clusters}"
    assert len(unclustered) == 0
    mentions = set(clusters[0]["all_mentions"])
    assert "Captain Westfall" in mentions
    assert "Chaol Westfall" in mentions


def test_main_parses_live_book_flag(monkeypatch):
    """--live --book <yaml> is parsed and forwarded to run_live_mode."""
    import scripts.entity_clustering as clustering

    captured = {}

    def fake_run_live_mode(*, book_yaml=None):
        captured["book_yaml"] = book_yaml

    monkeypatch.setattr(clustering, "run_live_mode", fake_run_live_mode)
    monkeypatch.setattr(sys, "argv", ["entity_clustering.py", "--live", "--book", "library/foo/books/01.yaml"])

    clustering.main()

    assert captured["book_yaml"] == "library/foo/books/01.yaml"


# --- Series seeding (STU-485) ---

def _seed_registry():
    from wiki_creator.registry import Registry

    return Registry.from_dict({
        "version": 1,
        "entities": [
            {
                "entity_id": "eragon",
                "canonical_name": "Eragon",
                "entity_type": "PERSON",
                "aliases": ["Argetlam", "Eragon", "Shadeslayer"],
                "mentions": [],
                "decisions": ["d_a", "d_b"],
                "books": ["01-eragon"],
                "first_book": "01-eragon",
            }
        ],
        "decisions": [
            {
                "decision_id": "d_a",
                "strategy": "pattern",
                "inputs": ["eragon", "argetlam"],
                "evidence": "e",
                "confidence": "high",
                "reversible": True,
            },
            {
                "decision_id": "d_b",
                "strategy": "pattern",
                "inputs": ["eragon", "shadeslayer"],
                "evidence": "e",
                "confidence": "high",
                "reversible": True,
            },
        ],
        "warnings": [],
    })


def test_build_clusters_seed_unions_known_aliases():
    """Dissimilar names that are known aliases of one series entity cluster
    together in tome 2 — identity carried by the registry, not by similarity."""
    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Eragon"], "first_seen": "ch01"},
        "e002": {"type": "PERSON", "raw_mentions": ["Argetlam"], "first_seen": "ch04"},
        "e003": {"type": "PERSON", "raw_mentions": ["Shadeslayer"], "first_seen": "ch07"},
    }
    # Without seed: no similarity, nothing clusters.
    clusters, unclustered = build_clusters(entities)
    assert clusters == []

    seed = _seed_registry().seed_table()
    clusters, unclustered = build_clusters(entities, seed=seed)
    assert len(clusters) == 1
    assert set(clusters[0]["entity_ids"]) == {"e001", "e002", "e003"}


def test_build_clusters_seed_ignores_unknown_names():
    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Roran"], "first_seen": "ch01"},
        "e002": {"type": "PERSON", "raw_mentions": ["Katrina"], "first_seen": "ch02"},
    }
    clusters, unclustered = build_clusters(entities, seed=_seed_registry().seed_table())
    assert clusters == []
    assert set(unclustered.keys()) == {"e001", "e002"}


def test_main_seeds_from_series_registry(tmp_path):
    """End-to-end: file_path in additional_context + a series registry on disk
    pre-link known aliases in stdin mode."""
    import subprocess
    import json as _json
    import sys as _sys

    books = tmp_path / "library" / "author" / "series" / "books"
    books.mkdir(parents=True)
    book_yaml = books / "02-eldest.yaml"
    book_yaml.write_text("title: Eldest\n", encoding="utf-8")
    _seed_registry().save(tmp_path / "library" / "author" / "series" / "registry.json")

    entities = {
        "e001": {"type": "PERSON", "raw_mentions": ["Eragon"], "first_seen": "ch01", "mention_count": 4},
        "e002": {"type": "PERSON", "raw_mentions": ["Argetlam"], "first_seen": "ch04", "mention_count": 2},
    }
    payload = _json.dumps({
        "additional_context": f"file_path: {book_yaml}\n",
        "previous_outputs": {
            "entity-extraction": {"entities_for_resolution": entities}
        },
    })
    result = subprocess.run(
        [_sys.executable, "scripts/entity_clustering.py"],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, result.stderr
    assert "series seeding active" in result.stderr
    output = _json.loads(result.stdout)
    seeded = [c for c in output["clusters"] if c["entity_count"] > 1]
    assert len(seeded) == 1
    assert set(seeded[0]["entity_ids"]) == {"e001", "e002"}
