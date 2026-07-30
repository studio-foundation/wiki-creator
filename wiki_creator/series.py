"""Series discovery — enumerate a series' book YAMLs in reading order (STU-487).

Pure logic over the existing library layout
(``library/<author>/<series>/books/NN_*.yaml``, already numbered); no ad-hoc
series manifest. Consumed by ``make run-series`` to run the tomes in
order, propagating the accumulated series registry from one tome to the next.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from wiki_creator.canonicalize import (
    canonical_key,
    is_generic_role_name,
    preferred_display_name,
)
from wiki_creator.lang import load_lang_config
from wiki_creator.page_templates import TIERS, output_language
from wiki_creator.registry import EntityRecord, Registry
from wiki_creator.tome_labels import tome_number


def _sort_key(book: Path) -> tuple[float, str]:
    """Order by leading numeric tome prefix ('04.5_...' -> 4.5); books with no
    numeric prefix sort last, then alphabetically by name for stability."""
    number = tome_number(book.stem)
    try:
        return (float(number), book.name)
    except ValueError:
        return (float("inf"), book.name)


def discover_series_books(series_dir: Path | str) -> list[Path]:
    """Book YAMLs under ``<series_dir>/books/`` in reading order.

    Raises FileNotFoundError when the ``books/`` directory is absent or holds no
    YAML."""
    books_dir = Path(series_dir) / "books"
    books = sorted(books_dir.glob("*.yaml"), key=_sort_key)
    if not books:
        raise FileNotFoundError(f"No book YAML found under {books_dir}")
    return books


def series_vocabulary(book: Path | str) -> dict[str, list[str]]:
    """The name-canonicalization vocabulary for a series, read from its first
    tome's config (STU-719) — language properties every tome of one series
    declares alike, as the arc pass already assumes.

    ``classification.role_words`` is where a reader declares this book's titles;
    it *extends* the language pack here rather than replacing it, so naming a role
    the pack missed cannot silently drop the ones it knew.
    """
    cfg = yaml.safe_load(Path(book).read_text(encoding="utf-8")) or {}
    lang_cfg = load_lang_config(output_language(cfg), allow_en_fallback=True)
    classification = cfg.get("classification") or {}
    return {
        "role_words": list(dict.fromkeys(
            [str(w) for w in classification.get("role_words") or []]
            + [str(w) for w in lang_cfg.get("role_words") or []]
        )),
        "determiners": [str(w) for w in lang_cfg.get("determiners") or []],
        "connectors": [str(w) for w in lang_cfg.get("name_connectors") or []],
    }


def series_title(series_dir: Path | str) -> str:
    """Display title of a series, from its library directory name
    (``throne-of-glass`` -> ``Throne Of Glass``). The layout is the only series
    manifest there is (STU-487), so the directory name is the only declared name."""
    return Path(series_dir).name.replace("_", " ").replace("-", " ").title()


# --- Cross-tome assembly (STU-668) -----------------------------------------
#
# The series wiki is a pure function of every tome's already-persisted artifacts
# (STU-455 "disk is the bus" at series scope): no page mutation, no read-write
# wiki tools. The series registry is the identity join — one EntityRecord spans
# every tome (Gavriel-t2 == Gavriel-t3), its `aliases` union already carrying each
# tome's page title — so under A2 there is exactly one page per character and
# nothing to dedup (this is why STU-553's title-collision killer evaporates).


@dataclass
class TomeArtifacts:
    """One tome's persisted contribution, as read from its own ``processing_output``.

    ``pages`` is that tome's exportable ``wiki_pages.json`` set; ``status_verdicts``
    the ``entity_status.json`` ``verdicts`` map (canonical name -> verdict); ``events``
    the ``events.json`` list. Callers pass these in **reading order**.
    """

    book_id: str
    title: str = ""
    pages: list[dict] = field(default_factory=list)
    status_verdicts: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)


@dataclass
class TomeContribution:
    book_id: str
    tome_number: str
    title: str = ""
    page: dict | None = None
    status: dict | None = None
    events: list[dict] = field(default_factory=list)


@dataclass
class SeriesCharacter:
    """One merged character across the whole series — the unit the series wiki
    renders as a single page."""

    entity_id: str
    canonical_name: str
    entity_type: str
    aliases: list[str] = field(default_factory=list)
    contributions: list[TomeContribution] = field(default_factory=list)
    importance: str = "figurant"
    status: dict | None = None

    @property
    def books(self) -> list[str]:
        """Tome slugs where the character has a page, in reading order."""
        return [c.book_id for c in self.contributions if c.page]


def reconcile_importance(contributions: list[TomeContribution]) -> str:
    """Highest notability tier the entity reached in any tome (STU-719).

    Not latest-wins like Status, because the two questions differ: "is she
    alive?" is answered at the furthest reading position, "is she a main
    character of this *series*?" by the series as a whole. Reading the last tome
    as the verdict dropped the Scarecrow — principal in book 1, a walk-on in
    book 6 — out of the Oz hub entirely. Operates on the resolved tier
    (``WikiPage.importance``), never the raw percentile, which is deliberately
    non-comparable across tomes (STU-509/513). ``figurant`` when no tome typed it.
    """
    tiers = [
        str(c.page["importance"])
        for c in contributions
        if c.page and str(c.page.get("importance") or "") in TIERS
    ]
    return max(tiers, key=TIERS.index) if tiers else "figurant"


def reconcile_status(contributions: list[TomeContribution]) -> dict | None:
    """Latest-wins status verdict — the state at the furthest reading position.
    ``None`` when no tome delivered a verdict (renders the slot's ``unknown``)."""
    for contribution in reversed(contributions):
        if contribution.status:
            return contribution.status
    return None


def load_tome_artifacts(processing_dir: Path | str, book_id: str) -> TomeArtifacts:
    """Read one tome's ``{wiki_pages,entity_status,events}.json`` from disk,
    tolerant of any being absent (a tome that never ran a stage contributes
    nothing for it, never fails the assemble)."""
    base = Path(processing_dir)

    def _read(name: str) -> dict:
        path = base / name
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    pages = _read("wiki_pages.json").get("pages")
    verdicts = _read("entity_status.json").get("verdicts")
    events = _read("events.json").get("events")
    title = str(_read("epub_data.json").get("title") or book_id)
    return TomeArtifacts(
        book_id=book_id,
        title=title,
        pages=[p for p in pages if isinstance(p, dict)] if isinstance(pages, list) else [],
        status_verdicts=verdicts if isinstance(verdicts, dict) else {},
        events=events if isinstance(events, list) else [],
    )


def _all_names(records: list[EntityRecord]) -> list[str]:
    """Every surface the grouped records carry, canonical names first, deduped."""
    names = [r.canonical_name for r in records] + [a for r in records for a in r.aliases]
    return list(dict.fromkeys(n for n in names if n))


def _match_page(pages: list[dict], keys: set[str], determiners: Iterable[str]) -> dict | None:
    for page in pages:
        if canonical_key(page.get("title") or "", determiners) in keys:
            return page
    return None


def _match_status(
    verdicts: dict[str, dict], keys: set[str], determiners: Iterable[str]
) -> dict | None:
    for name, verdict in verdicts.items():
        if canonical_key(name, determiners) in keys and isinstance(verdict, dict):
            return verdict
    return None


def _match_events(
    events: list[dict], keys: set[str], determiners: Iterable[str]
) -> list[dict]:
    return [
        e for e in events
        if keys & {canonical_key(p, determiners) for p in (e.get("participants") or [])}
    ]


def group_records(
    registry: Registry, determiners: Iterable[str] = ()
) -> list[list[EntityRecord]]:
    """Registry records grouped into one group per cross-tome entity (STU-719).

    The registry accumulates tome N onto tomes 1..N-1 by ``normalize_name``, which
    folds case and accents only — so a tome spelling the character ``Sawhorse``
    where an earlier one wrote ``Saw-Horse`` lands as a second record and the
    series renders two pages. Grouping on ``canonical_key`` closes that gap at the
    merge, per entity type (a PERSON and a PLACE homonym stay distinct, STU-506).

    Groups are in registry order, and so are the records inside each one.
    """
    groups: dict[tuple[str, str], list[EntityRecord]] = {}
    for record in registry.entities:
        key = canonical_key(record.canonical_name, determiners)
        groups.setdefault((key or record.entity_id, record.entity_type), []).append(record)
    return list(groups.values())


def group_display_name(records: list[EntityRecord], determiners: Iterable[str] = ()) -> str:
    """The page title for a merged group: the most reader-facing spelling of its
    canonical name. Chosen among the surfaces sharing the group's key, so it is
    never another referent's alias — ``Tin Woodman`` never becomes ``Nick``."""
    names = _all_names(records)
    group_key = canonical_key(records[0].canonical_name, determiners)
    same_key = [n for n in names if canonical_key(n, determiners) == group_key]
    return preferred_display_name(same_key or names, determiners)


def build_series_characters(
    registry: Registry,
    tomes: list[TomeArtifacts],
    *,
    role_words: Iterable[str] = (),
    determiners: Iterable[str] = (),
    connectors: Iterable[str] = (),
) -> list[SeriesCharacter]:
    """One ``SeriesCharacter`` per cross-tome entity that has a page in some tome.

    ``tomes`` are in reading order; each character's contributions preserve that
    order. Identity is the series registry's, canonicalized across tomes
    (:func:`group_records`) — an entity's page in any tome is the one whose title
    matches any surface of its group, so a tome that renamed or respelled it still
    joins. Notability is the highest tier reached in any tome.

    An entity whose name is a generic role (``King``, ``Queen``) is dropped: it
    names a different referent in every tome, so one merged page would be a
    fiction. ``role_words`` empty disables the drop.

    All entity types merge cross-tome (STU-706), not just PERSON. Status
    (alive/dead) is PERSON-only — the reader-facing slot for non-PERSON drops,
    matching the infobox (``series_pages._infobox_fields``).
    """
    characters: list[SeriesCharacter] = []
    for records in group_records(registry, determiners):
        entity_type = records[0].entity_type
        is_person = entity_type == "PERSON"
        names = _all_names(records)
        keys = {k for k in (canonical_key(n, determiners) for n in names) if k}
        contributions: list[TomeContribution] = []
        for tome in tomes:
            page = _match_page(tome.pages, keys, determiners)
            status = _match_status(tome.status_verdicts, keys, determiners) if is_person else None
            events = _match_events(tome.events, keys, determiners)
            if page or status or events:
                contributions.append(
                    TomeContribution(
                        book_id=tome.book_id,
                        tome_number=tome_number(tome.book_id),
                        title=tome.title,
                        page=page,
                        status=status,
                        events=events,
                    )
                )
        if not any(c.page for c in contributions):
            continue
        canonical = group_display_name(records, determiners)
        if is_generic_role_name(canonical, role_words, determiners, connectors):
            continue
        characters.append(
            SeriesCharacter(
                entity_id=records[0].entity_id,
                canonical_name=canonical,
                entity_type=entity_type,
                aliases=names,
                contributions=contributions,
                importance=reconcile_importance(contributions),
                status=reconcile_status(contributions),
            )
        )
    return characters


def link_targets(
    registry: Registry,
    characters: list[SeriesCharacter],
    *,
    role_words: Iterable[str] = (),
    determiners: Iterable[str] = (),
    connectors: Iterable[str] = (),
) -> dict[str, str]:
    """``canonical_key(surface) -> series page title``, for every surface any tome
    could have linked (STU-719).

    A tome links whatever it called the entity, so its pages carry
    ``[[Nick Chopper]]``, ``[[The Scarecrow]]`` and ``[[WIZARD]]`` — one character
    exploded into three targets, none of them the series page title. Every alias
    the registry knows maps here, plus every spelling variant ``canonical_key``
    folds, so the merged page links resolve to one page per entity.

    Every surface of an entity dropped as a generic role maps to the empty string
    — including the ones that read like a name (``Queen of Ev`` is the dropped
    ``Queen``'s alias) — and the renderer unlinks them instead of leaving links to
    a page that no longer exists.
    """
    targets: dict[str, str] = {}
    for character in characters:
        for name in [character.canonical_name, *character.aliases]:
            key = canonical_key(name, determiners)
            if key:
                targets.setdefault(key, character.canonical_name)
    for records in group_records(registry, determiners):
        display = group_display_name(records, determiners)
        if not is_generic_role_name(display, role_words, determiners, connectors):
            continue
        for name in _all_names(records):
            key = canonical_key(name, determiners)
            if key:
                targets.setdefault(key, "")
    return targets
