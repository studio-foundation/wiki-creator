from scripts.copyright_check import tokenize, mask_short_quotes
from scripts.copyright_check import build_source_index, find_violations
from scripts.copyright_check import check_page, format_output, is_public_domain


def test_tokenize_lowercases_and_strips_punctuation():
    tokens = tokenize("David Martín entra, les mains vides.")
    assert tokens == ["david", "martín", "entra", "les", "mains", "vides"]


def test_tokenize_handles_newlines_and_extra_spaces():
    tokens = tokenize("Il entra.\n\nElle sortit.  Voilà.")
    assert tokens == ["il", "entra", "elle", "sortit", "voilà"]


def test_mask_short_quotes_french_guillemets():
    text = "Il dit « bonjour ami » et repartit."
    result = mask_short_quotes(text, max_words=5)
    assert "bonjour" not in result
    assert "Il dit" in result
    assert "et repartit" in result


def test_mask_short_quotes_preserves_long_quotes():
    # 6 words — should NOT be masked
    text = "Il cria « un deux trois quatre cinq six » dans la nuit."
    result = mask_short_quotes(text, max_words=5)
    assert "un deux trois quatre cinq six" in result


def test_mask_short_quotes_double_quotes():
    text = 'Elle murmura "mon dieu" et ferma les yeux.'
    result = mask_short_quotes(text, max_words=5)
    assert "mon dieu" not in result


def test_tokenize_splits_on_apostrophe_and_hyphen():
    # Documents intentional behavior: l'homme → ["l", "homme"], peut-être → ["peut", "être"]
    tokens = tokenize("l'homme peut-être")
    assert tokens == ["l", "homme", "peut", "être"]


SOURCE_CHAPTERS = [
    {
        "id": "ch01",
        "content": (
            "David Martín prit le manuscrit entre ses mains tremblantes "
            "et le déposa sur la table en bois verni avec soin. "
            "Il referma les yeux et écouta le silence de la nuit."
        ),
    }
]


def test_build_source_index_creates_ngrams():
    index = build_source_index(SOURCE_CHAPTERS, n=5)
    tokens = ["david", "martín", "prit", "le", "manuscrit"]
    assert tuple(tokens) in index


def test_build_source_index_maps_to_chapter_id():
    index = build_source_index(SOURCE_CHAPTERS, n=5)
    gram = ("david", "martín", "prit", "le", "manuscrit")
    assert index[gram] == "ch01"


def test_find_violations_detects_verbatim_match():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    # This is 15 words verbatim from SOURCE_CHAPTERS
    verbatim = (
        "david martín prit le manuscrit entre ses mains tremblantes "
        "et le déposa sur la table"
    )
    violations = find_violations(tokenize(verbatim), index, n=15)
    assert len(violations) == 1
    assert violations[0]["chapter"] == "ch01"
    assert violations[0]["consecutive_words"] >= 15


def test_find_violations_no_match_on_clean_text():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    clean = "Le personnage contemplait les étoiles depuis la fenêtre de sa chambre."
    violations = find_violations(tokenize(clean), index, n=15)
    assert violations == []


def test_find_violations_short_quote_exempted():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    # The source phrase embedded in a short quote — masked before tokenize
    text = "Il répéta « prit le manuscrit » et s'arrêta de parler."
    masked = mask_short_quotes(text, max_words=5)
    violations = find_violations(tokenize(masked), index, n=15)
    assert violations == []


WIKI_PAGES = [
    {
        "title": "David Martín",
        "content": (
            "David Martín prit le manuscrit entre ses mains tremblantes "
            "et le déposa sur la table en bois verni avec soin. "
            "Il referma les yeux et écouta le silence de la nuit.\n\n"
            "Il était un écrivain célèbre dans tout Barcelone."
        ),
        "importance": "principal",
    },
    {
        "title": "Barcelone",
        "content": "Barcelone est la capitale de la Catalogne.",
        "importance": "secondary",
    },
]


def test_check_page_detects_violation():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    violations = check_page(WIKI_PAGES[0], index, n=15)
    assert len(violations) >= 1
    assert violations[0]["page_title"] == "David Martín"
    assert violations[0]["chapter"] == "ch01"
    assert violations[0]["consecutive_words"] >= 15


def test_check_page_clean_page_returns_empty():
    index = build_source_index(SOURCE_CHAPTERS, n=15)
    violations = check_page(WIKI_PAGES[1], index, n=15)
    assert violations == []


def test_format_output_pass():
    result = format_output(pages_checked=10, violations=[])
    assert result["status"] == "pass"
    assert result["violations"] == []
    assert result["checked_pages"] == 10


def test_format_output_fail_includes_feedback():
    viol = [{"page_title": "David Martín", "chapter": "ch01",
              "wiki_excerpt": "...", "consecutive_words": 18}]
    result = format_output(pages_checked=10, violations=viol)
    assert result["status"] == "fail"
    assert "David Martín" in result["feedback"]
    assert len(result["violations"]) == 1


# STU-637: public-domain sources have no copyright to protect — verbatim spans
# are advisory, never a blocking `fail` that stops export.
VIOLATION = [{"page_title": "Alice", "chapter": "ch01",
              "wiki_excerpt": "...", "consecutive_words": 18}]


def test_public_domain_book_verbatim_page_is_advisory_not_fail():
    result = format_output(pages_checked=19, violations=VIOLATION, public_domain=True)
    assert result["status"] == "advisory"
    assert result["violations"] == VIOLATION  # still reported


def test_in_copyright_book_verbatim_page_still_fails():
    result = format_output(pages_checked=19, violations=VIOLATION, public_domain=False)
    assert result["status"] == "fail"


def test_public_domain_clean_page_still_passes():
    result = format_output(pages_checked=19, violations=[], public_domain=True)
    assert result["status"] == "pass"


def test_is_public_domain_from_corpus_tree():
    assert is_public_domain("public_domain/lewis_carroll/alice/books/01-alice.epub")
    assert not is_public_domain("library/sarah_j_maas/throne-of-glass/books/01.epub")


def test_is_public_domain_explicit_key_overrides_path():
    assert is_public_domain("library/x/y/books/01.epub", {"public_domain": True})
    assert not is_public_domain("public_domain/x/y/books/01.epub", {"public_domain": False})


def test_is_public_domain_ignores_substring_in_filename():
    # "public_domain" as a filename fragment, not a path component, must not match.
    assert not is_public_domain("library/x/y/books/public_domain_notes.epub")
