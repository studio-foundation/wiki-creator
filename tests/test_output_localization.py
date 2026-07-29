"""No French literal survives an English render (STU-734).

The regression gate the STU-734 audit exists to install. Every reader-facing
surface is rendered with ``lang="en"`` and checked against the *French* side of
base.yaml itself — so a new localized string added to `chrome`/`labels`/`stubs`
is covered the day it lands, and a string built in Python instead of read from
the template is caught the day someone writes it.
"""
from __future__ import annotations

import pytest

import scripts.generate_book_synopsis as synopsis_stage
import scripts.generate_event_pages as event_stage
import scripts.generate_wiki_pages as gwp
from scripts.wiki_export import _build_categories_wiki, render_page
from scripts.wiki_page_validator import check_language_contamination, validate_page
from wiki_creator.collation import collation_labels, collective_pages
from wiki_creator.export_helpers import category_labels, main_page_content
from wiki_creator.page_templates import load_base_template
from wiki_creator.registry import Registry
from wiki_creator.series import TomeArtifacts, build_series_characters
from wiki_creator.series_hub import SeriesTome, build_series_hub, render_series_hub
from wiki_creator.series_pages import render_series_character_page
from wiki_creator.tome_labels import appearance_label

LABELS = category_labels({}, "en")
_STUB_ENTITY = {"canonical_name": "Nox", "type": "PERSON", "importance": "figurant"}


def _french_strings() -> list[str]:
    """Every base.yaml string whose French differs from its English — the exact
    vocabulary an English render must never contain. Placeholders are stripped so
    a `{n}`-carrying template is matched on its literal prefix."""
    base = load_base_template()
    out = []
    for group in ("chrome", "labels", "stubs"):
        for entry in (base.get(group) or {}).values():
            if not isinstance(entry, dict):
                continue
            fr, en = entry.get("fr"), entry.get("en")
            if not fr or fr == en:
                continue
            head = fr.split("{")[0].strip(" :,—")
            if len(head) < 5:
                continue  # shorter heads collide with ordinary words
            if head in en:
                continue  # "Relations" inside "Relationships": not detectable by search
            out.append(head)
    for spec in (base.get("entity_types") or {}).values():
        default = ((spec.get("export") or {}).get("category_default")) or {}
        if default.get("fr") and default["fr"] != default.get("en"):
            out.append(default["fr"])
    return sorted(set(out))


FRENCH = _french_strings()


def assert_no_french(rendered: str, surface: str) -> None:
    hits = [s for s in FRENCH if s in rendered]
    assert not hits, f"French literal(s) {hits} in the English render of {surface}"


def _person_page() -> dict:
    return {
        "title": "Celaena",
        "entity_type": "PERSON",
        "importance": "principal",
        "content": "## Biography\n\nBio.\n\n## Relationships\n\nProse.",
        "infobox_fields": {"nom": "Celaena", "status": "Deceased", "death": "Killed by Durza"},
        "books": ["01-heir", "02-crown"],
        "content_units": [
            {"section": "biography", "revealed_at_chapter": 1},
            {"section": "relationships", "revealed_at_chapter": 20},
        ],
        "relationship_index": ["* [[Chaol]] — lover (ch.1→ch.55)"],
    }


def _series_characters() -> list:
    registry = Registry.from_dict({
        "version": 1,
        "entities": [
            {"entity_id": "celaena", "canonical_name": "Celaena", "entity_type": "PERSON",
             "aliases": ["Aelin"], "books": ["01-heir", "02-crown"]},
        ],
        "decisions": [], "warnings": [],
    })
    tomes = [
        TomeArtifacts(
            book_id=book_id,
            pages=[{"title": "Celaena", "importance": "principal", "entity_type": "PERSON",
                    "content": "## Biography\n\nAn assassin."}],
            status_verdicts={"Celaena": {"status": "deceased", "agent": "Durza"}},
            events=[{"description": "The duel", "participants": ["Celaena"], "chapter": 3}],
        )
        for book_id in ("01-heir", "02-crown")
    ]
    return build_series_characters(registry, tomes)


@pytest.mark.parametrize("surface,render", [
    ("entity page", lambda: render_page(_person_page(), LABELS, 5, None, lang="en")[1]),
    ("categories.wiki", lambda: _build_categories_wiki(LABELS, "en")),
    ("Main_Page.wiki", lambda: main_page_content(
        "Heir of Fire", "Sarah J. Maas", [_person_page()], LABELS, lang="en")),
    ("appearance slot", lambda: appearance_label(["01-heir", "02-crown"], lang="en")),
    ("collective page", lambda: collective_pages(
        [{"canonical_name": "Nox", "type": "PERSON", "aliases": ["Nox Owen"],
          "total_mentions": 4, "chapters_present": 2}],
        collation_labels({}, lang="en"), lang="en")[0]["content"]),
    ("collective page title", lambda: collective_pages(
        [{"canonical_name": "Nox", "type": "PERSON", "total_mentions": 4, "chapters_present": 2}],
        collation_labels({}, lang="en"), lang="en")[0]["title"]),
    ("series character page", lambda: render_series_character_page(
        _series_characters()[0], LABELS, lang="en")[1]),
    ("series hub", lambda: render_series_hub(
        build_series_hub("Throne of Glass", "Sarah J. Maas",
                         [SeriesTome(book_id="01-heir", title="Heir of Fire")],
                         _series_characters()),
        LABELS, lang="en")[1]),
    ("failed stub page", lambda: gwp.make_stub_page(_STUB_ENTITY, failed=True, lang="en")["content"]),
    ("insufficient stub page", lambda: gwp.make_stub_page(
        _STUB_ENTITY, insufficient_data=True, lang="en")["content"]),
    ("references block", lambda: gwp._references_block("Heir of Fire", lang="en")),
    ("references back-matter", lambda: gwp._references_backmatter(lang="en")),
    ("synopsis stub", lambda: synopsis_stage._stub_page("en", failed=True)["content"]),
    ("event stub page", lambda: event_stage._stub_page(
        "The duel", {"description": "The duel"}, "en", failed=True)["content"]),
])
def test_english_render_carries_no_french(surface, render):
    assert_no_french(render(), surface)


def test_validator_messages_are_english():
    page = {"title": "Celaena", "content": "## Biography\n\nCelaena is the heir of fire.",
            "infobox_fields": {"- nom": "Celaena"}}
    verdict = validate_page(page, {"title": "Celaena", "language": "en"})

    assert not verdict["valid"]
    assert_no_french("\n".join(verdict["errors"]) + verdict["feedback"], "validator messages")


def test_contamination_check_passes_an_english_page():
    """The bug STU-734 names: the check hardcoded `en` as the contaminant, so an
    English page tripped `language_contamination` on the very markers it must
    contain."""
    page = {"content": "Celaena is the best assassin in the kingdom. She was known as Lillian."}

    assert check_language_contamination(page, lang="en") == []
    assert check_language_contamination(page, lang="fr") != []
