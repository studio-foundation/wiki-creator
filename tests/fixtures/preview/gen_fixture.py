#!/usr/bin/env python3
"""Generate the preview-app wikitext fixture (STU-645).

The M5.1 Fandom Preview app consumes what ``scripts/wiki_export.py`` writes. To
stay faithful byte-for-byte, this fixture is **not** hand-typed wikitext: the
*pages* are hand-authored (an Alice in Wonderland cast, no live pipeline run, no
EPUB/LLM), but the *wikitext* is produced by the real exporter helpers —
``render_page``, ``main_page_content``, the infobox-template writer and
``_build_categories_wiki`` — exactly as ``wiki_export.main`` would.

There is no circularity with the e2e discipline (STU-524): the exporter and the
preview app's parser are different components. Re-run this after an intentional
exporter change and review the diff, the same way ``gen_seed.py`` is re-run.

    python tests/fixtures/preview/gen_fixture.py

writes ``tests/fixtures/preview/output/`` (a book named
``01-alice-in-wonderland``), covering every construct the exporter emits:
headings, bold/italic, wikilinks (incl. a cross-subdir link and a dangling/red
link), ``[[Category:X]]``, an infobox table + ``{{Infobox …}}`` call, and an
``mw-collapsible`` spoiler block (a late-revealed section, and a gated
status/death infobox row).
"""
from __future__ import annotations

from pathlib import Path

from scripts.wiki_export import render_page, _build_categories_wiki
from wiki_creator import entity_taxonomy
from wiki_creator.editorial_stance import EditorialStance
from wiki_creator.export_helpers import index_limits, main_page_content

OUT = Path(__file__).resolve().parent / "output"
LANG = "en"
BOOK = "01-alice-in-wonderland"
# A spoiler cutoff so late-revealed sections and status/death rows collapse.
COLLAPSE_AFTER = 6

# English category axis for an English novel (export.categories.labels).
EXPORT_CFG = {
    "categories": {
        "labels": {
            "persons": "Characters",
            "locations": "Locations",
            "organizations": "Organizations",
            "events": "Events",
            "principal": "Main Characters",
            "secondary": "Supporting Characters",
            "persons_by_tome": "Characters (Book {n})",
            "locations_by_tome": "Locations (Book {n})",
            "organizations_by_tome": "Organizations (Book {n})",
        }
    }
}


