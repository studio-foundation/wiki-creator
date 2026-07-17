"""STU-551: affiliation is the faction a character belongs to at the end of the tome."""
import json
from pathlib import Path

CUE_WORDS = Path(__file__).resolve().parents[1] / "wiki_creator" / "cue_words"


def test_both_languages_declare_affiliation_markers():
    # The vocabulary is data, never a constant in a .py (CLAUDE.md).
    for lang in ("en", "fr"):
        cues = json.loads((CUE_WORDS / f"{lang}.json").read_text(encoding="utf-8"))
        assert cues["affiliation_markers"], f"{lang} has no affiliation_markers"
        assert all(isinstance(m, str) and m for m in cues["affiliation_markers"])


import pytest

from wiki_creator.entity_affiliation import (
    SNIPPETS_PER_ENTITY,
    parse_affiliation_verdict,
    roster_rows,
    select_affiliation_snippets,
)
from wiki_creator.roster import load_cache, render_roster, save_cache

MARKERS = ["joined", "loyal", "betrayed"]


def _snip(text, chapter_id):
    return {"text": text, "chapter_id": chapter_id}


def test_only_marker_bearing_snippets_are_kept():
    """Single-source, unlike `status`: no sentence proves "no affiliation", so
    there is no `alive`-analogue proved by lateness. A snippet with no marker
    can only confirm the character exists."""
    chosen = select_affiliation_snippets(
        [_snip("Eragon joined the Varden.", "ch10"), _snip("Eragon ate bread.", "ch11")],
        MARKERS,
    )
    assert [s["text"] for s in chosen] == ["Eragon joined the Varden."]


def test_marker_snippets_are_latest_first():
    """Latest-first is what makes the scalar mean "end of tome" — it absorbs an
    intra-tome switch without dating it."""
    chosen = select_affiliation_snippets(
        [_snip("Eragon joined the Empire.", "ch2"), _snip("Eragon joined the Varden.", "ch30")],
        MARKERS,
    )
    assert chosen[0]["text"] == "Eragon joined the Varden."


def test_snippets_are_capped():
    chosen = select_affiliation_snippets(
        [_snip(f"joined {i}", f"ch{i}") for i in range(20)], MARKERS
    )
    assert len(chosen) == SNIPPETS_PER_ENTITY


def test_no_markers_selects_nothing():
    """CLAUDE.md: an absent cue_words key degrades to an empty collection. No
    markers → no snippets → the slot is omitted. It must not crash."""
    assert select_affiliation_snippets([_snip("Eragon joined the Varden.", "ch1")], []) == []


def _rows():
    return roster_rows(
        [{"canonical_name": "Eragon", "aliases": []}],
        {"Eragon": [_snip("Eragon joined the Varden.", "ch10")]},
        MARKERS,
    )


def test_a_verdict_must_quote_the_entitys_own_snippet():
    """STU-539's rule. These novels are in the model's training data: without it,
    a verdict from its memory of the plot and one from this run's text are
    indistinguishable afterwards."""
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Eragon", "affiliation": "Varden",
                          "quote": "Eragon was crowned king of the Varden."}]},
        _rows(),
    )
    assert verdicts == {}


def test_the_value_must_appear_in_the_quote():
    """THE LOAD-BEARING RULE (STU-551). `status` returns an enum member, so
    verifying the quote verifies the verdict. `affiliation` returns a NAME, so
    the model can quote a real sentence and infer the wrong faction from it."""
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Eragon", "affiliation": "Empire",
                          "quote": "Eragon joined the Varden."}]},
        _rows(),
    )
    assert verdicts == {}


def test_a_grounded_verdict_survives():
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Eragon", "affiliation": "Varden",
                          "quote": "Eragon joined the Varden."}]},
        _rows(),
    )
    assert verdicts == {"Eragon": {"affiliation": "Varden", "quote": "Eragon joined the Varden."}}


def test_a_name_off_the_roster_is_rejected():
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Galbatorix", "affiliation": "Empire",
                          "quote": "Galbatorix led the Empire."}]},
        _rows(),
    )
    assert verdicts == {}


def test_typographic_quotes_match_a_straight_quoted_reply():
    """The 99a6a71 regression: the EPUB ships curly quotes, the model echoes
    straight ones. Inherited if _normalize is reimplemented instead of reused."""
    rows = roster_rows(
        [{"canonical_name": "Eragon", "aliases": []}],
        {"Eragon": [_snip("“I joined the Varden,” said Eragon.", "ch10")]},
        MARKERS,
    )
    verdicts = parse_affiliation_verdict(
        {"affiliation": [{"name": "Eragon", "affiliation": "Varden",
                          "quote": '"I joined the Varden," said Eragon.'}]},
        rows,
    )
    assert verdicts["Eragon"]["affiliation"] == "Varden"


@pytest.mark.parametrize("payload", ["not json", None, {}, {"affiliation": "a string"}, 42])
def test_unparseable_payloads_verdict_nothing(payload):
    assert parse_affiliation_verdict(payload, _rows()) == {}


def test_cache_is_keyed_on_the_roster_rows(tmp_path):
    """WIKI_MAX_CHAPTERS or any upstream extraction fix must not replay a verdict
    made for a different roster — STU-539's premise was measured false precisely
    because it was measured on a 5-chapter extraction."""
    cache = tmp_path / "entity_affiliation.json"
    verdicts = {"Eragon": {"affiliation": "Varden", "quote": "Eragon joined the Varden."}}
    save_cache(cache, _rows(), verdicts)
    assert load_cache(cache, _rows()) == verdicts

    other = roster_rows(
        [{"canonical_name": "Eragon", "aliases": []}],
        {"Eragon": [_snip("Eragon joined the Empire.", "ch10")]},
        MARKERS,
    )
    assert load_cache(cache, other) is None


