"""STU-556: schema-guided relation discovery — pure chunking + book-level fold.

Ported from research/relation-eval (chunks_of + aggregate.py). These are the
deterministic halves of the discovery stage: split a chapter into
paragraph-aligned chunks, and fold the per-chunk votes into one book-level
typed pair. No LLM here.
"""
from wiki_creator.relationship_discovery import (
    aggregate,
    build_roster,
    canonicalize_relations,
    chunk_chapters,
    flip,
    valid_relations,
)

ROSTER = {"Eragon", "Brom", "Saphira", "Murtagh"}
TYPES = {"mentor", "friend", "family", "wary_alliance"}


# --- chunk_chapters ---------------------------------------------------------


def test_chunk_splits_on_paragraph_breaks_under_size():
    chapters = [{"id": "ch1", "title": "One", "text": "a\n\nb\n\nc"}]
    chunks = chunk_chapters(chapters, size=3)
    # "a" then "b" exceeds size (1 + 1 + 1 sep) — packing stops before overflow
    assert [c["text"] for c in chunks] == ["a\n\nb", "c"]


def test_chunk_ids_are_chapter_scoped_and_ordered():
    chapters = [{"id": "ch1", "title": "One", "text": "aaaa\n\nbbbb"}]
    chunks = chunk_chapters(chapters, size=4)
    assert [c["id"] for c in chunks] == ["ch1:0", "ch1:1"]
    assert all(c["chapter_id"] == "ch1" and c["title"] == "One" for c in chunks)


def test_chunk_spans_multiple_chapters_in_order():
    chapters = [
        {"id": "ch1", "title": "One", "text": "x"},
        {"id": "ch2", "title": "Two", "text": "y"},
    ]
    chunks = chunk_chapters(chapters, size=6000)
    assert [c["id"] for c in chunks] == ["ch1:0", "ch2:0"]


# --- valid_relations --------------------------------------------------------


def test_valid_relations_drops_off_roster_name():
    raw = [{"entity_a": "Eragon", "entity_b": "Nobody",
            "relationship_type": "friend", "direction": "symétrique"}]
    kept, rejected = valid_relations(raw, ROSTER, TYPES)
    assert kept == []
    assert rejected and "Nobody" in rejected[0]


def test_valid_relations_drops_self_pair():
    raw = [{"entity_a": "Eragon", "entity_b": "Eragon",
            "relationship_type": "friend", "direction": "symétrique"}]
    kept, rejected = valid_relations(raw, ROSTER, TYPES)
    assert kept == []


def test_valid_relations_drops_off_vocabulary_type():
    raw = [{"entity_a": "Eragon", "entity_b": "Brom",
            "relationship_type": "nemesis", "direction": "symétrique"}]
    kept, rejected = valid_relations(raw, ROSTER, TYPES)
    assert kept == []


def test_valid_relations_truncates_evidence():
    raw = [{"entity_a": "Eragon", "entity_b": "Brom",
            "relationship_type": "mentor", "direction": "B→A",
            "evidence": "x" * 500}]
    kept, _ = valid_relations(raw, ROSTER, TYPES)
    assert len(kept[0]["evidence"]) == 200


# --- flip -------------------------------------------------------------------


def test_flip_inverts_asymmetric_direction():
    assert flip("A→B") == "B→A"
    assert flip("B→A") == "A→B"
    assert flip("symétrique") == "symétrique"


# --- aggregate --------------------------------------------------------------


def _vote(chapter_id, a, b, rtype, direction="symétrique", evidence="ev"):
    return {"chapter_id": chapter_id, "relations": [
        {"entity_a": a, "entity_b": b, "relationship_type": rtype,
         "direction": direction, "evidence": evidence}]}


def test_aggregate_primary_type_is_most_common():
    votes = [
        _vote("ch1", "Eragon", "Murtagh", "wary_alliance"),
        _vote("ch2", "Eragon", "Murtagh", "wary_alliance"),
        _vote("ch3", "Eragon", "Murtagh", "friend"),
    ]
    pairs = aggregate(votes, ROSTER)
    assert len(pairs) == 1
    assert pairs[0]["relationship_type"] == "wary_alliance"


