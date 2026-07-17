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
