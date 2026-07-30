"""Cross-tome series assembly (STU-668) — pure logic, no disk/LLM.

Covers the two web-verifiable pieces: the identity-joined cross-tome gather +
latest-wins notability/status reconciliation (wiki_creator/series.py), and the
tome-axis collapsible primitive (wiki_creator/spoiler_blocks.py).
"""
import json

from wiki_creator.canonicalize import canonical_key
from wiki_creator.registry import Registry
from wiki_creator.series import (
    TomeArtifacts,
    TomeContribution,
    build_series_characters,
    link_targets,
    load_tome_artifacts,
    reconcile_importance,
    reconcile_status,
)
from wiki_creator.spoiler_blocks import tome_collapsible_section


def _registry(entities: list[dict]) -> Registry:
    return Registry.from_dict({"version": 1, "entities": entities, "decisions": [], "warnings": []})


def _page(title: str, importance: str = "secondary", entity_type: str = "PERSON") -> dict:
    return {"title": title, "importance": importance, "entity_type": entity_type}


def _contrib(book_id: str, importance: str | None = None, status: dict | None = None):
    page = _page("X", importance) if importance is not None else None
    return TomeContribution(book_id=book_id, tome_number=book_id, page=page, status=status)


# --- reconciliation --------------------------------------------------------

def test_importance_promotes_to_the_highest_tier_reached():
    contribs = [_contrib("01", "figurant"), _contrib("05", "principal")]
    assert reconcile_importance(contribs) == "principal"


def test_importance_survives_a_later_demotion():
    # STU-719: unlike Status, notability is not latest-wins — a principal of book 1
    # who walks on in book 6 is still a main character of the series.
    contribs = [_contrib("01", "principal"), _contrib("05", "figurant")]
    assert reconcile_importance(contribs) == "principal"


def test_importance_ignores_an_unknown_tier():
    assert reconcile_importance([_contrib("01", "vedette"), _contrib("05", "secondary")]) == "secondary"


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


def test_gather_merges_non_person_entities():
    # STU-706: all types merge cross-tome, not just PERSON.
    reg = _registry([
        {"entity_id": "p", "canonical_name": "Rifthold", "entity_type": "PLACE", "aliases": []},
    ])
    tomes = [
        TomeArtifacts("01", pages=[_page("Rifthold", entity_type="PLACE")]),
        TomeArtifacts("03", pages=[_page("Rifthold", entity_type="PLACE")]),
    ]
    chars = build_series_characters(reg, tomes)
    assert len(chars) == 1
    assert chars[0].entity_type == "PLACE"
    assert chars[0].books == ["01", "03"]


def test_non_person_status_is_gated():
    # STU-706: status (alive/dead) is PERSON-only. A non-PERSON whose name collides
    # with a status verdict must not pick it up.
    reg = _registry([
        {"entity_id": "p", "canonical_name": "Rifthold", "entity_type": "PLACE", "aliases": []},
    ])
    tomes = [TomeArtifacts("01", pages=[_page("Rifthold", entity_type="PLACE")],
                           status_verdicts={"Rifthold": {"status": "deceased", "quote": "q"}})]
    chars = build_series_characters(reg, tomes)
    assert chars[0].status is None
    assert all(c.status is None for c in chars[0].contributions)


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


# --- cross-tome canonicalization (STU-719) ---------------------------------

def test_gather_merges_spelling_variants_of_one_character():
    # The registry accumulates on normalize_name (case + accents), so two tomes
    # spelling the same character differently reach the merge as two records.
    reg = _registry([
        {"entity_id": "saw_horse", "canonical_name": "Saw-Horse", "entity_type": "PERSON",
         "aliases": ["Saw-Horse"]},
        {"entity_id": "sawhorse", "canonical_name": "Sawhorse", "entity_type": "PERSON",
         "aliases": ["Sawhorse"]},
    ])
    tomes = [
        TomeArtifacts("02", pages=[_page("Saw-Horse", "secondary")]),
        TomeArtifacts("04", pages=[_page("Sawhorse", "figurant")]),
    ]
    chars = build_series_characters(reg, tomes)
    assert len(chars) == 1
    assert chars[0].books == ["02", "04"]


def test_gather_matches_a_status_verdict_on_the_canonical_key():
    # STU-724: the verdict is keyed by the roster name the tome wrote, which is
    # not always the spelling the registry kept.
    reg = _registry([
        {"entity_id": "b", "canonical_name": "Billina", "entity_type": "PERSON", "aliases": []},
    ])
    verdict = {"status": "alive", "quote": "q"}
    tomes = [TomeArtifacts("01", pages=[_page("Billina")], status_verdicts={"BILLINA": verdict})]
    assert build_series_characters(reg, tomes)[0].status == verdict