def _pages() -> list[dict]:
    """The hand-authored cast. Section headings use the localized slot labels so
    the exporter's spoiler gating matches them (wrap_collapsible keys on
    slot_label)."""
    alice = {
        "title": "Alice",
        "entity_type": "PERSON",
        "importance": "principal",
        "books": [BOOK],
        "infobox_fields": {
            "name": "Alice",
            "aliases": "",
            "titles": "",
            "status": "Alive",
            "death": "",
            "species": "Human",
            "occupation": "",
            "residence": "Victorian England",
            "affiliation": "",
            "first_seen": "Chapter 1",
        },
        "content": (
            "== Biography ==\n"
            "'''Alice''' is a curious seven-year-old girl who falls down a "
            "rabbit hole into [[Wonderland]], a nonsensical world she explores "
            "across the story. She follows the [[White Rabbit]], meets the "
            "[[Cheshire Cat]], and clashes with the [[Queen of Hearts]].\n\n"
            "== Appearance ==\n"
            "Alice wears a blue pinafore dress. Her size changes constantly — "
            "she grows ''enormous'' after a cake and shrinks after a drink.\n\n"
            "== Narrative role ==\n"
            "By the trial, Alice realises the court is ''nothing but a pack of "
            "cards'' and wakes — the dream ends. A stray note about the "
            "[[Dormouse]] belongs here too.\n"
        ),
        "content_units": [
            {"section": "biography", "revealed_at_chapter": 1},
            {"section": "physical", "revealed_at_chapter": 2},
            {"section": "narrative_role", "revealed_at_chapter": 12},
        ],
    }
    white_rabbit = {
        "title": "White Rabbit",
        "entity_type": "PERSON",
        "importance": "principal",
        "books": [BOOK],
        "infobox_fields": {
            "name": "White Rabbit",
            "species": "Rabbit",
            "status": "Alive",
            "occupation": "Herald",
            "affiliation": "[[Court of Hearts]]",
            "first_seen": "Chapter 1",
        },
        "content": (
            "== Biography ==\n"
            "The '''White Rabbit''' is a fretful, waistcoat-wearing rabbit who "
            "hurries through [[Wonderland]] muttering ''\"Oh dear! I shall be "
            "late!\"'' It is he Alice follows down the [[Rabbit Hole]].\n"
        ),
        "content_units": [{"section": "biography", "revealed_at_chapter": 1}],
    }
    cheshire = {
        "title": "Cheshire Cat",
        "entity_type": "PERSON",
        "importance": "secondary",
        "books": [BOOK],
        "infobox_fields": {
            "name": "Cheshire Cat",
            "species": "Cat",
            "status": "Alive",
            "first_seen": "Chapter 6",
        },
        "content": (
            "== Biography ==\n"
            "The '''Cheshire Cat''' is a grinning cat who can vanish at will, "
            "leaving only its smile. It gives Alice riddling directions and "
            "unsettles the [[Queen of Hearts]].\n"
        ),
        "content_units": [{"section": "biography", "revealed_at_chapter": 6}],
    }
    queen = {
        "title": "Queen of Hearts",
        "entity_type": "PERSON",
        "importance": "principal",
        "books": [BOOK],
        "infobox_fields": {
            "name": "Queen of Hearts",
            "titles": "Queen",
            "status": "Deceased",
            "death": "Dissolved when Alice wakes",
            "species": "Playing card",
            "affiliation": "[[Court of Hearts]]",
            "first_seen": "Chapter 8",
        },
        "content": (
            "== Biography ==\n"
            "The '''Queen of Hearts''' is the tyrant of [[Wonderland]], forever "
            "bellowing ''\"Off with their heads!\"'' She rules the "
            "[[Court of Hearts]] and puts Alice on trial.\n\n"
            "== Narrative role ==\n"
            "Her court is revealed to be ''nothing but a pack of cards'', and "
            "she dissolves with the dream.\n"
        ),
        "content_units": [
            {"section": "biography", "revealed_at_chapter": 8},
            {"section": "narrative_role", "revealed_at_chapter": 12},
        ],
    }
    wonderland = {
        "title": "Wonderland",
        "entity_type": "PLACE",
        "importance": "principal",
        "books": [BOOK],
        "infobox_fields": {
            "name": "Wonderland",
            "type": "Dream world",
            "location": "Below the [[Rabbit Hole]]",
        },
        "content": (
            "== Overview ==\n"
            "'''Wonderland''' is the surreal realm Alice reaches through the "
            "[[Rabbit Hole]]. Its logic is dream-logic: sizes shift, animals "
            "speak, and the [[Court of Hearts]] holds absurd trials.\n"
        ),
    }
    rabbit_hole = {
        "title": "Rabbit Hole",
        "entity_type": "PLACE",
        "importance": "secondary",
        "books": [BOOK],
        "infobox_fields": {"name": "Rabbit Hole", "type": "Passage"},
        "content": (
            "== Overview ==\n"
            "The '''Rabbit Hole''' is the tunnel Alice tumbles down after the "
            "[[White Rabbit]], falling slowly past shelves and maps into "
            "[[Wonderland]].\n"
        ),
    }
    court = {
        "title": "Court of Hearts",
        "entity_type": "ORG",
        "importance": "principal",
        "books": [BOOK],
        "infobox_fields": {
            "name": "Court of Hearts",
            "type": "Royal court",
            "leader": "[[Queen of Hearts]]",
        },
        "content": (
            "== Overview ==\n"
            "The '''Court of Hearts''' is the playing-card court ruled by the "
            "[[Queen of Hearts]]. It stages the trial of the Knave and, "
            "finally, of [[Alice]] herself.\n"
        ),
    }
    tea_party = {
        "title": "A Mad Tea-Party",
        "entity_type": "EVENT",
        "importance": "principal",
        "books": [BOOK],
        "infobox_fields": {
            "name": "A Mad Tea-Party",
            "participants": "[[Alice]], [[Cheshire Cat]]",
            "location": "[[Wonderland]]",
            "chapter": "Chapter 7",
        },
        "content": (
            "== Overview ==\n"
            "'''A Mad Tea-Party''' is the endless tea party where time itself "
            "has stopped at six o'clock. Alice is quizzed with the riddle "
            "''\"Why is a raven like a writing-desk?\"'' and leaves in disgust.\n"
        ),
    }
    synopsis = {
        "title": "Synopsis",
        "entity_type": "SYNOPSIS",
        "importance": "principal",
        "infobox_fields": {},
        "content": (
            "== Synopsis ==\n"
            "'''Alice''' follows a waistcoated [[White Rabbit]] down a "
            "[[Rabbit Hole]] into [[Wonderland]], where she grows and shrinks, "
            "attends [[A Mad Tea-Party]], and is tried by the "
            "[[Queen of Hearts]] before waking on a riverbank.\n"
        ),
    }
    minor = {
        "title": "Minor Characters",
        "entity_type": "COLLATION",
        "importance": "figurant",
        "infobox_fields": {},
        "content": (
            "== Minor Characters ==\n"
            "* '''Dodo''' — organiser of the Caucus-race.\n"
            "* '''Mock Turtle''' — a melancholy creature who sings of soup.\n"
            "* '''Gryphon''' — escorts Alice to the Mock Turtle.\n"
        ),
    }
    return [
        alice, white_rabbit, cheshire, queen,
        wonderland, rabbit_hole, court, tea_party,
        synopsis, minor,
    ]


