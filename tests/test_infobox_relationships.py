from wiki_creator.infobox_relationships import (
    bucket_for_type,
    relationship_infobox_fields,
)


def _entity(relationships):
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
         "cooccurrence_count": 1},
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
