"""Series hub frame (STU-707) — golden on a synthetic 2-tome fixture.

Pure logic, LLM-free: assembled series characters + tome metadata →
build_series_hub → render_series_hub, compared byte-for-byte to a committed
.wiki golden. The arc slot is absent from the golden — it is STU-708's string,
not part of the deterministic frame.

    UPDATE_GOLDENS=1 python -m pytest tests/test_series_hub.py -q
"""
import os
from pathlib import Path

from wiki_creator.export_helpers import category_labels
from wiki_creator.registry import Registry
from wiki_creator.series import TomeArtifacts, build_series_characters
from wiki_creator.series_hub import (
    HUB_FILENAME,
    HUB_MAIN_CHARACTER_TIER,
    SeriesTome,
    build_series_hub,
    render_series_hub,
)

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "series"
UPDATE_GOLDENS = os.environ.get("UPDATE_GOLDENS") == "1"

TOMES = [
    SeriesTome(book_id="01-heir", title="Heir of Fire", synopsis_title="Heir of Fire (synopsis)"),
    SeriesTome(book_id="02-crown", title="Queen of Shadows"),
]


def _characters() -> list:
    registry = Registry.from_dict({
        "version": 1,
        "entities": [
            {"entity_id": "gavriel", "canonical_name": "Gavriel",
             "entity_type": "PERSON", "aliases": [], "books": ["01-heir", "02-crown"]},
            {"entity_id": "celaena", "canonical_name": "Aelin Galathynius",
             "entity_type": "PERSON", "aliases": ["Celaena Sardothien"],
             "books": ["01-heir", "02-crown"]},
            # secondary in every tome: below the hub tier, never listed
            {"entity_id": "nesryn", "canonical_name": "Nesryn Faliq",
             "entity_type": "PERSON", "aliases": [], "books": ["02-crown"]},
            # principal, but not a character: the hub lists people
            {"entity_id": "castle", "canonical_name": "Glass Castle",
             "entity_type": "PLACE", "aliases": []},
        ],
        "decisions": [], "warnings": [],
    })
    tome1 = TomeArtifacts(
        book_id="01-heir",
        pages=[
            {"title": "Gavriel", "importance": "secondary", "entity_type": "PERSON",
             "content": "## Biography\n\nA warrior of the Cadre."},
            {"title": "Celaena Sardothien", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nAn assassin in Rifthold."},
        ],
    )
    tome2 = TomeArtifacts(
        book_id="02-crown",
        pages=[
            {"title": "Gavriel", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nHe joins the war."},
            {"title": "Aelin Galathynius", "importance": "principal", "entity_type": "PERSON",
             "content": "## Biography\n\nQueen of Terrasen."},
            {"title": "Nesryn Faliq", "importance": "secondary", "entity_type": "PERSON",
             "content": "## Biography\n\nA rebel archer."},
            {"title": "Glass Castle", "importance": "principal", "entity_type": "PLACE",
             "content": "## Overview\n\nShattered in the siege."},
        ],
    )
    return build_series_characters(registry, [tome1, tome2])


def _hub():
    return build_series_hub("Throne of Glass", "Sarah J. Maas", TOMES, _characters())


def test_hub_frame_matches_golden():
    path, wiki = render_series_hub(_hub(), category_labels({}, "en"), lang="en")

    assert path == HUB_FILENAME
    golden = GOLDEN_DIR / "hub.wiki"
    if UPDATE_GOLDENS:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(wiki, encoding="utf-8")
    assert golden.exists(), f"golden missing: {golden} — regenerate with UPDATE_GOLDENS=1"
    assert wiki == golden.read_text(encoding="utf-8"), (
        "hub render drifted from golden; if intentional rerun UPDATE_GOLDENS=1"
    )


def test_main_characters_are_persons_reaching_the_tier():
    hub = _hub()

    # Gavriel is secondary in tome 1, principal in tome 2 — latest-wins promotes him.
    assert hub.main_characters == ["Gavriel", "Aelin Galathynius"]
    assert HUB_MAIN_CHARACTER_TIER == "principal"

    lowered = build_series_hub(
        "Throne of Glass", "Sarah J. Maas", TOMES, _characters(), tier="secondary"
    )
    assert lowered.main_characters == ["Gavriel", "Aelin Galathynius", "Nesryn Faliq"]


def test_tome_entries_follow_reading_order_and_link_only_when_published():
    _, wiki = render_series_hub(_hub(), category_labels({}, "en"), lang="en")

    assert "* Book 1 — [[Heir of Fire (synopsis)|Heir of Fire]]" in wiki
    assert "* Book 2 — Queen of Shadows" in wiki
    assert wiki.index("Heir of Fire") < wiki.index("Queen of Shadows")


def test_arc_slot_is_injected_above_the_frame():
    frame = render_series_hub(_hub(), category_labels({}, "en"), lang="en")[1]
    with_arc = render_series_hub(
        _hub(), category_labels({}, "en"), lang="en", arc="A kingdom of glass, a queen of ash."
    )[1]

    assert "A kingdom of glass, a queen of ash." in with_arc
    assert with_arc.index("A kingdom of glass") < with_arc.index("== Reading order ==")
    assert with_arc.replace("A kingdom of glass, a queen of ash.\n\n", "") == frame


def test_hub_localizes_chrome_and_category_targets():
    _, wiki = render_series_hub(_hub(), category_labels({}, "fr"), lang="fr")

    assert "== Ordre de lecture ==" in wiki
    assert "* Tome 1 — [[Heir of Fire (synopsis)|Heir of Fire]]" in wiki
    assert "[[:Category:Personnages|Tous les personnages]]" in wiki
