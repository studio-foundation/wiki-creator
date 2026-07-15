import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from build_gold import spans_for  # noqa: E402


def test_every_occurrence_of_a_surface_becomes_a_span():
    text = "Eragon rode on. Later, Eragon slept."
    spans, unfound = spans_for(text, [{"text": "Eragon", "label": "PERSON"}])

    assert [(s["start"], s["end"]) for s in spans] == [(0, 6), (23, 29)]
    assert unfound == []


def test_surface_not_in_the_passage_is_reported_not_guessed():
    spans, unfound = spans_for("Eragon rode on.", [{"text": "Saphira", "label": "PERSON"}])

    assert spans == []
    assert unfound == ["Saphira"]


def test_substring_inside_a_longer_word_does_not_match():
    # "Bromsson" must not yield a span for "Brom".
    spans, _ = spans_for("Bromsson waited.", [{"text": "Brom", "label": "PERSON"}])
    assert spans == []


def test_surface_with_regex_metacharacters_is_matched_literally():
    text = "They reached Gil'ead at dusk."
    spans, unfound = spans_for(text, [{"text": "Gil'ead", "label": "PLACE"}])

    assert unfound == []
    assert text[spans[0]["start"]:spans[0]["end"]] == "Gil'ead"


def test_multi_token_surface_matches():
    text = "The Palancar Valley was quiet."
    spans, _ = spans_for(text, [{"text": "Palancar Valley", "label": "PLACE"}])
    assert text[spans[0]["start"]:spans[0]["end"]] == "Palancar Valley"


def test_spans_come_out_sorted_by_position():
    text = "Saphira flew over Carvahall toward Eragon."
    spans, _ = spans_for(text, [
        {"text": "Eragon", "label": "PERSON"},
        {"text": "Saphira", "label": "PERSON"},
        {"text": "Carvahall", "label": "PLACE"},
    ])
    assert [s["start"] for s in spans] == sorted(s["start"] for s in spans)


def test_blank_surface_is_ignored():
    spans, unfound = spans_for("Eragon rode.", [{"text": "  ", "label": "PERSON"}])
    assert spans == [] and unfound == []
