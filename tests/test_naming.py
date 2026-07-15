"""Tests for wiki_creator/naming.py — name-collision policy (STU-506)."""
import pytest

from wiki_creator.naming import (
    NamingPolicy,
    disambiguate_page_titles,
    naming_policy,
)


def test_defaults_are_the_safe_posture():
    p = naming_policy({})
    assert p.collision_policy == "disambiguate"
    assert p.merge_requires_same_type is True
    assert p.merges_cross_type is False
    assert p.fails_on_collision is False
    assert p.alias_arbitration == ("canonical_owner", "mention_count", "first_seen")


def test_reads_book_config():
    p = naming_policy(
        {
            "naming": {
                "collision_policy": "fail",
                "merge_requires_same_type": True,
                "disambiguator": {"template": "{name} [{type_label}]"},
                "alias_arbitration": {"order": ["mention_count", "first_seen"]},
            }
        }
    )
    assert p.collision_policy == "fail"
    assert p.fails_on_collision is True
    assert p.disambiguate("Adarlan", "Lieu") == "Adarlan [Lieu]"
    assert p.alias_arbitration == ("mention_count", "first_seen")


def test_merge_policy_folds_cross_type():
    assert naming_policy({"naming": {"collision_policy": "merge"}}).merges_cross_type is True
    assert NamingPolicy(merge_requires_same_type=False).merges_cross_type is True


def test_rejects_unknown_policy():
    with pytest.raises(ValueError, match="collision_policy"):
        naming_policy({"naming": {"collision_policy": "nope"}})


def test_rejects_unknown_arbitration_key():
    with pytest.raises(ValueError, match="alias_arbitration"):
        naming_policy({"naming": {"alias_arbitration": {"order": ["bogus"]}}})


def _pages():
    return [
        {"title": "Adarlan", "entity_type": "PERSON"},
        {"title": "Adarlan", "entity_type": "PLACE"},
        {"title": "Celaena", "entity_type": "PERSON"},
    ]


def test_disambiguate_rewrites_cross_type_collision():
    pages = _pages()
    rewrites = disambiguate_page_titles(
        pages, NamingPolicy(), {"PERSON": "Character", "PLACE": "Location"}
    )
    titles = {p["title"] for p in pages}
    assert titles == {"Adarlan (Character)", "Adarlan (Location)", "Celaena"}
    assert ("Adarlan", "Adarlan (Character)") in rewrites


def test_disambiguate_leaves_same_type_collision_alone():
    # Two PERSON 'Adarlan' pages: a real duplicate, not an ambiguity a type
    # label could resolve — left untouched (the validator surfaces it).
    pages = [{"title": "Adarlan", "entity_type": "PERSON"}] * 1 + [
        {"title": "Adarlan", "entity_type": "PERSON"}
    ]
    assert disambiguate_page_titles(pages, NamingPolicy()) == []


def test_disambiguate_falls_back_to_entity_type_label():
    pages = _pages()
    disambiguate_page_titles(pages, NamingPolicy(), type_labels=None)
    assert {p["title"] for p in pages} == {"Adarlan (PERSON)", "Adarlan (PLACE)", "Celaena"}


def test_disambiguate_noop_under_fail_and_merge():
    for policy in (NamingPolicy(collision_policy="fail"), NamingPolicy(collision_policy="merge")):
        pages = _pages()
        assert disambiguate_page_titles(pages, policy) == []
        assert [p["title"] for p in pages] == ["Adarlan", "Adarlan", "Celaena"]
