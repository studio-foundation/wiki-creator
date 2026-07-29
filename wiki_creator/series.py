"""Series discovery — enumerate a series' book YAMLs in reading order (STU-487).

Pure logic over the existing library layout
(``library/<author>/<series>/books/NN_*.yaml``, already numbered); no ad-hoc
series manifest. Consumed by ``make run-series`` to run the tomes in
order, propagating the accumulated series registry from one tome to the next.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from wiki_creator.registry import Registry, normalize_name
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
    pages: list[dict] = field(default_factory=list)
    status_verdicts: dict[str, dict] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)


@dataclass
class TomeContribution:
    book_id: str
    tome_number: str
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
    """Latest-wins notability tier — the resolved tier of the furthest reading
    position, consistent with Status (STU-668). Operates on the resolved tier
    (``WikiPage.importance``), never the raw percentile, which is deliberately
    non-comparable across tomes (STU-509/513). ``figurant`` when no tome typed it.
    """
    for contribution in reversed(contributions):
        page = contribution.page
        if page and page.get("importance"):
            return str(page["importance"])
    return "figurant"


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
    return TomeArtifacts(
        book_id=book_id,
        pages=[p for p in pages if isinstance(p, dict)] if isinstance(pages, list) else [],
        status_verdicts=verdicts if isinstance(verdicts, dict) else {},
        events=events if isinstance(events, list) else [],
    )


def _name_set(record) -> set[str]:
    return {normalize_name(n) for n in (record.canonical_name, *record.aliases) if n}


def _match_page(pages: list[dict], names: set[str]) -> dict | None:
    for page in pages:
        if normalize_name(page.get("title") or "") in names:
            return page
    return None


def _match_status(verdicts: dict[str, dict], names: set[str]) -> dict | None:
    for name, verdict in verdicts.items():
        if normalize_name(name) in names and isinstance(verdict, dict):
            return verdict
    return None


def _match_events(events: list[dict], names: set[str]) -> list[dict]:
    return [
        e for e in events
        if names & {normalize_name(p) for p in (e.get("participants") or [])}
    ]


def build_series_characters(
    registry: Registry, tomes: list[TomeArtifacts]
) -> list[SeriesCharacter]:
    """One ``SeriesCharacter`` per canonical entity that has a page in some tome.

    ``tomes`` are in reading order; each character's contributions preserve that
    order. Identity is the series registry's — an entity's page in any tome is
    the one whose title matches its canonical name or any accumulated alias, so a
    tome that renamed it still joins. Notability is reconciled latest-wins.

    All entity types merge cross-tome (STU-706), not just PERSON. Status
    (alive/dead) is PERSON-only — the reader-facing slot for non-PERSON drops,
    matching the infobox (``series_pages._infobox_fields``).
    """
    characters: list[SeriesCharacter] = []
    for record in registry.entities:
        is_person = record.entity_type == "PERSON"
        names = _name_set(record)
        contributions: list[TomeContribution] = []
        for tome in tomes:
            page = _match_page(tome.pages, names)
            status = _match_status(tome.status_verdicts, names) if is_person else None
            events = _match_events(tome.events, names)
            if page or status or events:
                contributions.append(
                    TomeContribution(
                        book_id=tome.book_id,
                        tome_number=tome_number(tome.book_id),
                        page=page,
                        status=status,
                        events=events,
                    )
                )
        if not any(c.page for c in contributions):
            continue
        characters.append(
            SeriesCharacter(
                entity_id=record.entity_id,
                canonical_name=record.canonical_name,
                entity_type=record.entity_type,
                aliases=list(record.aliases),
                contributions=contributions,
                importance=reconcile_importance(contributions),
                status=reconcile_status(contributions),
            )
        )
    return characters
