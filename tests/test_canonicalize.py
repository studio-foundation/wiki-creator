"""Entity-name canonicalization (STU-719/STU-724) — the one key every site joins on.

Each case is a defect fixed once, in one module, and rediscovered at the next
surface: the `Queen`/`The Queen` fold (STU-636, again at series scope in
STU-719), the Beaver honorific (STU-541, again in clustering in STU-585), the
casing/spacing variants STU-719 measured across the Oz tomes.
"""
import pytest

from wiki_creator.canonicalize import (
    canonical_key,
    canonical_tokens,
    fold_vocabulary,
    is_bare_role,
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


# --- STU-724: the same key, read by clustering and alias-resolution ---

# --- canonical_key: same name, one key ---

def test_casing_folds():
    assert canonical_key("BILLINA") == canonical_key("Billina")


def test_punctuation_folds():
    assert canonical_key("Saw-Horse") == canonical_key("Sawhorse") == "sawhorse"
    assert canonical_key("Tik-tok") == canonical_key("Tiktok")


def test_accents_fold():
    assert canonical_key("Martín") == canonical_key("Martin")


def test_spacing_folds():
    assert canonical_key("  Nome   King ") == "nome king"


def test_leading_article_strips():
    assert canonical_key("The Queen", DETERMINERS) == canonical_key("Queen", DETERMINERS)
    assert canonical_key("THE shaggy man", DETERMINERS) == "shaggy man"


def test_article_only_strips_when_declared():
    # The vocabulary is the book language's, never hardcoded here.
    assert canonical_key("The Queen") == "the queen"


def test_bare_article_survives_as_last_token():
    # STU-636: a name that is nothing but a title is identified by it, not emptied.
    assert canonical_key("The", DETERMINERS) == "the"


def test_different_roles_stay_distinct():
    assert canonical_key("The King", DETERMINERS) != canonical_key("The Queen", DETERMINERS)


def test_honorific_is_kept_because_it_discriminates():
    # STU-541/585: the surname is the part that cannot tell the spouses apart.
    assert canonical_key("Mr Beaver", DETERMINERS) != canonical_key("Mrs Beaver", DETERMINERS)


def test_honorific_punctuation_folds():
    assert canonical_key("Mrs. Beaver") == canonical_key("Mrs Beaver")


# --- canonical_tokens: what a similarity rule compares ---

def test_tokens_strip_declared_vocabulary_but_never_the_last_token():
    assert canonical_tokens("Mr Tumnus", ["mr"]) == ["tumnus"]
    assert canonical_tokens("Mr", ["mr"]) == ["mr"]


def test_tokens_strip_repeated_prefixes():
    assert canonical_tokens("The Mrs Beaver", ["the", "mrs"]) == ["beaver"]


def test_tokens_of_empty_name():
    assert canonical_tokens("") == []


# --- fold_vocabulary: a reader's vocabulary, compared to text ---

def test_vocabulary_folds_to_the_tokens_it_must_match():
    assert fold_vocabulary(["M.", "Mère"]) == frozenset({"m", "mere"})


def test_vocabulary_splits_multiword_entries():
    assert fold_vocabulary(["crown prince"]) == frozenset({"crown", "prince"})


# --- is_bare_role ---

def test_bare_role_single_word():
    assert is_bare_role("King", ["prince", "king"]) is True


def test_bare_role_modifier_plus_head():
    # STU-471: English titles are head-final, so the head carries the role.
    assert is_bare_role("Crown Prince", ["prince"]) is True


def test_title_plus_surname_is_not_bare():
    assert is_bare_role("Captain Westfall", ["captain"]) is False


def test_bare_role_behind_an_article():
    assert is_bare_role("The Queen", ["queen"], DETERMINERS) is True


def test_bare_role_of_empty_name():
    assert is_bare_role("", ["queen"]) is False
