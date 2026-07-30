"""Series character page render (STU-668) — golden on a synthetic 2-tome fixture.

Pure logic, LLM-free: hand-authored per-tome artifacts → build_series_characters
→ render_series_character_page, compared byte-for-byte to a committed .wiki golden.

    UPDATE_GOLDENS=1 python -m pytest tests/test_series_render.py -q
"""
import os
from pathlib import Path

from wiki_creator.export_helpers import category_labels
from wiki_creator.registry import Registry
from wiki_creator.series import TomeArtifacts, build_series_characters, link_targets
from wiki_creator.series_pages import render_series_character_page

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "series"
UPDATE_GOLDENS = os.environ.get("UPDATE_GOLDENS") == "1"


def _fixture() -> list:
    registry = Registry.from_dict({
        "version": 1,
        "entities": [
            {
                "entity_id": "gavriel", "canonical_name": "Gavriel",
                "entity_type": "PERSON", "aliases": ["The Lion"],
                "books": ["01-heir", "02-crown"],
            },
            # Renamed across tomes: registry canonical is the tome-2 name, the
            # tome-1 page title is only an alias — identity must still join.
            {
                "entity_id": "celaena", "canonical_name": "Aelin Galathynius",
                "entity_type": "PERSON", "aliases": ["Celaena Sardothien"],
                "books": ["01-heir", "02-crown"],
            },
            {"entity_id": "castle", "canonical_name": "Glass Castle",
             "entity_type": "PLACE", "aliases": []},
        ],
        "decisions": [], "warnings": [],
    })
    tome1 = TomeArtifacts(
        book_id="01-heir",
        title="Throne of Glass",
        pages=[
            {"title": "Gavriel", "importance": "secondary", "entity_type": "PERSON",
             "content": "## Biography\n\nA warrior of the Cadre.\n\n## Personality\n\nProud and haunted.\n\n## Relationships\n\n**[[Aedion]]** — his son, unknown to him.",
             "relationship_index": ["* [[Aedion]] — family (ch.10)"]},
            {"title": "Celaena Sardothien", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nAn assassin in Rifthold.",
             "relationship_index": ["* [[Chaol]] — romance (ch.5→ch.30)"]},
            {"title": "Glass Castle", "importance": "secondary", "entity_type": "PLACE",
             "content": "## Overview\n\nThe royal seat of Adarlan."},
        ],
        # A verdict keyed on the PLACE name must be ignored (status is PERSON-only).
        status_verdicts={"Gavriel": {"status": "alive", "quote": "Gavriel lived."},
                         "Glass Castle": {"status": "deceased", "quote": "nope"}},
    )
    tome2 = TomeArtifacts(
        book_id="02-crown",
        title="Crown of Midnight",
        pages=[
            {"title": "Gavriel", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nHe joins the war.\n\n## Personality\n\nWeary but resolute.\n\n## Relationships\n\n**[[Aedion]]** — reunited at last.",
             "relationship_index": ["* [[Aedion]] — family (ch.3→ch.20)"]},
            {"title": "Aelin Galathynius", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nQueen of Terrasen.",
             "relationship_index": ["* [[Chaol]] — romance (ch.5→ch.30)", "* [[Rowan]] — romance (ch.40)"]},
            {"title": "Glass Castle", "importance": "secondary", "entity_type": "PLACE",
             "content": "## Overview\n\nShattered in the siege."},
        ],
        status_verdicts={"Gavriel": {"status": "deceased", "quote": "Gavriel fell.", "agent": "Aelin Galathynius"}},
        events=[{"event_id": "e1", "chapter": 22, "description": "Gavriel dies shielding the army.",
                 "participants": ["Gavriel"]}],
    )
    return build_series_characters(registry, [tome1, tome2])


def _assert_golden(name: str, actual: str) -> None:
    path = GOLDEN_DIR / name
    if UPDATE_GOLDENS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"golden missing: {path} — regenerate with UPDATE_GOLDENS=1"
    assert actual == path.read_text(encoding="utf-8"), (
        f"render drifted from golden {name}; if intentional rerun UPDATE_GOLDENS=1"
    )


def test_series_character_pages_match_golden():
    chars = _fixture()
    labels = category_labels({}, "en")
    by_name = {c.canonical_name: c for c in chars}

    assert set(by_name) == {"Gavriel", "Aelin Galathynius", "Glass Castle"}  # all types (STU-706)

    _, gavriel = render_series_character_page(by_name["Gavriel"], labels, lang="en")
    _assert_golden("gavriel.wiki", gavriel)

    _, aelin = render_series_character_page(by_name["Aelin Galathynius"], labels, lang="en")
    _assert_golden("aelin.wiki", aelin)

    _, castle = render_series_character_page(by_name["Glass Castle"], labels, lang="en")
    _assert_golden("glass_castle.wiki", castle)


