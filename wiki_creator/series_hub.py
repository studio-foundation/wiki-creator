"""Series hub — the series wiki's front page (STU-707).

Pure model + wikitext render, no I/O and no LLM: the deterministic frame
(reading order, main characters, navigation) around one injectable slot, the
overarching-arc paragraph an LLM pass supplies (STU-708). The series-scope
counterpart of ``export_helpers.main_page_content``, which does the same job for
a single tome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from wiki_creator import entity_taxonomy
from wiki_creator.page_templates import TIERS, chrome_label
from wiki_creator.series import SeriesCharacter
from wiki_creator.tome_labels import tome_number

# "Who are the main characters of this series?" — a question about the books,
# answered by the reconciled notability tier (STU-668 latest-wins).
HUB_MAIN_CHARACTER_TIER = "principal"

# STU-738: a character consistently mid-tier across the whole series (the
# Cowardly Lion — secondary in every tome, principal in none) is a series main
# character too, distinct from the single-tome-peak question above. Reaching
# ``HUB_RECURRENCE_TIER`` in at least ``HUB_RECURRENCE_SHARE`` of the series'
# *published* tomes clears that floor. Overridable per series via
# ``canon.yaml`` (``cross_tome.main_character_recurrence``), never a bare
# constant a reader would have to edit code to tune. 1/3 is calibrated to the
# ticket's own case on the real Oz corpus: the Lion is ``secondary`` in 2 of
# its 6 published tomes.
HUB_RECURRENCE_TIER = "secondary"
HUB_RECURRENCE_SHARE = 1 / 3

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
    characters: list[SeriesCharacter],
    tier: str = HUB_MAIN_CHARACTER_TIER,
    *,
    tome_count: int = 0,
    recurrence_tier: str = HUB_RECURRENCE_TIER,
    recurrence_share: float = HUB_RECURRENCE_SHARE,
) -> list[str]:
    """Canonical names of the series' main characters, in assembly order: the
    PERSON entities whose reconciled tier reaches ``tier``, plus (STU-738) any
    PERSON who never peaked that high but reached ``recurrence_tier`` in at
    least a ``recurrence_share`` fraction of the series' ``tome_count`` tomes —
    the recurrence signal max-across-tomes cannot see (a character consistently
    ``secondary`` everywhere never reaches ``principal`` by that rule alone).
    Each one's series page title is its canonical name (A2: exactly one page
    per entity)."""
    floor = TIERS.index(tier if tier in TIERS else HUB_MAIN_CHARACTER_TIER)
    recurrence_floor = TIERS.index(
        recurrence_tier if recurrence_tier in TIERS else HUB_RECURRENCE_TIER
    )
    # A single tome is not recurrence; require the tier in at least two even
    # when the share alone (e.g. a 2-tome series) would allow one.
    recurrence_min = max(2, ceil(tome_count * recurrence_share)) if tome_count > 0 else None

    names = []
    for character in characters:
        if character.entity_type != "PERSON":
            continue
        if character.importance in TIERS and TIERS.index(character.importance) >= floor:
            names.append(character.canonical_name)
            continue
        if recurrence_min is None:
            continue
        hits = sum(
            1
            for contribution in character.contributions
            if contribution.page
            and str(contribution.page.get("importance") or "") in TIERS
            and TIERS.index(str(contribution.page["importance"])) >= recurrence_floor
        )
        if hits >= recurrence_min:
            names.append(character.canonical_name)
    return names


def build_series_hub(
    series_title: str,
    author: str,
    tomes: list[SeriesTome],
    characters: list[SeriesCharacter],
    tier: str = HUB_MAIN_CHARACTER_TIER,
    *,
    tome_count: int | None = None,
    recurrence_tier: str = HUB_RECURRENCE_TIER,
    recurrence_share: float = HUB_RECURRENCE_SHARE,
) -> SeriesHub:
    """Hub model from the tome list (reading order) and the assembled series
    characters.

    ``tome_count`` is the denominator for the recurrence share (STU-738) —
    defaults to ``len(tomes)``, but a series with tomes discovered on disk that
    have not actually run yet (no pages generated) must pass the *published*
    count explicitly, or recurrence is measured against books with no data at
    all and can never clear its own floor.
    """
    return SeriesHub(
        series_title=series_title,
        author=author,
        tomes=list(tomes),
        main_characters=main_characters(
            characters,
            tier,
            tome_count=tome_count if tome_count is not None else len(tomes),
            recurrence_tier=recurrence_tier,
            recurrence_share=recurrence_share,
        ),
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
