from wiki_creator.event_layer import _parse_chapter, _resolve, _names_in
from wiki_creator.registry import EntityRecord, Registry


def test_parse_chapter_variants():
    assert _parse_chapter("Ch04: eye contact and mutual smiles") == 4
    assert _parse_chapter("ch36: harmed by Cain") == 36
    assert _parse_chapter("C12: final duel") == 12
    assert _parse_chapter("Chapter 1") == 1
    assert _parse_chapter("no chapter here") is None
    assert _parse_chapter("") is None


def _registry(*records: EntityRecord) -> Registry:
    return Registry(entities=list(records))


CELAENA = EntityRecord(entity_id="celaena", canonical_name="Celaena Sardothien",
                       entity_type="PERSON", aliases=["Celaena Sardothien", "Celaena"])
CAIN = EntityRecord(entity_id="cain", canonical_name="Cain",
                    entity_type="PERSON", aliases=["Cain"])
RIFTHOLD = EntityRecord(entity_id="rifthold", canonical_name="Rifthold",
                        entity_type="PLACE", aliases=["Rifthold"])


def test_resolve_uses_registry_canonical():
    reg = _registry(CELAENA, CAIN, RIFTHOLD)
    assert _resolve("Celaena", reg) == "Celaena Sardothien"
    assert _resolve("Unknown", reg) == "Unknown"
    assert _resolve("Celaena", None) == "Celaena"


def test_names_in_matches_whole_words_by_type():
    reg = _registry(CELAENA, CAIN, RIFTHOLD)
    text = "Celaena defeats Cain in the arena at Rifthold"
    assert _names_in(text, reg, "PERSON") == ["Cain", "Celaena Sardothien"]
    assert _names_in(text, reg, "PLACE") == ["Rifthold"]
    assert _names_in("nothing here", reg, "PERSON") == []
    assert _names_in(text, None, "PERSON") == []


def test_salience_action_cue_and_position():
    from wiki_creator.event_layer import _salience

    cues = ["couronna", "vainquit", "tua"]
    # action cue + last chapter → high
    assert _salience("Celaena vainquit Cain", 12, 12, cues) == 1.0
    # action cue, early chapter → 0.5 + small position term
    assert _salience("Celaena vainquit Cain", 1, 12, cues) < 0.6
    # no cue, mid book → only the position term
    assert _salience("Celaena walks the corridor", 6, 12, cues) < 0.3
    # no cue, no chapters info → 0.0
    assert _salience("something", 0, 0, cues) == 0.0


from wiki_creator.event_layer import build_events


def test_build_events_from_summaries_and_key_moments():
    reg = _registry(CELAENA, CAIN, RIFTHOLD)
    summaries = {
        "Chapter 12": {
            "chapter_id": "C12.xhtml",
            "chapter_title": "Chapter 12",
            "summary_bullets": ["Celaena vainquit Cain at Rifthold"],
        },
    }
    relationships = [
        {"entity_a": "Celaena", "entity_b": "Cain",
         "key_moments": ["Ch12: Celaena vainquit Cain at Rifthold"]},
    ]
    events = build_events(summaries, relationships, reg, action_cues=["vainquit"])

    # same chapter + identical description → one merged event
    assert len(events) == 1
    e = events[0]
    assert e["chapter"] == 12
    assert e["participants"] == ["Cain", "Celaena Sardothien"]
    assert e["places"] == ["Rifthold"]
    assert e["outcome"] == "Celaena vainquit Cain at Rifthold"  # has action cue
    assert e["salience"] == 1.0
    assert len(e["source_bullets"]) == 2  # both sources merged
    assert e["event_id"] == "e_ch12_0"


def test_build_events_skips_beats_without_chapter():
    reg = _registry(CELAENA)
    relationships = [{"entity_a": "Celaena", "entity_b": "Cain",
                      "key_moments": ["no chapter marker here"]}]
    assert build_events({}, relationships, reg, action_cues=[]) == []


def test_build_events_degrades_gracefully_with_no_registry():
    # No relationships (so no entity_a/entity_b seed names) — participants and
    # places can only come from registry name-matching, which is unavailable
    # when registry is None.
    summaries = {
        "Chapter 3": {
            "chapter_id": "C03.xhtml",
            "chapter_title": "Chapter 3",
            "summary_bullets": ["Celaena vainquit Cain at Rifthold"],
        },
    }
    events = build_events(summaries, [], None, action_cues=["vainquit"])

    assert len(events) == 1
    e = events[0]
    assert e["chapter"] == 3
    # no registry → no name-matching, participants/places stay empty
    assert e["participants"] == []
    assert e["places"] == []
    assert e["outcome"] == "Celaena vainquit Cain at Rifthold"
    assert e["event_id"] == "e_ch3_0"


def test_build_events_tolerates_none_summaries_and_relationships():
    assert build_events(None, None, None, action_cues=[]) == []