def test_non_person_page_has_no_status_row():
    # STU-706: a PLACE merges cross-tome but carries no alive/dead status slot,
    # even when a status verdict collides with its name.
    chars = _fixture()
    castle = next(c for c in chars if c.canonical_name == "Glass Castle")
    relpath, wiki = render_series_character_page(castle, category_labels({}, "en"), lang="en")

    assert relpath == "locations/Glass_Castle.wiki"
    assert castle.status is None
    assert "Deceased" not in wiki and "status" not in wiki.lower()
    # still a real cross-tome page: one collapsible section per tome, headed by its title
    assert "== Throne of Glass ==" in wiki and "== Crown of Midnight ==" in wiki


def test_gavriel_page_key_properties():
    chars = _fixture()
    gavriel = next(c for c in chars if c.canonical_name == "Gavriel")
    relpath, wiki = render_series_character_page(gavriel, category_labels({}, "en"), lang="en")

    assert relpath == "characters/Gavriel.wiki"
    assert gavriel.importance == "principal"          # highest tier reached (secondary -> principal)
    # latest-wins status, collapsed behind the spoiler span
    assert "mw-collapsible mw-collapsed" in wiki and "Deceased" in wiki
    assert "Alive" not in wiki
    # one collapsible tome section per tome, headed by the tome title, tome-axis controls
    assert wiki.count("data-expandtext=\"Book 1 — reveal\"") == 1
    assert wiki.count("data-expandtext=\"Book 2 — reveal\"") == 1
    assert "== Throne of Glass ==" in wiki and "== Crown of Midnight ==" in wiki
    # multi-tome appearance line
    assert "First appears in book 1, last appears in book 2" in wiki
    # tome-2 event rendered under its tome section
    assert "Gavriel dies shielding the army." in wiki
    # relationships merged to one index line per target, latest tome's span winning
    assert "* [[Aedion]] — family (ch.3→ch.20)" in wiki
    assert "ch.10" not in wiki  # tome-1 span superseded by the latest-wins merge
    # STU-718: no duplicated sections. The Biography récit is inlined under each tome
    # title (no Biography heading anywhere), attribute sections are consolidated once,
    # and Relationships is the single merged index.
    assert "Biography ==" not in wiki
    assert wiki.count("== Personality ==") == 1  # consolidated, not once per tome
    assert "Weary but resolute." in wiki and "Proud and haunted." not in wiki  # latest tome wins
    assert wiki.count("\n== Relationships ==") == 1
    # the per-tome prose Relationships is dropped in favor of the merged index
    assert "reunited at last" not in wiki and "unknown to him" not in wiki


def test_tome_links_are_retargeted_onto_the_series_page_set():
    """STU-719: each tome links the entity by whatever it called it. On the series
    page those targets must resolve to the one merged page — and a target the merge
    dropped must be unlinked, never left as a red link."""
    registry = Registry.from_dict({
        "version": 1,
        "entities": [
            {"entity_id": "aelin", "canonical_name": "Aelin Galathynius",
             "entity_type": "PERSON", "aliases": ["Aelin Galathynius", "Celaena Sardothien"]},
            {"entity_id": "queen", "canonical_name": "Queen", "entity_type": "PERSON",
             "aliases": ["Queen"]},
            {"entity_id": "chaol", "canonical_name": "Chaol", "entity_type": "PERSON",
             "aliases": ["Chaol"]},
        ],
        "decisions": [], "warnings": [],
    })
    tome = TomeArtifacts(
        book_id="01-heir", title="Throne of Glass",
        pages=[
            {"title": "Chaol", "importance": "secondary", "entity_type": "PERSON",
             "content": "## Biography\n\nSworn to [[Celaena Sardothien]] and to the [[Queen]].",
             "relationship_index": ["* [[Celaena Sardothien]] — romance (ch.5)",
                                    "* [[Aelin Galathynius]] — romance (ch.40)",
                                    "* [[Queen]] — duty (ch.1)"]},
            {"title": "Aelin Galathynius", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nQueen of Terrasen."},
            {"title": "Queen", "importance": "secondary", "entity_type": "PERSON",
             "content": "## Biography\n\nSomeone's queen."},
        ],
    )
    vocab = {"role_words": ["queen"], "determiners": ["the"]}
    chars = build_series_characters(registry, [tome], **vocab)
    targets = link_targets(registry, chars, **vocab)

    assert "Queen" not in {c.canonical_name for c in chars}
    chaol = next(c for c in chars if c.canonical_name == "Chaol")
    _, wiki = render_series_character_page(
        chaol, category_labels({}, "en"), lang="en", targets=targets, determiners=["the"],
    )

    # Two tome spellings of one character collapse to one line pointing at her page.
    assert wiki.count("romance") == 1
    assert "[[Aelin Galathynius|Celaena Sardothien]] — romance (ch.5)" in wiki
    # The dropped generic role is unlinked in the index and in the prose.
    assert "[[Queen]]" not in wiki
    assert "* Queen — duty (ch.1)" in wiki
    assert "and to the Queen." in wiki
