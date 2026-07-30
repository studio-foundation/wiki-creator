"""Entity-name canonicalization (STU-719) — the key the series merge joins on."""
import pytest

from wiki_creator.canonicalize import (
    canonical_key,
    is_generic_role_name,
    preferred_display_name,
)

DETERMINERS = ["the", "a", "an"]
CONNECTORS = ["of", "the", "de", "van", "von"]
ROLE_WORDS = ["captain", "guard", "queen", "king", "prince", "princess", "champion"]


@pytest.mark.parametrize(
    "a,b",
    [
        ("Saw-Horse", "Sawhorse"),
        ("Tik-tok", "Tiktok"),
        ("BILLINA", "Billina"),
        ("Glinda  the Good", "Glinda the Good"),
        ("Hugson's Ranch", "Hugsons Ranch"),
        ("Célaena", "Celaena"),
    ],
)
def test_key_folds_case_accents_spacing_and_punctuation(a, b):
    assert canonical_key(a) == canonical_key(b)


@pytest.mark.parametrize(
    "a,b",
    [
        ("Mr Beaver", "Mrs Beaver"),      # STU-541/585: honorifics are not noise
        ("Nome King", "King"),
        ("Polly", "Polychrome"),
        ("Emerald City", "City of Emeralds"),
    ],
)
def test_key_keeps_distinct_referents_apart(a, b):
    assert canonical_key(a) != canonical_key(b)


def test_key_strips_a_leading_determiner_only_when_declared():
    assert canonical_key("THE shaggy man") != canonical_key("Shaggy Man")
    assert canonical_key("THE shaggy man", DETERMINERS) == canonical_key("Shaggy Man", DETERMINERS)
    # Only leading, and only a whole token: 'Theodore' keeps its 'the'.
    assert canonical_key("Theodore", DETERMINERS) == "theodore"


def test_key_is_empty_for_a_name_with_no_alphanumerics():
    assert canonical_key(" — ") == ""
    assert canonical_key(None) == ""


def test_display_name_prefers_cased_over_shouty():
    assert preferred_display_name(["BILLINA", "Billina"]) == "Billina"
    assert preferred_display_name(["FUDDLECUMJIG"]) == "FUDDLECUMJIG"


def test_display_name_prefers_the_bare_form_over_the_article_led_one():
    assert preferred_display_name(["THE shaggy man", "Shaggy Man"], DETERMINERS) == "Shaggy Man"
    assert preferred_display_name(["The Scarecrow", "Scarecrow"], DETERMINERS) == "Scarecrow"


def test_display_name_falls_back_to_input_order():
    assert preferred_display_name(["Saw-Horse", "Sawhorse"]) == "Saw-Horse"
    assert preferred_display_name([]) == ""


@pytest.mark.parametrize("name", ["King", "Queen", "captain", "Princess", "Champion"])
def test_generic_role_matches_a_bare_role(name):
    assert is_generic_role_name(name, ROLE_WORDS, DETERMINERS, CONNECTORS)


@pytest.mark.parametrize(
    "name", ["Nome King", "Princess Langwidere", "King Bud of Noland", "Dorothy", "Glinda"]
)
def test_generic_role_spares_a_role_qualified_by_a_proper_name(name):
    assert not is_generic_role_name(name, ROLE_WORDS, DETERMINERS, CONNECTORS)


def test_generic_role_matches_an_enumerated_phrase():
    # A reader declares this book's titles in `classification.role_words`.
    assert is_generic_role_name(
        "Guardian of the Gates", [*ROLE_WORDS, "guardian of the gates"], DETERMINERS, CONNECTORS
    )
    assert not is_generic_role_name("Guardian of the Gates", ROLE_WORDS, DETERMINERS, CONNECTORS)


def test_generic_role_needs_a_vocabulary():
    assert not is_generic_role_name("King", [], DETERMINERS, CONNECTORS)
    assert not is_generic_role_name("", ROLE_WORDS, DETERMINERS, CONNECTORS)
