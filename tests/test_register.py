"""STU-644: the editorial register axis (voice/tone), per book."""

import pytest

from wiki_creator.register import DEFAULT_REGISTER, register_clause


def test_absent_register_yields_the_neutral_default():
    assert register_clause({}) == DEFAULT_REGISTER
    assert register_clause({"generation": {}}) == DEFAULT_REGISTER


def test_declared_register_is_returned_stripped():
    cfg = {"generation": {"register": "  Whimsical, nonsense-tinged.  "}}
    assert register_clause(cfg) == "Whimsical, nonsense-tinged."


@pytest.mark.parametrize("bad", ["", "   ", 3, [], {}])
def test_present_but_invalid_register_raises(bad):
    with pytest.raises(ValueError):
        register_clause({"generation": {"register": bad}})