def test_render_roster_shows_names_aliases_and_snippets():
    rendered = render_roster(
        roster_rows(
            [{"canonical_name": "Eragon", "aliases": ["Shadeslayer"]}],
            {"Eragon": [_snip("Eragon joined the Varden.", "ch10")]},
            MARKERS,
        )
    )
    assert "## Eragon (also called: Shadeslayer)" in rendered
    assert "- Eragon joined the Varden." in rendered


import json as _json
from unittest.mock import patch

from scripts.entity_affiliation import resolve_affiliation


def _ok_payload():
    class _Ok:
        returncode = 0
        stdout = _json.dumps({
            "stages": [{
                "stage_name": "entity-affiliation-item",
                "status": "success",
                "output": {"affiliation": [
                    {"name": "Eragon", "affiliation": "Varden",
                     "quote": "Eragon joined the Varden."}
                ]},
            }]
        })
        stderr = ""
    return _Ok()


def test_resolve_caches_and_does_not_call_twice(tmp_path):
    cache = tmp_path / "entity_affiliation.json"
    with patch("scripts.entity_affiliation.subprocess.run", return_value=_ok_payload()):
        first = resolve_affiliation(_rows(), "Eragon", cache)
    assert first["Eragon"]["affiliation"] == "Varden"

    with patch("scripts.entity_affiliation.subprocess.run") as run:
        second = resolve_affiliation(_rows(), "Eragon", cache)
    run.assert_not_called()
    assert second == first


@pytest.mark.parametrize("boom", [FileNotFoundError, __import__("subprocess").TimeoutExpired("studio", 1)])
def test_every_failure_path_omits_the_slot_for_everyone(tmp_path, boom):
    """THE LOAD-BEARING TEST. A false affiliation puts a character in the wrong
    army on a page nobody will reread; an absent one says nothing. The run must
    never fail."""
    cache = tmp_path / "entity_affiliation.json"
    with patch("scripts.entity_affiliation.subprocess.run", side_effect=boom):
        assert resolve_affiliation(_rows(), "Eragon", cache) == {}


def test_a_nonzero_exit_omits_the_slot_for_everyone(tmp_path):
    class _Fail:
        returncode = 1
        stdout = ""
        stderr = "boom"
    cache = tmp_path / "entity_affiliation.json"
    with patch("scripts.entity_affiliation.subprocess.run", return_value=_Fail()):
        assert resolve_affiliation(_rows(), "Eragon", cache) == {}


def test_a_stale_cache_from_another_roster_is_deleted_not_replayed(tmp_path):
    """wiki_preparation.load_affiliation_verdicts is roster-blind, so a give-up
    path that left the old artifact in place would let it replay a verdict made
    for a different roster."""
    cache = tmp_path / "entity_affiliation.json"
    save_cache(cache, _rows(), {"Eragon": {"affiliation": "Varden", "quote": "x"}})
    other = roster_rows(
        [{"canonical_name": "Murtagh", "aliases": []}],
        {"Murtagh": [_snip("Murtagh joined the Empire.", "ch40")]},
        MARKERS,
    )
    with patch("scripts.entity_affiliation.subprocess.run", side_effect=FileNotFoundError):
        assert resolve_affiliation(other, "Eragon", cache) == {}
    assert not cache.exists()


from scripts.generate_wiki_pages import _extracted_fact_value
from scripts.wiki_preparation import build_entity_bundle, load_affiliation_verdicts


def test_the_binder_renders_affiliation_from_the_batch_entity():
    assert _extracted_fact_value({"affiliation": "Varden"}, "affiliation", "fr") == "Varden"


def test_an_unstamped_entity_renders_no_affiliation():
    # OPT with no declared fallback: _bind_batch_fields omits a falsy value.
    assert _extracted_fact_value({}, "affiliation", "fr") is None
    assert _extracted_fact_value({"affiliation": ""}, "affiliation", "fr") is None


def test_preparation_stamps_affiliation_onto_the_batch_entity():
    bundle = build_entity_bundle(
        entity={"canonical_name": "Eragon", "type": "PERSON", "importance": "principal"},
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={},
        affiliation_verdicts={"Eragon": {"affiliation": "Varden", "quote": "x"}},
    )
    assert bundle["affiliation"] == "Varden"


def test_preparation_stamps_nothing_for_an_undecided_character():
    bundle = build_entity_bundle(
        entity={"canonical_name": "Murtagh", "type": "PERSON", "importance": "secondary"},
        relationships=[],
        persons={}, places={}, orgs={}, events={},
        entities_by_name={},
        affiliation_verdicts={},
    )
    assert bundle["affiliation"] is None


def test_load_affiliation_verdicts_degrades_on_an_absent_artifact(tmp_path):
    # A book that never ran the stage is not an error.
    assert load_affiliation_verdicts(tmp_path) == {}


def test_person_declares_the_affiliation_slot():
    from wiki_creator.page_templates import load_base_template
    person = load_base_template()["entity_types"]["PERSON"]
    slots = {s["token"]: s for s in person["infobox"]}
    assert slots["affiliation"]["provenance"] == "extracted-fact"
    assert slots["affiliation"]["obligation"] == "OPT"
