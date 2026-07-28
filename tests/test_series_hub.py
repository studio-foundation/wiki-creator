"""Series hub render (STU-707) — deterministic frame, golden on a 2-tome fixture.

Pure logic, LLM-free: hand-authored per-tome artifacts → build_series_characters
→ render_series_hub, compared byte-for-byte to a committed .wiki golden.

    UPDATE_GOLDENS=1 python -m pytest tests/test_series_hub.py -q
"""
import os
from pathlib import Path

from wiki_creator.export_helpers import category_labels
from wiki_creator.registry import Registry
from wiki_creator.series import build_series_characters, TomeArtifacts
from wiki_creator.series_hub import SeriesTome, render_series_hub

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "series"
UPDATE_GOLDENS = os.environ.get("UPDATE_GOLDENS") == "1"


def _page(title: str, importance: str, entity_type: str = "PERSON") -> dict:
    return {"title": title, "importance": importance, "entity_type": entity_type}


def _characters() -> list:
    registry = Registry.from_dict({
        "version": 1,
        "entities": [
            {"entity_id": "aelin", "canonical_name": "Aelin Galathynius",
             "entity_type": "PERSON", "aliases": ["Celaena Sardothien"]},
            {"entity_id": "gavriel", "canonical_name": "Gavriel",
             "entity_type": "PERSON", "aliases": []},
            {"entity_id": "nesryn", "canonical_name": "Nesryn Faliq",
             "entity_type": "PERSON", "aliases": []},
            {"entity_id": "rifthold", "canonical_name": "Rifthold",
             "entity_type": "PLACE", "aliases": []},
        ],
        "decisions": [], "warnings": [],
    })
    tome1 = TomeArtifacts("01-heir", pages=[
        _page("Celaena Sardothien", "principal"),
        _page("Gavriel", "secondary"),
        _page("Rifthold", "principal", "PLACE"),
    ])
    tome2 = TomeArtifacts("02-crown", pages=[
        _page("Aelin Galathynius", "principal"),
        _page("Gavriel", "principal"),
        _page("Nesryn Faliq", "secondary"),   # secondary everywhere → not a lead
        _page("Rifthold", "principal", "PLACE"),
    ])
    return build_series_characters(registry, [tome1, tome2])


def _tomes() -> list:
    return [
        SeriesTome(number="1", title="Heir of Fire"),
        SeriesTome(number="2", title="Queen of Shadows"),
    ]


def _assert_golden(name: str, actual: str) -> None:
    path = GOLDEN_DIR / name
    if UPDATE_GOLDENS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"golden missing: {path} — regenerate with UPDATE_GOLDENS=1"
    assert actual == path.read_text(encoding="utf-8"), (
        f"render drifted from golden {name}; if intentional rerun UPDATE_GOLDENS=1"
    )


def test_series_hub_frame_matches_golden():
    """No arc — the deterministic frame only."""
    labels = category_labels({}, "en")
    filename, wiki = render_series_hub(
        "Throne of Glass", _tomes(), _characters(), labels, "en", arc=None
    )
    assert filename == "Main_Page.wiki"
    _assert_golden("series_hub.wiki", wiki)


def test_hub_selects_only_principal_leads():
    wiki = render_series_hub(
        "Throne of Glass", _tomes(), _characters(), category_labels({}, "en"), "en"
    )[1]
    # Aelin (principal, joined by alias) and Gavriel (secondary→principal latest-wins) lead.
    assert "* [[Aelin Galathynius]]" in wiki
    assert "* [[Gavriel]]" in wiki
    # Nesryn is secondary in every tome → not a main character.
    assert "Nesryn" not in wiki
    # Rifthold is a principal PLACE → main location, not a character.
    assert "* [[Rifthold]]" in wiki


def test_hub_injects_arc_when_present():
    arc = "Across five tomes, an assassin becomes a queen."
    wiki = render_series_hub(
        "Throne of Glass", _tomes(), _characters(), category_labels({}, "en"), "en", arc=arc
    )[1]
    assert "== Synopsis ==" in wiki
    assert arc in wiki
    # Absent arc drops the section entirely.
    no_arc = render_series_hub(
        "Throne of Glass", _tomes(), _characters(), category_labels({}, "en"), "en"
    )[1]
    assert "== Synopsis ==" not in no_arc


def test_hub_lists_tomes_in_reading_order():
    wiki = render_series_hub(
        "Throne of Glass", _tomes(), _characters(), category_labels({}, "en"), "en"
    )[1]
    assert "== Reading order ==" in wiki
    assert wiki.index("Book 1 — Heir of Fire") < wiki.index("Book 2 — Queen of Shadows")
