from wiki_creator.collation import (
    DEFAULT_MODE,
    collation_config,
    collation_labels,
    collective_pages,
    partition,
)


def _entity(name, importance="figurant", entity_type="PERSON", **extra):
    return {"canonical_name": name, "importance": importance, "type": entity_type, **extra}


def _collective_cfg(**tier):
    return {"generation": {"collation": {"figurant": {"mode": "collective", **tier}}}}


def test_config_absent_leaves_every_tier_dedicated():
    assert collation_config({}) == {}
    dedicated, collective, dropped = partition(
        [_entity("Extra"), _entity("Celaena", "principal")], collation_config({}), []
    )
    assert [e["canonical_name"] for e in dedicated] == ["Extra", "Celaena"]
    assert collective == [] and dropped == []


def test_unknown_mode_falls_back_to_dedicated():
    config = collation_config({"generation": {"collation": {"figurant": {"mode": "banish"}}}})
    assert config["figurant"].mode == DEFAULT_MODE


def test_collective_mode_moves_figurants_off_dedicated():
    config = collation_config(_collective_cfg())
    dedicated, collective, dropped = partition(
        [_entity("Extra"), _entity("Celaena", "principal")], config, []
    )
    assert [e["canonical_name"] for e in dedicated] == ["Celaena"]
    assert [e["canonical_name"] for e in collective] == ["Extra"]
    assert dropped == []


def test_drop_mode_removes_the_tier_entirely():
    config = collation_config({"generation": {"collation": {"figurant": {"mode": "drop"}}}})
    dedicated, collective, dropped = partition([_entity("Extra")], config, [])
    assert dedicated == [] and collective == []
    assert [e["canonical_name"] for e in dropped] == ["Extra"]


def test_promote_if_keeps_a_salient_figurant_dedicated():
    config = collation_config(
        _collective_cfg(promote_if={"appears_in_event_salience_above": 0.7})
    )
    events = [
        {"participants": ["Nehemia"], "salience": 0.9},
        {"participants": ["Extra"], "salience": 0.2},
    ]
    dedicated, collective, _ = partition(
        [_entity("Nehemia"), _entity("Extra")], config, events
    )
    assert [e["canonical_name"] for e in dedicated] == ["Nehemia"]
    assert [e["canonical_name"] for e in collective] == ["Extra"]


def test_promote_if_matches_places_too():
    config = collation_config(
        _collective_cfg(promote_if={"appears_in_event_salience_above": 0.7})
    )
    events = [{"participants": [], "places": ["Endovier"], "salience": 0.9}]
    dedicated, collective, _ = partition(
        [_entity("Endovier", entity_type="PLACE")], config, events
    )
    assert [e["canonical_name"] for e in dedicated] == ["Endovier"]
    assert collective == []


def test_promote_if_absent_never_promotes():
    config = collation_config(_collective_cfg())
    events = [{"participants": ["Extra"], "salience": 1.0}]
    dedicated, collective, _ = partition([_entity("Extra")], config, events)
    assert dedicated == []
    assert [e["canonical_name"] for e in collective] == ["Extra"]


def test_collective_pages_group_by_entity_type_and_sort_entries():
    pages = collective_pages(
        [
            _entity("Verin", total_mentions=4, chapters_present=2),
            _entity("Cain", total_mentions=3, chapters_present=1, aliases=["The Champion"]),
            _entity("Endovier", entity_type="PLACE", total_mentions=5, chapters_present=3),
        ],
        collation_labels({}),
    )
    assert [p["title"] for p in pages] == ["Personnages mineurs", "Lieux mineurs"]
    persons = pages[0]
    assert persons["entity_type"] == "COLLATION"
    assert persons["infobox_fields"] == {}
    assert persons["content"].index("## Cain") < persons["content"].index("## Verin")
    assert "*Alias : The Champion*" in persons["content"]
    assert "Mentionné 4 fois dans 2 chapitre(s)." in persons["content"]


def test_collective_pages_titles_come_from_export_labels():
    pages = collective_pages(
        [_entity("Verin")],
        collation_labels({"categories": {"labels": {"minor_persons": "Minor Characters"}}}),
    )
    assert [p["title"] for p in pages] == ["Minor Characters"]


def test_collective_pages_empty_input_yields_nothing():
    assert collective_pages([], collation_labels({})) == []