def test_gather_prefers_a_cased_spelling_over_a_shouty_one():
    reg = _registry([
        {"entity_id": "billina", "canonical_name": "BILLINA", "entity_type": "PERSON",
         "aliases": ["BILLINA", "Billina", "Yellow Hen"]},
    ])
    chars = build_series_characters(reg, [TomeArtifacts("03", pages=[_page("BILLINA")])])
    assert chars[0].canonical_name == "Billina"


def test_gather_folds_a_leading_article_when_the_language_declares_it():
    reg = _registry([
        {"entity_id": "shaggy", "canonical_name": "Shaggy Man", "entity_type": "PERSON",
         "aliases": ["Shaggy Man"]},
        {"entity_id": "the_shaggy", "canonical_name": "THE shaggy man", "entity_type": "PERSON",
         "aliases": ["THE shaggy man"]},
    ])
    tomes = [
        TomeArtifacts("05", pages=[_page("THE shaggy man")]),
        TomeArtifacts("06", pages=[_page("Shaggy Man")]),
    ]
    assert len(build_series_characters(reg, tomes)) == 2          # no article vocabulary
    chars = build_series_characters(reg, tomes, determiners=["the"])
    assert len(chars) == 1
    assert chars[0].canonical_name == "Shaggy Man"


def test_gather_keeps_a_homonym_of_another_type_distinct():
    # STU-506: a PERSON and a PLACE sharing a name are not one entity.
    reg = _registry([
        {"entity_id": "p", "canonical_name": "Emperor", "entity_type": "PERSON", "aliases": []},
        {"entity_id": "l", "canonical_name": "Emperor", "entity_type": "PLACE", "aliases": []},
    ])
    tomes = [TomeArtifacts("01", pages=[
        _page("Emperor", entity_type="PERSON"), _page("Emperor", entity_type="PLACE"),
    ])]
    assert len(build_series_characters(reg, tomes)) == 2


def test_gather_drops_a_generic_role_but_keeps_a_qualified_one():
    # 'Queen' is Ev's queen in one tome and Oz's in another — one merged page for
    # both would be a fiction. 'Nome King' is one character and must survive.
    reg = _registry([
        {"entity_id": "queen", "canonical_name": "Queen", "entity_type": "PERSON", "aliases": []},
        {"entity_id": "nome", "canonical_name": "Nome King", "entity_type": "PERSON", "aliases": []},
        {"entity_id": "gates", "canonical_name": "Guardian of the Gates",
         "entity_type": "PERSON", "aliases": []},
    ])
    tomes = [TomeArtifacts("01", pages=[
        _page("Queen"), _page("Nome King"), _page("Guardian of the Gates"),
    ])]
    names = [c.canonical_name for c in build_series_characters(
        reg, tomes, role_words=["king", "queen", "guardian of the gates"],
        determiners=["the"], connectors=["of", "the"],
    )]
    assert names == ["Nome King"]


def test_no_role_vocabulary_drops_nothing():
    reg = _registry([
        {"entity_id": "queen", "canonical_name": "Queen", "entity_type": "PERSON", "aliases": []},
    ])
    chars = build_series_characters(reg, [TomeArtifacts("01", pages=[_page("Queen")])])
    assert [c.canonical_name for c in chars] == ["Queen"]


def test_link_targets_map_every_tome_surface_to_the_series_page():
    reg = _registry([
        {"entity_id": "tw", "canonical_name": "Tin Woodman", "entity_type": "PERSON",
         "aliases": ["Nick Chopper", "The Tin Woodman", "Tin Woodman"]},
        {"entity_id": "queen", "canonical_name": "Queen", "entity_type": "PERSON",
         "aliases": ["Queen", "Queen of Ev"]},
    ])
    tomes = [TomeArtifacts("01", pages=[_page("Tin Woodman"), _page("Queen")])]
    kwargs = {"role_words": ["queen"], "determiners": ["the"]}
    chars = build_series_characters(reg, tomes, **kwargs)
    targets = link_targets(reg, chars, **kwargs)
    assert targets[canonical_key("Nick Chopper")] == "Tin Woodman"
    assert targets[canonical_key("THE TIN WOODMAN", ["the"])] == "Tin Woodman"
    # A dropped generic role maps to "" — the renderer unlinks instead of red-linking.
    # Every surface of the dropped entity, including the ones that read like a name.
    assert targets[canonical_key("Queen")] == ""
    assert targets[canonical_key("Queen of Ev")] == ""
    assert canonical_key("Ozma") not in targets


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
