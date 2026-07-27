"""Series character page render (STU-668) — golden on a synthetic 2-tome fixture.

Pure logic, LLM-free: hand-authored per-tome artifacts → build_series_characters
→ render_series_character_page, compared byte-for-byte to a committed .wiki golden.

    UPDATE_GOLDENS=1 python -m pytest tests/test_series_render.py -q
"""
import os
from pathlib import Path

from wiki_creator.export_helpers import category_labels
from wiki_creator.registry import Registry
from wiki_creator.series import TomeArtifacts, build_series_characters
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
        pages=[
            {"title": "Gavriel", "importance": "secondary", "entity_type": "PERSON",
             "content": "## Biography\n\nA warrior of the Cadre.\n\n## Relationships\n\n**[[Aedion]]** — his son, unknown to him.",
             "relationship_index": ["* [[Aedion]] — family (ch.10)"]},
            {"title": "Celaena Sardothien", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nAn assassin in Rifthold.",
             "relationship_index": ["* [[Chaol]] — romance (ch.5→ch.30)"]},
        ],
        status_verdicts={"Gavriel": {"status": "alive", "quote": "Gavriel lived."}},
    )
    tome2 = TomeArtifacts(
        book_id="02-crown",
        pages=[
            {"title": "Gavriel", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nHe joins the war.\n\n## Relationships\n\n**[[Aedion]]** — reunited at last.",
             "relationship_index": ["* [[Aedion]] — family (ch.3→ch.20)"]},
            {"title": "Aelin Galathynius", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nQueen of Terrasen.",
             "relationship_index": ["* [[Chaol]] — romance (ch.5→ch.30)", "* [[Rowan]] — romance (ch.40)"]},
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

    assert set(by_name) == {"Gavriel", "Aelin Galathynius"}  # PLACE excluded

    _, gavriel = render_series_character_page(by_name["Gavriel"], labels, "en")
    _assert_golden("gavriel.wiki", gavriel)

    _, aelin = render_series_character_page(by_name["Aelin Galathynius"], labels, "en")
    _assert_golden("aelin.wiki", aelin)


def test_gavriel_page_key_properties():
    chars = _fixture()
    gavriel = next(c for c in chars if c.canonical_name == "Gavriel")
    relpath, wiki = render_series_character_page(gavriel, category_labels({}, "en"), "en")

    assert relpath == "characters/Gavriel.wiki"
    assert gavriel.importance == "principal"          # latest-wins (secondary -> principal)
    # latest-wins status, collapsed behind the spoiler span
    assert "mw-collapsible mw-collapsed" in wiki and "Deceased" in wiki
    assert "Alive" not in wiki
    # one collapsible tome section per tome, tome-axis reveal labels
    assert wiki.count("data-expandtext=\"Book 1 — reveal\"") == 1
    assert wiki.count("data-expandtext=\"Book 2 — reveal\"") == 1
    assert "== Book 1 ==" in wiki and "== Book 2 ==" in wiki
    # multi-tome appearance line
    assert "First appears in book 1, last appears in book 2" in wiki
    # tome-2 event rendered under its tome section
    assert "Gavriel dies shielding the army." in wiki
    # relationships merged to one index line per target, latest tome's span winning
    assert "* [[Aedion]] — family (ch.3→ch.20)" in wiki
    assert "ch.10" not in wiki  # tome-1 span superseded by the latest-wins merge
