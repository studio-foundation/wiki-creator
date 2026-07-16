"""Book-declared relationship types, and the rename that made room for them (STU-472).

Two halves of one argument: the generic vocabulary must name what a *reader* would
call the bond, and a bond only that novel has must be declarable by the person who
read that novel.
"""
from pathlib import Path

import pytest
import yaml

from wiki_creator import page_templates as pt
from wiki_creator.relationship_vocabulary import book_relationship_types

import scripts.relationship_classifier_validator as validator
from scripts.relationship_extraction import _run_studio_classifier_item

DRAGON_BOND = "lien de Dragonnier"

ERAGON_CONFIG = {
    "classification": {
        "relationship_types": [
            {"name": DRAGON_BOND, "description": "The magical bond between a Rider and their dragon."},
            {"name": "carranam", "description": "Two magicians whose minds are magically linked."},
        ]
    }
}


# --- the vocabulary a book adds ------------------------------------------------


def test_book_types_join_the_generic_ones():
    """The generic types stay the base; the world's own bonds are added, not swapped."""
    names = [d["name"] for d in pt.relationship_definitions(book_config=ERAGON_CONFIG)]
    assert set(pt.relationship_tokens()) <= set(names)
    assert DRAGON_BOND in names
    assert "carranam" in names


def test_book_type_carries_its_description_into_the_prompt():
    """A name with no criterion guides nothing — same rule STU-477 set for the base enum."""
    defs = {d["name"]: d["description"] for d in pt.relationship_definitions(book_config=ERAGON_CONFIG)}
    assert defs[DRAGON_BOND] == "The magical bond between a Rider and their dragon."


def test_no_book_section_is_the_generic_vocabulary_alone():
    """Graceful fallback: an unconfigured book is byte-identical to pre-STU-472."""
    assert pt.relationship_definitions(book_config={}) == pt.relationship_definitions()
    assert pt.relationship_definitions(book_config=None) == pt.relationship_definitions()


def test_book_type_survives_validation_and_renders_as_written():
    """A book type must cross all three gates: prompt, validation, rendering. The
    name IS the reader-facing label — no token/label split for book config."""
    assert pt.canonical_relationship(DRAGON_BOND, book_config=ERAGON_CONFIG) == DRAGON_BOND
    assert pt.relationship_label(DRAGON_BOND, "fr", book_config=ERAGON_CONFIG) == DRAGON_BOND


def test_book_type_is_unknown_to_a_book_that_did_not_declare_it():
    assert pt.canonical_relationship(DRAGON_BOND) is None


@pytest.mark.parametrize(
    "entry",
    [
        {"description": "no name"},
        {"name": "", "description": "empty name"},
        {"name": "nameless_criterion"},
        {"name": "blank_criterion", "description": "   "},
    ],
)
def test_an_incomplete_book_type_raises(entry):
    """A silently-dropped type is the STU-470 shape: the config says one thing and the
    pipeline does another. Fail at config instead."""
    with pytest.raises(ValueError):
        book_relationship_types({"classification": {"relationship_types": [entry]}})


def test_a_book_type_shadowing_a_generic_one_raises():
    """Two entries with one name make the criterion ambiguous — and the model would
    return a name that resolves to whichever we looked up first."""
    with pytest.raises(ValueError, match="family"):
        pt.relationship_definitions(
            book_config={
                "classification": {
                    "relationship_types": [{"name": "family", "description": "redefined"}]
                }
            }
        )


def test_book_types_reach_the_classifier_payload(monkeypatch):
    """The whole point: the model cannot return a type it was never shown."""
    captured = {}

    def fake_run(cmd, **kwargs):
        input_path = cmd[cmd.index("--input-file") + 1]
        captured["payload"] = yaml.safe_load(Path(input_path).read_text(encoding="utf-8"))
        raise FileNotFoundError  # short-circuit: we only care about the payload

    monkeypatch.setattr("scripts.relationship_extraction.subprocess.run", fake_run)
    _run_studio_classifier_item(
        {"entity_a": "Eragon", "entity_b": "Saphira"},
        novel_summary="",
        additional_context="",
        book_config=ERAGON_CONFIG,
    )

    sent = [d["name"] for d in captured["payload"]["relationship_types"]]
    assert DRAGON_BOND in sent


def test_validator_accepts_a_book_type_it_was_shown():
    """The validator judges the answer against the vocabulary we actually sent — read
    from the payload, not from a global table that never heard of this book."""
    meta = {
        "entity_a": "Eragon",
        "entity_b": "Saphira",
        "relationship_types": pt.relationship_definitions(book_config=ERAGON_CONFIG),
    }
    assert validator.check_relationship_type_valid({"relationship_type": DRAGON_BOND}, meta) == []


def test_validator_rejects_a_type_absent_from_the_payload():
    meta = {"relationship_types": pt.relationship_definitions(book_config=ERAGON_CONFIG)}
    assert validator.check_relationship_type_valid({"relationship_type": "soulmates"}, meta)


def test_validator_without_a_payload_vocabulary_falls_back_to_the_generic_enum():
    """Pre-STU-472 payloads (and the offline callers) carry no vocabulary."""
    assert validator.check_relationship_type_valid({"relationship_type": "family"}, {}) == []
    assert validator.check_relationship_type_valid({"relationship_type": DRAGON_BOND}, {})


# --- the rename: relational words, not narratological ones ----------------------


def test_the_narratological_type_is_gone():
    """`antagonist` names a story-structure role held toward THE protagonist. Saying
    Chaol is Cain's antagonist implies Cain heads his own novel. Readers say enemy."""
    assert "antagonist" not in pt.relationship_tokens()
    assert "enemy" in pt.relationship_tokens()


@pytest.mark.parametrize("legacy", ["antagoniste", "antagonist"])
def test_pre_rename_artifacts_still_render(legacy):
    """`legacy` is a rendering map for artifacts already on disk, not a vocabulary the
    classifier may still emit."""
    assert pt.canonical_relationship(legacy) == "enemy"
    assert validator.check_relationship_type_valid({"relationship_type": legacy})


def test_enemy_is_labelled_in_readers_words():
    assert pt.relationship_label("enemy", "en") == "Enemy"
    assert pt.relationship_label("enemy", "fr") == "Ennemi"
