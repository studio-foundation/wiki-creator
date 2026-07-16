import json

from wiki_creator.alias_adjudication import (
    SNIPPETS_PER_ENTITY,
    load_cached_merges,
    parse_merge_verdict,
    render_roster,
    roster_rows,
    save_merge_cache,
    select_snippets,
)


def _entity(name, aliases=()):
    return {"canonical_name": name, "type": "PERSON", "aliases": list(aliases) or [name]}


# --- select_snippets ---


def test_a_snippet_naming_nobody_else_is_dropped():
    """A sentence naming only its own entity can confirm the entity exists, nothing more."""
    kept = select_snippets(
        ["Celaena walked alone.", "Celaena bowed to Dorian."],
        own_names={"Celaena"},
        roster_names={"Celaena", "Dorian"},
    )
    assert kept == ["Celaena bowed to Dorian."]


def test_snippets_naming_more_characters_rank_first():
    snippets = ["Lillian saw Dorian.", "Lillian Gordaina was Celaena Sardothien, said Dorian."]
    kept = select_snippets(
        snippets,
        own_names={"Lillian", "Lillian Gordaina"},
        roster_names={"Lillian", "Lillian Gordaina", "Celaena Sardothien", "Dorian"},
    )
    assert kept[0] == "Lillian Gordaina was Celaena Sardothien, said Dorian."


def test_selection_is_capped():
    snippets = [f"Celaena met Dorian, day {i}." for i in range(20)]
    kept = select_snippets(snippets, own_names={"Celaena"}, roster_names={"Celaena", "Dorian"})
    assert len(kept) == SNIPPETS_PER_ENTITY


def test_an_alias_of_the_entity_does_not_count_as_another_character():
    kept = select_snippets(
        ["Lady Lillian is Lillian Gordaina."],
        own_names={"Lillian Gordaina", "Lady Lillian"},
        roster_names={"Lillian Gordaina", "Lady Lillian", "Dorian"},
    )
    assert kept == []


# --- roster_rows / render_roster ---


def test_rows_carry_aliases_and_selected_snippets():
    entities = [_entity("Celaena Sardothien", ["Celaena Sardothien", "Celaena"]), _entity("Dorian")]
    rows = roster_rows(
        entities,
        {"Celaena Sardothien": ["Celaena greeted Dorian."], "Dorian": ["Dorian left."]},
    )
    assert rows[0] == {
        "name": "Celaena Sardothien",
        "aliases": ["Celaena"],
        "snippets": ["Celaena greeted Dorian."],
    }
    assert rows[1]["snippets"] == []


def test_render_names_every_roster_entry_as_a_heading():
    rows = [{"name": "Celaena", "aliases": ["Sardothien"], "snippets": ["Celaena met Dorian."]}]
    rendered = render_roster(rows)
    assert "## Celaena (also called: Sardothien)" in rendered
    assert "- Celaena met Dorian." in rendered


# --- parse_merge_verdict ---


def _rows():
    return [
        {
            "name": "Celaena Sardothien",
            "aliases": [],
            "snippets": ["Lillian Gordaina was Celaena Sardothien, the world's most notorious assassin."],
        },
        {"name": "Lillian Gordaina", "aliases": [], "snippets": ["Kaltain watched Lillian Gordaina dance."]},
        {"name": "Dorian", "aliases": [], "snippets": ["Dorian watched Celaena Sardothien."]},
    ]


def _verdict(**entry):
    return {"merge": [entry]}


def test_a_quote_grounded_in_the_snippets_is_kept():
    verdict = _verdict(
        a="Celaena Sardothien",
        b="Lillian Gordaina",
        quote="Lillian Gordaina was Celaena Sardothien",
        reason="cover identity",
    )
    assert parse_merge_verdict(verdict, _rows()) == [
        {
            "a": "Celaena Sardothien",
            "b": "Lillian Gordaina",
            "quote": "Lillian Gordaina was Celaena Sardothien",
            "reason": "cover identity",
        }
    ]


def test_a_quote_absent_from_the_snippets_is_discarded():
    """The model has read these novels; a merge it cannot ground in this run's text
    comes from its memory of the plot, and nothing downstream could tell the difference."""
    verdict = _verdict(
        a="Celaena Sardothien",
        b="Dorian",
        quote="Dorian is secretly Celaena",
        reason="invented",
    )
    assert parse_merge_verdict(verdict, _rows()) == []


def test_quote_matching_ignores_whitespace_and_case():
    verdict = _verdict(
        a="Celaena Sardothien",
        b="Lillian Gordaina",
        quote="lillian gordaina   was\nCelaena Sardothien",
        reason="cover identity",
    )
    assert len(parse_merge_verdict(verdict, _rows())) == 1


def test_a_name_absent_from_the_roster_is_discarded():
    verdict = _verdict(
        a="Celaena Sardothien",
        b="Elentiya",
        quote="Lillian Gordaina was Celaena Sardothien",
        reason="hallucinated",
    )
    assert parse_merge_verdict(verdict, _rows()) == []


def test_a_merge_without_a_quote_is_discarded():
    verdict = _verdict(a="Celaena Sardothien", b="Lillian Gordaina", quote="", reason="obvious")
    assert parse_merge_verdict(verdict, _rows()) == []


def test_the_same_pair_twice_is_returned_once():
    payload = {
        "merge": [
            {"a": "Celaena Sardothien", "b": "Lillian Gordaina", "quote": "was Celaena Sardothien", "reason": "x"},
            {"a": "Lillian Gordaina", "b": "Celaena Sardothien", "quote": "was Celaena Sardothien", "reason": "x"},
        ]
    }
    assert len(parse_merge_verdict(payload, _rows())) == 1


def test_a_json_string_reply_is_parsed():
    verdict = json.dumps(
        _verdict(
            a="Celaena Sardothien",
            b="Lillian Gordaina",
            quote="Lillian Gordaina was Celaena Sardothien",
            reason="cover identity",
        )
    )
    assert len(parse_merge_verdict(verdict, _rows())) == 1


def test_an_unparseable_reply_merges_nothing():
    for payload in ("not json", None, [], {"drop": []}, {"merge": "everything"}, {"merge": ["x"]}):
        assert parse_merge_verdict(payload, _rows()) == []


# --- cache ---


def test_cache_round_trips(tmp_path):
    path = tmp_path / "alias_adjudication.json"
    rows = _rows()
    merges = [{"a": "Celaena Sardothien", "b": "Lillian Gordaina", "quote": "q", "reason": "r"}]
    save_merge_cache(path, rows, merges)
    assert load_cached_merges(path, rows) == merges


def test_a_verdict_for_a_different_roster_is_not_replayed(tmp_path):
    """WIKI_MAX_CHAPTERS and every upstream extraction fix reshape the roster."""
    path = tmp_path / "alias_adjudication.json"
    save_merge_cache(path, _rows(), [])
    assert load_cached_merges(path, _rows()[:2]) is None


def test_a_missing_cache_is_not_an_error(tmp_path):
    assert load_cached_merges(tmp_path / "absent.json", _rows()) is None