def _labels() -> dict:
    """Reproduce wiki_export.main's labels dict for the English export config."""
    labels_cfg = EXPORT_CFG["categories"]["labels"]
    labels = {
        "principal": labels_cfg["principal"],
        "secondary": labels_cfg["secondary"],
        "persons_by_tome": labels_cfg["persons_by_tome"],
        "locations_by_tome": labels_cfg["locations_by_tome"],
        "organizations_by_tome": labels_cfg["organizations_by_tome"],
    }
    for etype in entity_taxonomy.declared_types():
        cat_key = entity_taxonomy.category_key(etype)
        if cat_key and cat_key not in labels:
            labels[cat_key] = labels_cfg.get(cat_key) or entity_taxonomy.category_default(etype)
    return labels


def build() -> dict[str, str]:
    """Every fixture ``.wiki`` file as ``{relative path: content}``, produced by
    the real exporter helpers. The single source of truth for both the writer
    (``main``) and the drift guard (``test_preview_fixture.py``)."""
    pages = _pages()
    labels = _labels()
    stance = EditorialStance()
    files: dict[str, str] = {}

    for etype in entity_taxonomy.declared_types():
        source = entity_taxonomy.infobox_source(etype)
        template_name = entity_taxonomy.infobox_template_name(etype)
        if not source or not template_name:
            continue
        files[f"templates/{template_name.replace(' ', '_')}.wiki"] = source

    for page in pages:
        rel_path, content = render_page(page, labels, COLLAPSE_AFTER, stance, LANG)
        files[rel_path] = content

    files["categories.wiki"] = _build_categories_wiki(labels)

    principals_shown, places_shown = index_limits(EXPORT_CFG)
    files["Main_Page.wiki"] = main_page_content(
        "Alice's Adventures in Wonderland", "Lewis Carroll", pages, labels,
        principals_shown, places_shown,
        expose_pipeline_metadata=stance.expose_pipeline_metadata, lang=LANG,
    )
    return files


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for rel_path, content in build().items():
        path = OUT / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"wrote {len(build())} .wiki files under {OUT}")


if __name__ == "__main__":
    main()
