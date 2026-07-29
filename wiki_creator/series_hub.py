"""Series hub — the series wiki's front page (STU-707).

Pure model + wikitext render, no I/O and no LLM: the deterministic frame
(reading order, main characters, navigation) around one injectable slot, the
overarching-arc paragraph an LLM pass supplies (STU-708). The series-scope
counterpart of ``export_helpers.main_page_content``, which does the same job for
a single tome.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from wiki_creator import entity_taxonomy
from wiki_creator.page_templates import TIERS, chrome_label
from wiki_creator.series import SeriesCharacter
from wiki_creator.tome_labels import tome_number

# "Who are the main characters of this series?" — a question about the books,
# answered by the reconciled notability tier (STU-668 latest-wins).
HUB_MAIN_CHARACTER_TIER = "principal"

HUB_FILENAME = "Main_Page.wiki"


@dataclass
class SeriesTome:
    """One tome as the hub lists it. ``synopsis_title`` links the entry to that
    tome's synopsis page; absent when the series wiki publishes none."""

    book_id: str
    title: str
    synopsis_title: str | None = None


@dataclass
class SeriesHub:
    series_title: str
    author: str
    tomes: list[SeriesTome] = field(default_factory=list)
    main_characters: list[str] = field(default_factory=list)


def main_characters(
    characters: list[SeriesCharacter], tier: str = HUB_MAIN_CHARACTER_TIER
) -> list[str]:
    """Canonical names of the series' main characters, in assembly order: the
    PERSON entities whose reconciled tier reaches ``tier``. Each one's series page
    title is its canonical name (A2: exactly one page per entity)."""
    floor = TIERS.index(tier if tier in TIERS else HUB_MAIN_CHARACTER_TIER)
    return [
        character.canonical_name
        for character in characters
        if character.entity_type == "PERSON"
        and character.importance in TIERS
        and TIERS.index(character.importance) >= floor
    ]


def build_series_hub(
    series_title: str,
    author: str,
    tomes: list[SeriesTome],
    characters: list[SeriesCharacter],
    tier: str = HUB_MAIN_CHARACTER_TIER,
) -> SeriesHub:
    """Hub model from the tome list (reading order) and the assembled series
    characters."""
    return SeriesHub(
        series_title=series_title,
        author=author,
        tomes=list(tomes),
        main_characters=main_characters(characters, tier),
    )


def render_series_hub(
    hub: SeriesHub, labels: dict, *, lang: str, arc: str | None = None
) -> tuple[str, str]:
    """``(path relative to the series wiki dir, wikitext)`` for the hub page.

    ``arc`` is the overarching-series paragraph (STU-708); omitted, the frame
    renders without it."""
    lines = [f"= {hub.series_title} =", f"''{hub.author}''", ""]
    if arc:
        lines += [arc.strip(), ""]

    lines.append(f"== {chrome_label('reading_order', lang)} ==")
    for tome in hub.tomes:
        label = chrome_label("tome_heading", lang).format(tome=tome_number(tome.book_id))
        title = f"[[{tome.synopsis_title}|{tome.title}]]" if tome.synopsis_title else tome.title
        lines.append(f"* {label} — {title}")

    lines += ["", f"== {chrome_label('main_characters', lang)} =="]
    lines += [f"* [[{name}]]" for name in hub.main_characters]

    persons = labels.get("persons") or entity_taxonomy.category_default("PERSON", lang)
    locations = labels.get("locations") or entity_taxonomy.category_default("PLACE", lang)
    orgs = labels.get("organizations") or entity_taxonomy.category_default("ORG", lang)
    lines += [
        "",
        f"== {chrome_label('navigation', lang)} ==",
        f"* [[:Category:{persons}|{chrome_label('all_characters', lang)}]]",
        f"* [[:Category:{locations}|{chrome_label('all_locations', lang)}]]",
        f"* [[:Category:{orgs}|{chrome_label('all_organizations', lang)}]]",
    ]
    return HUB_FILENAME, "\n".join(lines)
