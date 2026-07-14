"""Tests for wiki_creator/synopsis.py — the SP4 book-synopsis projection."""
from wiki_creator.synopsis import (
    SYNOPSIS_ENTITY_TYPE,
    SYNOPSIS_IMPORTANCE,
    SYNOPSIS_TITLE,
    build_synopsis_prompt,
    event_lines,
    salience_label,
    select_events,
)


def _event(chapter, description, salience=0.5, participants=(), places=(), outcome=None):
    return {
        "event_id": f"e_ch{chapter}_x",
        "chapter": chapter,
        "description": description,
        "participants": list(participants),
        "places": list(places),
        "outcome": outcome,
        "salience": salience,
        "source_bullets": [description],
    }


# --- select_events ---


def test_select_events_orders_by_chapter():
    events = [_event(12, "final duel"), _event(1, "freed from Endovier"), _event(6, "training")]
    got = select_events(events)
    assert [e["chapter"] for e in got] == [1, 6, 12]


def test_select_events_caps_per_chapter_by_salience():
    events = [
        _event(3, "a low beat", salience=0.1),
        _event(3, "b crucial beat", salience=0.9),
        _event(3, "c medium beat", salience=0.5),
    ]
    got = select_events(events, max_per_chapter=2)
    assert [e["description"] for e in got] == ["b crucial beat", "c medium beat"]


def test_select_events_keeps_chronological_order_within_chapter():
    events = [
        _event(3, "zz early scene", salience=0.9),
        _event(3, "aa later climax", salience=0.95),
    ]
    got = select_events(events, max_per_chapter=2)
    # kept events return to stable description order, not salience order
    assert [e["description"] for e in got] == ["aa later climax", "zz early scene"]


def test_select_events_no_cap_when_nonpositive():
    events = [_event(1, f"beat {i}", salience=0.1) for i in range(5)]
    assert len(select_events(events, max_per_chapter=0)) == 5
    assert len(select_events(events, max_per_chapter=-1)) == 5


def test_select_events_empty_and_none():
    assert select_events([]) == []
    assert select_events(None) == []  # type: ignore[arg-type]


# --- event_lines ---


def test_event_lines_formats_chapter_and_details():
    events = [
        _event(12, "Celaena affronte Cain",
               participants=["Cain", "Celaena Sardothien"], places=["Rifthold"]),
    ]
    (line,) = event_lines(events)
    assert line.startswith("[Chapitre 12] Celaena affronte Cain")
    assert "personnages : Cain, Celaena Sardothien" in line
    assert "lieux : Rifthold" in line


def test_event_lines_omits_empty_details_and_redundant_outcome():
    events = [_event(2, "a quiet scene", outcome="a quiet scene")]
    (line,) = event_lines(events)
    assert line == "[Chapitre 2] a quiet scene"


def test_event_lines_includes_informative_outcome():
    events = [_event(12, "the final duel", outcome="Celaena wins despite the poison")]
    (line,) = event_lines(events)
    assert "issue : Celaena wins despite the poison" in line


def test_event_lines_skips_blank_descriptions():
    assert event_lines([_event(1, "  ")]) == []


def test_event_lines_omits_salience_by_default():
    (line,) = event_lines([_event(1, "a beat", salience=0.9)])
    assert "importance" not in line


def test_event_lines_includes_salience_tier_when_requested():
    (high,) = event_lines([_event(12, "climax", salience=0.8)], include_salience=True)
    (mid,) = event_lines([_event(6, "middle", salience=0.4)], include_salience=True)
    (low,) = event_lines([_event(1, "minor", salience=0.1)], include_salience=True)
    assert "importance : haute" in high
    assert "importance : moyenne" in mid
    assert "importance : basse" in low


def test_salience_label_thresholds():
    assert salience_label(0.6) == "haute"
    assert salience_label(0.59) == "moyenne"
    assert salience_label(0.35) == "moyenne"
    assert salience_label(0.34) == "basse"
    assert salience_label(0.0) == "basse"


# --- build_synopsis_prompt ---


def test_prompt_contains_events_and_book_title():
    events = [_event(1, "Celaena is freed from Endovier", participants=["Celaena Sardothien"])]
    prompt = build_synopsis_prompt(events, "Throne of Glass")
    assert "Throne of Glass" in prompt
    assert "[Chapitre 1] Celaena is freed from Endovier" in prompt
    assert "## Synopsis" in prompt


def test_prompt_declares_page_identity_contract():
    prompt = build_synopsis_prompt([], "Throne of Glass")
    assert f'"title": "{SYNOPSIS_TITLE}"' in prompt
    assert f'"importance": "{SYNOPSIS_IMPORTANCE}"' in prompt
    assert f'"entity_type": "{SYNOPSIS_ENTITY_TYPE}"' in prompt


def test_prompt_includes_forbidden_names_rule_only_when_given():
    events = [_event(1, "a beat")]
    with_names = build_synopsis_prompt(events, "TOG", forbidden_names=["Aelin"])
    assert "FORBIDDEN NAMES" in with_names
    assert "- Aelin" in with_names
    without = build_synopsis_prompt(events, "TOG")
    assert "FORBIDDEN NAMES" not in without


def test_prompt_handles_no_events():
    prompt = build_synopsis_prompt([], "TOG")
    assert "(no events available)" in prompt
