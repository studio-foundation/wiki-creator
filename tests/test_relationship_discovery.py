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
    fold_chunk_result,
    load_votes_cache,
    save_votes_cache,
    uncached_chunk_ids,
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


# --- votes cache is keyed on the roster (STU-556) ---------------------------


def test_votes_cache_roundtrips_for_same_roster_and_prompt(tmp_path):
    path = tmp_path / "votes.json"
    roster = ["Eragon", "Brom (also called: Neal)"]
    votes = {"ch1:0": [{"entity_a": "Eragon", "entity_b": "Brom"}]}
    save_votes_cache(path, roster, "p1", votes)
    assert load_votes_cache(path, roster, "p1") == votes


def test_votes_cache_busts_when_roster_changes(tmp_path):
    path = tmp_path / "votes.json"
    save_votes_cache(path, ["Eragon", "Brom"], "p1", {"ch1:0": [{"entity_a": "Eragon"}]})
    # An alias merge changed the roster without changing chunk ids — stale votes
    # for the old roster must not replay.
    assert load_votes_cache(path, ["Eragon"], "p1") == {}


def test_votes_cache_busts_when_prompt_changes(tmp_path):
    path = tmp_path / "votes.json"
    save_votes_cache(path, ["Eragon"], "p1", {"ch1:0": [{"entity_a": "Eragon"}]})
    # The discovery prompt was edited — votes made under the old prompt must re-run,
    # or a prompt iteration on a subset silently sees stale results (STU-560).
    assert load_votes_cache(path, ["Eragon"], "p2") == {}


def test_votes_cache_missing_file_is_empty(tmp_path):
    assert load_votes_cache(tmp_path / "absent.json", ["Eragon"], "p1") == {}


# --- fold_chunk_result: a transient failure is not a genuine empty vote -------


def test_fold_chunk_failure_returns_none_not_cached():
    # None in (subprocess timeout / missing CLI / unparseable output) → None out,
    # so the caller leaves the chunk uncached and a re-run retries it (STU-562).
    assert fold_chunk_result(None, {}, ROSTER, TYPES) is None


def test_fold_chunk_success_with_no_relations_returns_empty_list():
    # A successful call that found nothing returns [] — cached as a genuine 0,
    # distinct from the failure above.
    assert fold_chunk_result([], {}, ROSTER, TYPES) == []


def test_fold_chunk_canonicalizes_and_validates():
    raw = [{
        "entity_a": "the boy",  # alias → Eragon
        "entity_b": "Brom",
        "relationship_type": "mentor",
        "direction": "B→A",
        "evidence": "Brom taught the boy to fight.",
    }]
    kept = fold_chunk_result(raw, {"the boy": "Eragon"}, ROSTER, TYPES)
    assert kept == [{
        "entity_a": "Eragon",
        "entity_b": "Brom",
        "relationship_type": "mentor",
        "direction": "B→A",
        "evidence": "Brom taught the boy to fight.",
    }]


# --- uncached_chunk_ids: failed chunks are coverage the run never bought ------


def test_uncached_chunk_ids_flags_failed_chunks(tmp_path):
    chunks = [{"id": "c0"}, {"id": "c1"}, {"id": "c2"}, {"id": "c3"}]
    # c1 failed and stayed out; c2 genuinely evidenced no relation ([] is cached).
    cache = {"c0": [{"entity_a": "A"}], "c2": [], "c3": [{"entity_a": "B"}]}
    assert uncached_chunk_ids(chunks, cache) == ["c1"]


def test_uncached_chunk_ids_empty_when_all_cached():
    chunks = [{"id": "c0"}, {"id": "c1"}]
    assert uncached_chunk_ids(chunks, {"c0": [], "c1": []}) == []


def test_uncached_chunk_ids_preserves_chunk_order():
    chunks = [{"id": "c0"}, {"id": "c1"}, {"id": "c2"}]
    assert uncached_chunk_ids(chunks, {}) == ["c0", "c1", "c2"]
