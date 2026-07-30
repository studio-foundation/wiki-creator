"""Registry-owned canonicalization (STU-724).

Each case here is a defect that was fixed once, in one module, and rediscovered
at the next surface: the `Queen`/`The Queen` fold (STU-636, again at series scope
in STU-719), the Beaver honorific (STU-541, again in clustering in STU-585), the
casing/spacing variants STU-719 found across the Oz tomes.
"""
from wiki_creator.canonicalize import (
    canonical_key,
    canonical_tokens,
    fold_vocabulary,
    is_bare_role,
)

DETERMINERS = ["the", "a", "an"]


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
