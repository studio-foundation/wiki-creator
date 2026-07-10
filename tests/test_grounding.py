"""Tests for wiki_creator/grounding.py — deterministic anti-hallucination."""
from wiki_creator.grounding import (
    extract_name_candidates,
    find_ungrounded_names,
    normalize,
)


SOURCE = (
    "Celaena Sardothien est une assassine emprisonnée à Endovier. "
    "Le prince Dorian Havilliard lui offre un marché. "
    "Chaol Westfall, capitaine de la garde, supervise son entraînement. "
    "Nehemia est une princesse d'Eyllwe en visite au palais de verre. "
    "Nox Owen est un voleur venu du nord participant au Tournoi."
)


# --- normalize ---


def test_normalize_strips_accents_and_case():
    assert normalize("Néhémia D'EYLLWE") == "nehemia d'eyllwe"


# --- extract_name_candidates ---


def test_extracts_multiword_names_anywhere():
    content = "Celaena Sardothien affronte ses rivaux."
    assert "Celaena Sardothien" in extract_name_candidates(content)


def test_extracts_midsentence_single_names():
    content = "Elle rencontre Dorian dans la bibliothèque."
    assert "Dorian" in extract_name_candidates(content)


def test_skips_single_capitalized_word_at_sentence_start():
    content = "Elle attend. Ensuite vient la nuit."
    assert "Ensuite" not in extract_name_candidates(content)
    assert "Elle" not in extract_name_candidates(content)


def test_skips_capitalized_word_after_dialogue_dash_and_quotes():
    content = "— Regarde là-bas. « Attends un peu. »"
    candidates = extract_name_candidates(content)
    assert "Regarde" not in candidates
    assert "Attends" not in candidates


def test_joins_names_with_connectors():
    content = "Elle lit La Colonne de Feu chaque soir."
    candidates = extract_name_candidates(content)
    assert any("Colonne" in c and "Feu" in c for c in candidates)


def test_strips_elision_prefix():
    content = "Elle parle avec l'Assassine du roi."
    candidates = extract_name_candidates(content)
    assert "Assassine" in candidates


def test_ignores_markdown_markup():
    content = "## Biographie\n\n**Celaena Sardothien** vit au palais."
    candidates = extract_name_candidates(content)
    assert "Celaena Sardothien" in candidates
    assert "Biographie" not in candidates  # heading = line start


def test_headings_do_not_leak_into_candidates():
    content = "## Relations\n\nElle se méfie de Kaltain à la cour."
    candidates = extract_name_candidates(content)
    assert "Relations" not in candidates
    assert "Kaltain" in candidates


# --- find_ungrounded_names ---


def test_grounded_names_pass():
    content = (
        "## Biographie\n\nCelaena Sardothien s'entraîne avec Chaol Westfall. "
        "Elle se lie d'amitié avec Nehemia."
    )
    assert find_ungrounded_names(content, {}, SOURCE) == []


def test_flags_invented_person_run15_regression():
    # Run 15: Nehemia confused with Yrene Astellaris (book-6 character)
    content = "Nehemia, aussi connue sous le nom de Yrene Astellaris, vit au palais."
    flagged = find_ungrounded_names(content, {}, SOURCE)
    assert any("Yrene" in f for f in flagged)


def test_flags_cross_series_title_run7_regression():
    # Run 7: wrong series titles in the References section
    content = "## Références\n\nVoir aussi La Colonne de Feu pour la suite."
    flagged = find_ungrounded_names(content, {}, SOURCE)
    assert any("Colonne" in f for f in flagged)


def test_flags_invented_kingdom_in_infobox_run15_regression():
    # Run 15: Kaltain described as confidante of queen Elena of 'Ruhn'
    infobox = {"allégeance": "Royaume de Ruhn"}
    flagged = find_ungrounded_names("Texte ancré sans nom.", infobox, SOURCE)
    assert any("Ruhn" in f for f in flagged)


def test_partial_name_passes_when_tokens_grounded():
    # 'Celaena' alone is grounded even though the source pairs it with
    # 'Sardothien'; token-level matching avoids this false positive.
    content = "Elle voit Celaena au Tournoi."
    assert find_ungrounded_names(content, {}, SOURCE) == []


def test_accent_variations_still_ground():
    content = "Elle accompagne Néhémia au palais."
    # Source spells it 'Nehemia' — accent-insensitive matching must pass.
    assert find_ungrounded_names(content, {}, SOURCE) == []


def test_empty_source_disables_check():
    content = "Yrene Astellaris apparaît ici."
    assert find_ungrounded_names(content, {}, "") == []


def test_max_names_cap():
    content = (
        "Il voit Zorg Premier, Blarg Second, Krog Troisième, "
        "Vlim Quatrième, Nix Cinquième, Plom Sixième et Grul Septième."
    )
    flagged = find_ungrounded_names(content, {}, SOURCE, max_names=5)
    assert len(flagged) == 5


def test_dedupes_repeated_names():
    content = "Yrene sourit. Elle regarde Yrene. Encore Yrene."
    flagged = find_ungrounded_names(content, {}, SOURCE)
    assert flagged.count("Yrene") == 1
