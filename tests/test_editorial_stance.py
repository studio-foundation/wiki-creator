"""STU-507: the editorial stance is declared, and grounding never depends on it."""

import pytest

from wiki_creator.editorial_stance import (
    GROUNDING_BLOCK,
    EditorialStance,
    editorial_stance,
)


def _cfg(**stance):
    return {"generation": {"editorial_stance": stance}}


def test_default_stance_reproduces_the_pre_stu507_posture():
    stance = editorial_stance({})
    assert stance.mode == "hybrid"
    assert stance.allows_section("references")
    assert stance.allows_section("narrative_role")
    assert stance.expose_pipeline_metadata
    assert stance.expose_importance_tier
    assert stance.forbid_author_mentions


def test_in_universe_forbids_every_out_of_universe_section():
    stance = editorial_stance(_cfg(mode="in_universe"))
    assert not stance.allows_section("references")
    assert not stance.allows_section("narrative_role")
    assert stance.allows_section("biography")


def test_out_of_universe_allows_every_section():
    stance = editorial_stance(_cfg(mode="out_of_universe"))
    assert stance.allows_section("references")
    assert stance.allows_section("narrative_role")


def test_hybrid_allows_only_the_declared_exceptions():
    stance = editorial_stance(_cfg(mode="hybrid", hybrid_exceptions=["references_section"]))
    assert stance.allows_section("references")
    assert not stance.allows_section("narrative_role")


def test_unknown_mode_is_a_config_error():
    with pytest.raises(ValueError, match="editorial_stance.mode"):
        editorial_stance(_cfg(mode="in-universe"))


def test_unknown_hybrid_exception_is_a_config_error():
    with pytest.raises(ValueError, match="hybrid_exceptions"):
        editorial_stance(_cfg(mode="hybrid", hybrid_exceptions=["trivia_section"]))


def test_grounding_block_carries_no_stance_rule():
    """Grounding and stance are separable: switching posture must not touch the
    'invent nothing' contract, so the grounding block says nothing about posture."""
    assert "prior knowledge" in GROUNDING_BLOCK
    assert "supported by one of the GROUNDING EXCERPTS" in GROUNDING_BLOCK
    for mode_word in ("in-universe", "out-of-universe", "author, publisher"):
        assert mode_word not in GROUNDING_BLOCK


def test_stance_block_names_the_mode_and_the_hybrid_exceptions():
    block = EditorialStance().prompt_block()
    assert "EDITORIAL STANCE — hybrid" in block
    assert "Références" in block and "Rôle dans le récit" in block


def test_stance_block_names_only_the_exceptions_among_the_written_sections():
    block = EditorialStance().prompt_block(["infobox", "biography", "references"])
    assert "Références" in block
    assert "Rôle dans le récit" not in block


def test_stance_block_drops_the_exception_line_when_no_exception_is_written():
    block = EditorialStance().prompt_block(["infobox", "biography"])
    assert "Exception" not in block


def test_stance_block_author_rule_is_independent_of_mode():
    assert "real-world author" in EditorialStance(mode="out_of_universe").prompt_block()
    assert (
        "real-world author"
        not in EditorialStance(mode="in_universe", forbid_author_mentions=False).prompt_block()
    )
