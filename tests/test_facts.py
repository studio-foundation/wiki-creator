from wiki_creator.facts import extract_titles

ROLE_WORDS = ["captain", "guard", "queen", "king", "prince", "princess",
              "lady", "lord", "sir", "duke", "assassin", "champion"]


def test_single_title_from_alias():
    assert extract_titles(["Chaol", "Captain Westfall"], ROLE_WORDS) == ["Captain"]


def test_multiple_titles_dedup_first_seen_order():
    # Realistic clean name variants (resolved aliases), not prose phrases.
    variants = ["Celaena", "Adarlan's Assassin", "Champion", "Assassin"]
    assert extract_titles(variants, ROLE_WORDS) == ["Assassin", "Champion"]


def test_possessive_is_matched_naively_known_limitation():
    # Naive whole-word scan: a possessive role word like "King's" DOES match
    # "king". Acceptable because callers pass clean resolved name variants
    # (aliases/mentions), not prose. Pinned so the behavior is a conscious choice.
    assert extract_titles(["the King's Champion"], ROLE_WORDS) == ["King", "Champion"]


def test_no_title_returns_empty():
    assert extract_titles(["Nehemia", "Nehemia Ytger"], ROLE_WORDS) == []


def test_empty_role_words_returns_empty():
    assert extract_titles(["Captain Westfall"], []) == []


def test_none_variants_safe():
    assert extract_titles([], ROLE_WORDS) == []
