"""Render the series hub — the wiki's front page for a whole series (STU-707).

Deterministic frame (reading order, main characters/locations, navigation),
LLM-free — the series-scope counterpart of
``export_helpers.main_page_content``. The overarching "what is this series
about" arc is an injectable slot (``arc``), filled by the LLM pass (STU-708);
absent, the frame renders without it.
"""
from __future__ import annotations

from dataclasses import dataclass

from wiki_creator.page_templates import chrome_label
from wiki_creator.series import SeriesCharacter

# Main characters/locations are the top notability tier — a book question ("who
# are the leads?"), not a pipeline threshold. TIERS = (figurant, secondary,
# principal); "principal" is the tier the per-book main page already showcases.
MAIN_TIER = "principal"

HUB_FILENAME = "Main_Page.wiki"


@dataclass
class SeriesTome:
    """One tome as the hub lists it. Callers pass these in reading order."""

    number: str  # "1", "4.5"
    title: str


def _leads(characters: list[SeriesCharacter], entity_type: str) -> list[SeriesCharacter]:
    leads = [
        c for c in characters
        if c.entity_type == entity_type and c.importance == MAIN_TIER
    ]
    return sorted(leads, key=lambda c: c.canonical_name)


def render_series_hub(
    series_title: str,
    tomes: list[SeriesTome],
    characters: list[SeriesCharacter],
    labels: dict,
    lang: str = "fr",
    arc: str | None = None,
) -> tuple[str, str]:
    """``(filename relative to the series wiki dir, wikitext)`` for the hub page."""
    lines = [f"= {series_title} =", ""]

    if arc:
        lines += [f"== {chrome_label('synopsis', lang)} ==", "", arc.strip(), ""]

    lines += [f"== {chrome_label('reading_order', lang)} =="]
    for tome in tomes:
        heading = chrome_label("tome_heading", lang).format(tome=tome.number)
        lines.append(f"* {heading} — {tome.title}")

    lines += ["", f"== {chrome_label('main_characters', lang)} =="]
    for character in _leads(characters, "PERSON"):
        lines.append(f"* [[{character.canonical_name}]]")

    lines += ["", f"== {chrome_label('main_locations', lang)} =="]
    for place in _leads(characters, "PLACE"):
        lines.append(f"* [[{place.canonical_name}]]")

    persons_label = labels.get("persons", "Personnages")
    locations_label = labels.get("locations", "Lieux")
    orgs_label = labels.get("organizations", "Organisations")
    lines += [
        "",
        f"== {chrome_label('navigation', lang)} ==",
        f"* [[:Category:{persons_label}|{chrome_label('all_characters', lang)}]]",
        f"* [[:Category:{locations_label}|{chrome_label('all_locations', lang)}]]",
        f"* [[:Category:{orgs_label}|{chrome_label('all_organizations', lang)}]]",
    ]

    return HUB_FILENAME, "\n".join(lines).rstrip() + "\n"
