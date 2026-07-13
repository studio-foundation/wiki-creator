"""Tests for wiki_creator/event_pages.py — the SP3 event-pages projection."""
from wiki_creator.event_pages import (
    EVENT_ENTITY_TYPE,
    EVENT_IMPORTANCE,
    build_event_prompt,
    event_infobox_fields,
    event_title,
    select_events,
)


def _event(chapter, description, salience=0.5, participants=("Celaena",), places=(), outcome=None):
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


def test_select_events_filters_by_threshold():
    events = [_event(1, "low", salience=0.3), _event(2, "high", salience=0.8)]
    got = select_events(events, threshold=0.6)
    assert [e["description"] for e in got] == ["high"]


def test_select_events_orders_by_salience_desc():
    events = [_event(1, "a", salience=0.7), _event(2, "b", salience=0.95), _event(3, "c", salience=0.8)]
    got = select_events(events, threshold=0.6)
    assert [e["description"] for e in got] == ["b", "c", "a"]


def test_select_events_requires_participants_by_default():
    events = [
        _event(1, "orphan climax", salience=1.0, participants=()),
        _event(2, "real event", salience=0.7),
    ]
    got = select_events(events, threshold=0.6)
    assert [e["description"] for e in got] == ["real event"]


def test_select_events_participant_filter_can_be_disabled():
    events = [_event(1, "orphan", salience=1.0, participants=())]
    got = select_events(events, threshold=0.6, require_participants=False)
    assert len(got) == 1


def test_select_events_caps_to_max_pages():
    events = [_event(i, f"e{i}", salience=0.9) for i in range(5)]
    assert len(select_events(events, threshold=0.6, max_pages=2)) == 2
    assert len(select_events(events, threshold=0.6, max_pages=0)) == 5


def test_select_events_empty_and_none():
    assert select_events([]) == []
    assert select_events(None) == []  # type: ignore[arg-type]


# --- event_title ---


def test_event_title_strips_trailing_punctuation():
    assert event_title(_event(1, "Celaena affronte Cain.")) == "Celaena affronte Cain"
    assert event_title(_event(1, "Champions left—only her.")) == "Champions left—only her"


# --- event_infobox_fields ---


def test_event_infobox_fields_full():
    event = _event(48, "the duel", participants=["Cain", "Celaena"], places=["Rifthold"],
                   outcome="Celaena wins")
    fields = event_infobox_fields(event)
    assert fields == {
        "participants": "Cain, Celaena",
        "lieu": "Rifthold",
        "chapitre": "48",
        "issue": "Celaena wins",
    }


def test_event_infobox_fields_omits_empty_and_redundant_outcome():
    event = _event(3, "a quiet scene", participants=["Celaena"], places=[], outcome="a quiet scene")
    fields = event_infobox_fields(event)
    assert fields == {"participants": "Celaena", "chapitre": "3"}


# --- build_event_prompt ---


def test_prompt_contains_facts_title_and_book():
    event = _event(12, "Celaena defeats Cain", participants=["Cain", "Celaena Sardothien"],
                   places=["Rifthold"], outcome="Celaena wins despite the poison")
    prompt = build_event_prompt(event, "Celaena defeats Cain", "Throne of Glass")
    assert "Throne of Glass" in prompt
    assert "Celaena defeats Cain" in prompt
    assert "Cain, Celaena Sardothien" in prompt
    assert "Rifthold" in prompt
    assert "Celaena wins despite the poison" in prompt
    assert "## Déroulement" in prompt


def test_prompt_declares_event_identity_contract():
    prompt = build_event_prompt(_event(1, "x"), "x", "TOG")
    assert f'"importance": "{EVENT_IMPORTANCE}"' in prompt
    assert f'"entity_type": "{EVENT_ENTITY_TYPE}"' in prompt


def test_prompt_includes_forbidden_names_rule_only_when_given():
    event = _event(1, "a beat")
    with_names = build_event_prompt(event, "a beat", "TOG", forbidden_names=["Aelin"])
    assert "FORBIDDEN NAMES" in with_names
    assert "- Aelin" in with_names
    assert "FORBIDDEN NAMES" not in build_event_prompt(event, "a beat", "TOG")
