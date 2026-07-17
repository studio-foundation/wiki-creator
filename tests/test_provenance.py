"""STU-491: chapter provenance on generated content."""

from wiki_creator.chapters import chapter_number
from wiki_creator.provenance import (
    content_units,
    relation_revealed_at,
    section_revealed_at,
)


class TestChapterNumber:
    def test_normalizes_every_key_form(self):
        assert chapter_number("C25.xhtml") == 25
        assert chapter_number("chapter_0") == 0
        assert chapter_number("ch01") == 1
        assert chapter_number("Chapter 25") == 25
        assert chapter_number("Ch12: something") == 12
        assert chapter_number(7) == 7

    def test_no_number_is_none(self):
        assert chapter_number("Prologue") is None
        assert chapter_number("") is None
        assert chapter_number(None) is None


def test_relation_revealed_at_is_first_appearance():
    assert relation_revealed_at({"chapters": [3, 1, 5]}) == 1
    assert relation_revealed_at({"chapters": []}) is None
    assert relation_revealed_at({}) is None


class TestSectionRevealedAt:
    def _entity(self):
        return {
            "relationships": [{"chapters": [3, 1]}, {"chapters": [5]}],
            "entity_events": [{"chapter": 4}, {"chapter": 2}],
            "context_chapters": [2, 6],
            "chapter_summary_context": [{"revealed_at_chapter": 2}],
        }

    def test_relationships_use_first_appearance(self):
        assert section_revealed_at("relationships", self._entity()) == 1

    def test_narrative_role_uses_events(self):
        assert section_revealed_at("narrative_role", self._entity()) == 2

    def test_backstory_uses_first_flashback_chapter(self):
        entity = {
            "chapter_summary_context": [
                {"revealed_at_chapter": 2, "temporal_context": "present"},
                {"revealed_at_chapter": 8, "temporal_context": "flashback"},
                {"revealed_at_chapter": 5, "temporal_context": "flashback"},
            ],
        }
        assert section_revealed_at("backstory", entity) == 5

    def test_backstory_none_without_flashback(self):
        entity = {"chapter_summary_context": [{"revealed_at_chapter": 2, "temporal_context": "present"}]}
        assert section_revealed_at("backstory", entity) is None

    def test_prose_section_uses_context_and_summaries(self):
        assert section_revealed_at("biography", self._entity()) == 2

    def test_missing_data_is_none(self):
        assert section_revealed_at("biography", {}) is None
        assert section_revealed_at("relationships", {}) is None


def test_content_units_skips_infobox_and_references():
    entity = {"context_chapters": [2]}
    units = content_units(["infobox", "biography", "references"], entity)
    assert units == [{"section": "biography", "revealed_at_chapter": 2}]


from wiki_creator.provenance import relation_units


def _rel_entity():
    return {
        "canonical_name": "Chaol",
        "aliases": ["Captain Westfall"],
        "relationships": [
            {"entity_a": "Chaol", "entity_b": "Celaena",
             "relationship_type": "amoureux", "chapters": [1, 55]},
            {"entity_a": "Cain", "entity_b": "Captain Westfall",
             "relationship_type": "antagoniste", "chapters": [7]},
            {"entity_a": "Chaol", "entity_b": "Dorian",
             "relationship_type": None, "chapters": [2]},
            {"entity_a": "Chaol", "entity_b": "Nox",
             "relationship_type": "ami", "chapters": []},
        ],
    }


def test_relation_units_uses_max_chapter_and_other_name():
    units = relation_units(_rel_entity())
    assert units == [
        {"name": "Celaena", "revealed_at_chapter": 55},
        {"name": "Cain", "revealed_at_chapter": 7},
    ]


def test_relation_units_empty_when_no_typed_with_chapters():
    assert relation_units({"canonical_name": "X", "relationships": []}) == []
