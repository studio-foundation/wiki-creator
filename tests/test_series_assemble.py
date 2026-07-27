"""Cross-tome series assembly (STU-668) — pure logic, no disk/LLM.

Covers the two web-verifiable pieces: the identity-joined cross-tome gather +
latest-wins notability/status reconciliation (wiki_creator/series.py), and the
tome-axis collapsible primitive (wiki_creator/spoiler_blocks.py).
"""
import json

from wiki_creator.registry import Registry
from wiki_creator.series import (
    TomeArtifacts,
    TomeContribution,
    build_series_characters,
    load_tome_artifacts,
    reconcile_importance,
    reconcile_status,
)
from wiki_creator.spoiler_blocks import tome_collapsible_section


def _registry(entities: list[dict]) -> Registry:
    return Registry.from_dict({"version": 1, "entities": entities, "decisions": [], "warnings": []})


def _page(title: str, importance: str = "secondary") -> dict:
    return {"title": title, "importance": importance, "entity_type": "PERSON"}


def _contrib(book_id: str, importance: str | None = None, status: dict | None = None):
    page = _page("X", importance) if importance is not None else None
    return TomeContribution(book_id=book_id, tome_number=book_id, page=page, status=status)


# --- reconciliation --------------------------------------------------------

def test_importance_latest_wins():
    contribs = [_contrib("01", "figurant"), _contrib("05", "principal")]
    assert reconcile_importance(contribs) == "principal"


def test_importance_latest_wins_even_when_it_demotes():
    # State at the furthest reading position wins, not the max tier ever held.
    contribs = [_contrib("01", "principal"), _contrib("05", "figurant")]
    assert reconcile_importance(contribs) == "figurant"


def test_importance_skips_tomes_without_a_page():
    contribs = [_contrib("01", "principal"), _contrib("05", None)]
    assert reconcile_importance(contribs) == "principal"


def test_importance_defaults_figurant_when_untyped():
    assert reconcile_importance([_contrib("01", None)]) == "figurant"
    assert reconcile_importance([]) == "figurant"


def test_status_latest_wins():
    early = {"status": "alive", "quote": "a"}
    late = {"status": "deceased", "quote": "b"}
    contribs = [_contrib("01", "principal", early), _contrib("05", "principal", late)]
    assert reconcile_status(contribs) == late


def test_status_none_when_no_verdict():
    assert reconcile_status([_contrib("01", "principal", None)]) is None


# --- cross-tome gather -----------------------------------------------------

def test_gather_merges_one_character_across_tomes():
    reg = _registry([
        {"entity_id": "gavriel", "canonical_name": "Gavriel", "entity_type": "PERSON", "aliases": []},
    ])
    tomes = [
        TomeArtifacts("02-tome", pages=[_page("Gavriel", "secondary")],
                      status_verdicts={"Gavriel": {"status": "alive", "quote": "q"}}),
        TomeArtifacts("05-tome", pages=[_page("Gavriel", "principal")],
                      status_verdicts={"Gavriel": {"status": "deceased", "quote": "q2"}}),
    ]
    chars = build_series_characters(reg, tomes)
    assert len(chars) == 1
    char = chars[0]
    assert char.canonical_name == "Gavriel"
    assert char.books == ["02-tome", "05-tome"]
    assert char.importance == "principal"          # latest-wins
    assert char.status == {"status": "deceased", "quote": "q2"}
    assert [c.tome_number for c in char.contributions] == ["2", "5"]


def test_gather_joins_by_alias_when_a_tome_renamed_the_character():
    # The registry canonical is a later-tome name; the earlier tome's page title
    # is only an alias. Identity must still join through the alias union.
    reg = _registry([
        {"entity_id": "e", "canonical_name": "Celaena Sardothien",
         "entity_type": "PERSON", "aliases": ["Aelin"]},
    ])
    tomes = [
        TomeArtifacts("01", pages=[_page("Celaena Sardothien", "principal")]),
        TomeArtifacts("03", pages=[_page("Aelin", "principal")]),
    ]
    chars = build_series_characters(reg, tomes)
    assert len(chars) == 1
    assert chars[0].books == ["01", "03"]


def test_gather_skips_non_person_entities():
    reg = _registry([
        {"entity_id": "p", "canonical_name": "Rifthold", "entity_type": "PLACE", "aliases": []},
    ])
    tomes = [TomeArtifacts("01", pages=[_page("Rifthold")])]
    assert build_series_characters(reg, tomes) == []


def test_gather_skips_characters_with_no_page_anywhere():
    # A registry entity that only ever has a status verdict, never a page, is not
    # a renderable character.
    reg = _registry([
        {"entity_id": "ghost", "canonical_name": "Ghost", "entity_type": "PERSON", "aliases": []},
    ])
    tomes = [TomeArtifacts("01", status_verdicts={"Ghost": {"status": "deceased", "quote": "q"}})]
    assert build_series_characters(reg, tomes) == []


def test_gather_matches_events_by_participant():
    reg = _registry([
        {"entity_id": "g", "canonical_name": "Gavriel", "entity_type": "PERSON", "aliases": []},
    ])
    ev = {"event_id": "e1", "chapter": 4, "description": "d", "participants": ["Gavriel", "Aedion"]}
    tomes = [TomeArtifacts("05", pages=[_page("Gavriel")], events=[ev, {"participants": ["Other"]}])]
    chars = build_series_characters(reg, tomes)
    assert chars[0].contributions[0].events == [ev]


# --- disk loader -----------------------------------------------------------

def test_load_tome_artifacts_reads_the_three_files(tmp_path):
    (tmp_path / "wiki_pages.json").write_text(json.dumps({"pages": [_page("Gavriel")]}))
    (tmp_path / "entity_status.json").write_text(
        json.dumps({"verdicts": {"Gavriel": {"status": "alive", "quote": "q"}}})
    )
    (tmp_path / "events.json").write_text(json.dumps({"events": [{"event_id": "e"}]}))
    art = load_tome_artifacts(tmp_path, "05-tome")
    assert art.book_id == "05-tome"
    assert art.pages[0]["title"] == "Gavriel"
    assert art.status_verdicts["Gavriel"]["status"] == "alive"
    assert art.events == [{"event_id": "e"}]


def test_load_tome_artifacts_tolerates_missing_files(tmp_path):
    art = load_tome_artifacts(tmp_path, "01")
    assert art.pages == [] and art.status_verdicts == {} and art.events == []


# --- tome-axis collapsible -------------------------------------------------

def test_tome_collapsible_section_wraps_a_heading():
    out = tome_collapsible_section("Book 5", "He returns.", "Book 5 — reveal", "Hide")
    assert out.startswith('<div class="mw-collapsible mw-collapsed" ')
    assert 'data-expandtext="Book 5 — reveal"' in out
    assert 'data-collapsetext="Hide"' in out
    assert "== Book 5 ==\n\nHe returns." in out
    assert out.rstrip().endswith("</div>")