def test_aggregate_flips_direction_to_sorted_key():
    # pair_key sorts to (Brom, Eragon). A vote naming (Eragon, Brom) as A→B means
    # Eragon over Brom; restated against the sorted key that is B→A.
    votes = [_vote("ch1", "Eragon", "Brom", "mentor", direction="A→B")]
    pairs = aggregate(votes, ROSTER)
    assert (pairs[0]["entity_a"], pairs[0]["entity_b"]) == ("Brom", "Eragon")
    assert pairs[0]["direction"] == "B→A"


def test_aggregate_unions_chapters_and_counts_votes():
    votes = [
        _vote("ch1", "Eragon", "Saphira", "family"),
        _vote("ch1", "Eragon", "Saphira", "family"),
        _vote("ch3", "Eragon", "Saphira", "family"),
    ]
    pairs = aggregate(votes, ROSTER)
    assert pairs[0]["chapters"] == ["ch1", "ch3"]
    assert pairs[0]["cooccurrence_count"] == 3


def test_aggregate_caps_sample_contexts_at_three():
    votes = [_vote(f"ch{i}", "Eragon", "Brom", "mentor", evidence=f"ev{i}")
             for i in range(5)]
    pairs = aggregate(votes, ROSTER)
    assert len(pairs[0]["sample_contexts"]) == 3


# --- build_roster -----------------------------------------------------------


def test_build_roster_keeps_only_persons():
    entities = [
        {"canonical_name": "Eragon", "entity_type": "PERSON", "aliases": ["Eragon"]},
        {"canonical_name": "Alagaësia", "entity_type": "PLACE", "aliases": []},
    ]
    names, _, _ = build_roster(entities)
    assert names == {"Eragon"}


def test_build_roster_maps_aliases_to_canonical():
    entities = [{"canonical_name": "Brom", "entity_type": "PERSON",
                 "aliases": ["Brom", "Neal", "the old man"]}]
    _, alias_to_canonical, _ = build_roster(entities)
    assert alias_to_canonical["Neal"] == "Brom"
    assert alias_to_canonical["the old man"] == "Brom"
    assert alias_to_canonical["Brom"] == "Brom"


def test_build_roster_prompt_line_lists_aliases():
    entities = [{"canonical_name": "Brom", "entity_type": "PERSON",
                 "aliases": ["Brom", "Neal"]}]
    _, _, lines = build_roster(entities)
    assert lines == ["Brom (also called: Neal)"]


def test_build_roster_prompt_line_bare_when_no_alias():
    entities = [{"canonical_name": "Eragon", "entity_type": "PERSON",
                 "aliases": ["Eragon"]}]
    _, _, lines = build_roster(entities)
    assert lines == ["Eragon"]


# --- canonicalize_relations -------------------------------------------------


def test_canonicalize_maps_surface_form_to_canonical():
    raw = [{"entity_a": "Neal", "entity_b": "Eragon",
            "relationship_type": "mentor", "direction": "A→B"}]
    alias_to_canonical = {"Neal": "Brom", "Brom": "Brom", "Eragon": "Eragon"}
    out = canonicalize_relations(raw, alias_to_canonical)
    assert out[0]["entity_a"] == "Brom"
    assert out[0]["entity_b"] == "Eragon"


def test_canonicalize_leaves_unknown_name_untouched():
    raw = [{"entity_a": "Ghost", "entity_b": "Eragon",
            "relationship_type": "friend", "direction": "symétrique"}]
    out = canonicalize_relations(raw, {"Eragon": "Eragon"})
    assert out[0]["entity_a"] == "Ghost"  # dropped later by valid_relations


def test_aggregate_orders_pairs_by_chapter_breadth():
    votes = [
        _vote("ch1", "Eragon", "Brom", "mentor"),
        _vote("ch1", "Eragon", "Saphira", "family"),
        _vote("ch2", "Eragon", "Saphira", "family"),
    ]
    pairs = aggregate(votes, ROSTER)
    # Saphira pair spans 2 chapters, Brom pair 1 → Saphira first.
    assert (pairs[0]["entity_a"], pairs[0]["entity_b"]) == ("Eragon", "Saphira")
