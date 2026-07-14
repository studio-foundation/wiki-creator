from wiki_creator.entity_links import link_first_mentions


def test_links_first_bare_mention_only():
    text = "Dorian rencontre Celaena Sardothien. Plus tard, Celaena Sardothien part."
    out = link_first_mentions(text, {"Celaena Sardothien"})
    assert out == "Dorian rencontre [[Celaena Sardothien]]. Plus tard, Celaena Sardothien part."


def test_leaves_already_linked_name_untouched():
    text = "Dorian aime [[Celaena Sardothien]] puis Celaena Sardothien s'en va."
    out = link_first_mentions(text, {"Celaena Sardothien"})
    # Already linked once — no second link is added.
    assert out.count("[[Celaena Sardothien]]") == 1


def test_links_multiple_distinct_entities():
    text = "Arobynn Hamel a formé Celaena Sardothien."
    out = link_first_mentions(text, {"Arobynn Hamel", "Celaena Sardothien"})
    assert out == "[[Arobynn Hamel]] a formé [[Celaena Sardothien]]."


def test_longest_name_wins_over_substring():
    text = "Celaena Sardothien avance."
    out = link_first_mentions(text, {"Celaena Sardothien", "Celaena"})
    assert "[[Celaena Sardothien]]" in out
    # The substring name must not carve a link inside the longer one.
    assert "[[Celaena]] Sardothien" not in out


def test_word_boundary_prevents_partial_match():
    text = "Le domaine de Cainville est vaste."
    out = link_first_mentions(text, {"Cain"})
    assert out == text


def test_accented_name_links():
    text = "Élide observe la scène."
    out = link_first_mentions(text, {"Élide"})
    assert out == "[[Élide]] observe la scène."


def test_empty_inputs_are_noops():
    assert link_first_mentions("", {"X"}) == ""
    assert link_first_mentions("texte", set()) == "texte"
