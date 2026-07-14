from wiki_creator.relationship_types import usable_relationship_type


def test_real_type_passes_through_stripped():
    assert usable_relationship_type("  amoureux  ") == "amoureux"


def test_none_is_untyped():
    assert usable_relationship_type(None) is None


def test_empty_string_is_untyped():
    assert usable_relationship_type("   ") is None


def test_null_sentinel_string_is_untyped():
    # STU-501: the classifier can emit the JSON sentinel as a literal string.
    assert usable_relationship_type("null") is None
    assert usable_relationship_type("NULL") is None
    assert usable_relationship_type("None") is None
