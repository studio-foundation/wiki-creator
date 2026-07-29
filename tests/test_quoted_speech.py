"""Tests for wiki_creator/quoted_speech.py — offstage names (STU-716)."""
from wiki_creator.quoted_speech import (
    is_inside,
    is_offstage,
    quoted_spans,
    quoted_spans_by_chapter,
)

# The defect this module closes: the Mock Turtle's pun on his schoolmaster's
# name became a PERSON with a page and a mentor relationship.
ALICE = (
    "“we went to school in the sea. The master was an old Turtle—we used to "
    "call him Tortoise—”\n\n"
    "“Why did you call him Tortoise, if he wasn't one?” Alice asked.\n\n"
    "“We called him Tortoise because he taught us,” said the Mock Turtle angrily."
)


def _spans(text: str) -> dict:
    return quoted_spans_by_chapter({"ch01": text})


def test_curly_quotes_bound_the_speech():
    text = "Alice waited. “Come here,” said the Queen. Alice went."
    (start, end), = quoted_spans(text)
    assert text[start:end] == "“Come here,”"


def test_unterminated_quote_stops_at_the_paragraph():
    text = "“First they said this.\n\nAnd then the narrator spoke."
    (start, end), = quoted_spans(text)
    assert text[start:end] == "“First they said this."


def test_straight_quotes_toggle():
    text = 'He said "come here" and left.'
    (start, end), = quoted_spans(text)
    assert text[start:end] == '"come here"'


def test_is_inside_only_for_fully_covered_spans():
    spans = [(10, 20)]
    assert is_inside(spans, 12, 15)
    assert not is_inside(spans, 18, 25)


def test_a_name_spoken_about_is_offstage():
    assert is_offstage(["Tortoise"], {"ch01": ALICE}, _spans(ALICE))


def test_a_name_the_narrator_uses_is_not_offstage():
    assert not is_offstage(["Mock Turtle"], {"ch01": ALICE}, _spans(ALICE))


def test_an_absent_name_is_not_offstage():
    assert not is_offstage(["Gryphon"], {"ch01": ALICE}, _spans(ALICE))


def test_any_surface_form_outside_speech_keeps_the_entity_onstage():
    text = "“Tell Mary Ann to hurry,” he said. The real Mary Ann never came."
    assert not is_offstage(["Mary Ann"], {"ch01": text}, _spans(text))


def test_matching_is_case_sensitive_and_whole_word():
    text = "“I Will go,” she said. He will not."
    assert is_offstage(["Will"], {"ch01": text}, _spans(text))
