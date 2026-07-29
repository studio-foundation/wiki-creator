from wiki_creator.infobox_relationships import (
    bucket_for_type,
    relationship_infobox_fields,
)


def _entity(relationships):
    for rel in relationships:
        rel.setdefault("cooccurrence_count", 2)
    return {"canonical_name": "Alice", "aliases": ["Ali"], "relationships": relationships}


def test_bucket_for_type_maps_and_omits():
    assert bucket_for_type("family") == "family"
    assert bucket_for_type("romance") == "romance"
    assert bucket_for_type("budding_attraction") == "romance"
    assert bucket_for_type("mentor") == "friends_allies"
    assert bucket_for_type("enemy") == "enemies"
    # Too weak / too specific for the infobox.
    assert bucket_for_type("acquaintance") is None
    assert bucket_for_type("employment") is None
    assert bucket_for_type("other") is None
    assert bucket_for_type(None) is None


def test_buckets_group_by_type():
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Alice", "entity_b": "Dinah", "relationship_type": "family"},
        {"entity_a": "Queen", "entity_b": "Alice", "relationship_type": "enemy"},
        {"entity_a": "Alice", "entity_b": "Hatter", "relationship_type": "friend"},
    ]))
    assert fields == {
        "family": "[[Dinah]]",
        "friends_allies": "[[Hatter]]",
        "enemies": "[[Queen]]",
    }


def test_acquaintance_and_untyped_omitted():
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Alice", "entity_b": "Mouse", "relationship_type": "acquaintance"},
        {"entity_a": "Alice", "entity_b": "Ghost", "relationship_type": None},
        {"entity_a": "Alice", "entity_b": "Nobody", "relationship_type": "null"},
    ]))
    assert fields == {}


def test_deceased_marker():
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Alice", "entity_b": "Sister", "relationship_type": "family",
         "other_deceased": True},
    ]))
    assert fields == {"family": "[[Sister]] †"}


def test_ordered_by_cooccurrence_then_name():
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Alice", "entity_b": "Low", "relationship_type": "friend",
         "cooccurrence_count": 2},
        {"entity_a": "Alice", "entity_b": "High", "relationship_type": "ally",
         "cooccurrence_count": 9},
        {"entity_a": "Alice", "entity_b": "Mid", "relationship_type": "mentor",
         "cooccurrence_count": 5},
    ]))
    assert fields["friends_allies"] == "[[High]], [[Mid]], [[Low]]"


def test_self_resolved_by_alias_and_deduped():
    # The entity appears as the alias on one side; the other party is the peer.
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Rabbit", "entity_b": "Ali", "relationship_type": "friend"},
        {"entity_a": "Alice", "entity_b": "Rabbit", "relationship_type": "ally"},
    ]))
    assert fields == {"friends_allies": "[[Rabbit]]"}


def test_legacy_french_type_resolves_to_bucket():
    # A pre-STU-477 artifact's French surface string still buckets via the enum's legacy map.
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Alice", "entity_b": "Chaol", "relationship_type": "amoureux"},
    ]))
    assert fields == {"romance": "[[Chaol]]"}


def test_single_cooccurrence_earns_no_infobox_slot():
    # Alice <-> Dodo: one chunk, one quote — an incidental adjacency, not an ally (STU-715).
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Alice", "entity_b": "Dodo", "relationship_type": "ally",
         "cooccurrence_count": 1},
    ]))
    assert fields == {}


def test_two_cooccurrences_earn_a_slot():
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Alice", "entity_b": "Dormouse", "relationship_type": "friend",
         "cooccurrence_count": 2},
    ]))
    assert fields == {"friends_allies": "[[Dormouse]]"}


def test_threshold_applies_per_bucket():
    # A weakly-supported enemy is dropped; a well-supported one survives.
    fields = relationship_infobox_fields(_entity([
        {"entity_a": "Alice", "entity_b": "Bill", "relationship_type": "enemy",
         "cooccurrence_count": 1},
        {"entity_a": "Alice", "entity_b": "Queen", "relationship_type": "enemy",
         "cooccurrence_count": 5},
    ]))
    assert fields == {"enemies": "[[Queen]]"}


def test_missing_cooccurrence_count_is_below_threshold():
    fields = relationship_infobox_fields({
        "canonical_name": "Alice", "aliases": [],
        "relationships": [{"entity_a": "Alice", "entity_b": "Dodo", "relationship_type": "ally"}],
    })
    assert fields == {}


def test_threshold_gates_regardless_of_confidence_grade():
    # confidence is null across the run (STU-700), so the support gate is the only
    # thing standing between an incidental adjacency and a hard infobox slot; it must
    # gate whether confidence is null or graded.
    for conf in (None, "interpretation", "explicit"):
        weak = relationship_infobox_fields(_entity([
            {"entity_a": "Alice", "entity_b": "Dodo", "relationship_type": "ally",
             "cooccurrence_count": 1, "confidence": conf},
        ]))
        assert weak == {}, conf
        strong = relationship_infobox_fields(_entity([
            {"entity_a": "Alice", "entity_b": "Queen", "relationship_type": "enemy",
             "cooccurrence_count": 5, "confidence": conf},
        ]))
        assert strong == {"enemies": "[[Queen]]"}, conf


_EN = {"generation": {"output_language": "en"}}


def test_sub_role_qualifier_uses_other_partys_role():
    # sub_role_a = what entity_a IS to entity_b, sub_role_b the converse. The
    # qualifier shown for the OTHER party is that party's own role (STU-665).
    child = {"canonical_name": "Harry", "aliases": [], "relationships": [
        {"entity_a": "James", "entity_b": "Harry", "relationship_type": "family",
         "sub_role_a": "father", "sub_role_b": "son", "other_deceased": True,
         "cooccurrence_count": 2},
    ]}
    parent = {"canonical_name": "James", "aliases": [], "relationships": [
        {"entity_a": "James", "entity_b": "Harry", "relationship_type": "family",
         "sub_role_a": "father", "sub_role_b": "son", "cooccurrence_count": 2},
    ]}
    assert relationship_infobox_fields(child, _EN) == {"family": "[[James]] (father) †"}
    assert relationship_infobox_fields(parent, _EN) == {"family": "[[Harry]] (son)"}


def test_sub_role_localized_label():
    child = {"canonical_name": "Harry", "aliases": [], "relationships": [
        {"entity_a": "James", "entity_b": "Harry", "relationship_type": "family",
         "sub_role_a": "father", "sub_role_b": "son", "cooccurrence_count": 2},
    ]}
    assert relationship_infobox_fields(child) == {"family": "[[James]] (père)"}


def test_symmetric_sub_role_shown_both_sides():
    a = {"canonical_name": "Alice", "aliases": [], "relationships": [
        {"entity_a": "Alice", "entity_b": "Bob", "relationship_type": "romance",
         "sub_role_a": "partner", "sub_role_b": "partner", "cooccurrence_count": 2},
    ]}
    assert relationship_infobox_fields(a, _EN) == {"romance": "[[Bob]] (partner)"}


def test_missing_sub_role_falls_back_to_bare_link():
    a = {"canonical_name": "Alice", "aliases": [], "relationships": [
        {"entity_a": "Alice", "entity_b": "Bob", "relationship_type": "family",
         "cooccurrence_count": 2},
    ]}
    assert relationship_infobox_fields(a, _EN) == {"family": "[[Bob]]"}
