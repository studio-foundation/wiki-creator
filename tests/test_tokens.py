from wiki_creator.tokens import contains_token_run


def test_whole_token_not_substring_in_either_boundary():
    # The rule both callers share: a token is not a substring of a longer word.
    assert not contains_token_run("beavers", "beaver")
    assert not contains_token_run("person", "son", boundary="word")


def test_whitespace_boundary_keeps_a_possessive_glued():
    # STU-541: "Durza" is not the token "Durza's".
    assert not contains_token_run("durza's blade took brom", "durza")


def test_word_boundary_crosses_a_possessive():
    # STU-552: a killer named in the possessive must ground.
    assert contains_token_run("durza's blade took brom", "durza", boundary="word")


def test_a_plain_token_matches_in_both_boundaries():
    assert contains_token_run("mr beaver", "beaver")
    assert contains_token_run("durza hunted brom", "durza", boundary="word")


def test_a_multiword_run_matches_contiguously():
    assert contains_token_run("chaol westfall struck", "chaol westfall")
    assert contains_token_run("at farthen dûr", "farthen dûr", boundary="word")
    assert not contains_token_run("chaol met westfall", "chaol westfall")


def test_an_empty_run_never_matches():
    assert not contains_token_run("anything", "")
    assert not contains_token_run("anything", "   ", boundary="word")


def test_unknown_boundary_raises():
    import pytest

    with pytest.raises(ValueError):
        contains_token_run("a b", "a", boundary="token")
