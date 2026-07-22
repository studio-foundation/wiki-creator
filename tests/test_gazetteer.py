"""Tests for the per-book character gazetteer (STU-630).

No model needed: the component is a PhraseMatcher over declared names, so a blank
English pipeline exercises everything but the GLiNER co-tenancy (covered by the
overlap test with hand-set ents).
"""
import spacy

from wiki_creator.nlp.gazetteer import BookGazetteer, attach

NAMES = ["Hatter", "Cheshire Cat", "Cat", "Dormouse"]


def blank_nlp():
    return spacy.blank("en")


def component(names=NAMES):
    nlp = blank_nlp()
    return nlp, BookGazetteer(nlp, names, "PERSON")


def test_declared_common_noun_name_is_typed_person():
    nlp, comp = component()
    doc = comp(nlp("Then the Hatter opened his eyes very wide."))
    assert [(e.text, e.label_) for e in doc.ents] == [("Hatter", "PERSON")]


def test_matching_is_case_sensitive_so_the_bare_common_noun_is_left_alone():
    """A lowercase `cat` is the animal the character is named after, not the
    character — only the capitalised name is a mention."""
    nlp, comp = component()
    doc = comp(nlp("The Cat grinned at the cat on the mat."))
    assert [e.text for e in doc.ents] == ["Cat"]


def test_multiword_name_matches_as_one_span():
    nlp, comp = component()
    doc = comp(nlp("The Cheshire Cat vanished."))
    assert [(e.text, e.label_) for e in doc.ents] == [("Cheshire Cat", "PERSON")]


def test_gazetteer_span_wins_over_an_overlapping_shorter_ner_ent():
    """GLiNER, in the ner slot, may have caught only `Cat`; the reader declared
    `Cheshire Cat`, so the longer declared span replaces it."""
    nlp = blank_nlp()
    doc = nlp("The Cheshire Cat vanished.")
    cat = doc.char_span(doc.text.index("Cat"), doc.text.index("Cat") + 3, label="PERSON")
    doc.ents = [cat]
    doc = BookGazetteer(nlp, ["Cheshire Cat"], "PERSON")(doc)
    assert [e.text for e in doc.ents] == ["Cheshire Cat"]


def test_existing_ner_ents_are_preserved_where_no_gazetteer_match():
    nlp = blank_nlp()
    doc = nlp("Alice met the Hatter.")
    alice = doc.char_span(0, 5, label="PERSON")
    doc.ents = [alice]
    doc = BookGazetteer(nlp, ["Hatter"], "PERSON")(doc)
    assert {e.text for e in doc.ents} == {"Alice", "Hatter"}


def test_every_occurrence_is_matched():
    nlp, comp = component()
    doc = comp(nlp("The Hatter and the Hatter and again the Hatter."))
    assert [e.text for e in doc.ents] == ["Hatter", "Hatter", "Hatter"]


def test_no_names_is_a_noop_component():
    nlp = blank_nlp()
    doc = nlp("The Hatter opened his eyes.")
    assert BookGazetteer(nlp, [], "PERSON")(doc).ents == ()


def test_attach_is_noop_when_no_names():
    nlp = blank_nlp()
    attach(nlp, [])
    assert "book_gazetteer" not in nlp.pipe_names


def test_attach_appends_after_the_ner_slot():
    nlp = blank_nlp()
    nlp.add_pipe("ner")
    attach(nlp, NAMES)
    assert nlp.pipe_names[-1] == "book_gazetteer"
