"""Canon policy — which source is authoritative for a series (STU-512).

Declared in ``library/<author>/<series>/canon.yaml``. Every series currently
ships a single EPUB per tome, so the policy only records what is already true de
facto. It exists so the arbitration rule is written down *before* a second
source of truth on the same content (``scripts/scrape_fandom.py``) is ever wired
into wiki generation.

Canon decides which bytes are read; the book YAML's ``file_path`` stays the
pipeline's identity anchor (it derives every output path).

No policy degrades, a broken policy fails. Absent/empty ``canon.yaml``, or a book
it does not declare, reads ``file_path``. Malformed ``canon.yaml`` raises: a
broken authority file ignored is a source nobody vouched for.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from wiki_creator.paths import book_paths_from_epub


STRATEGIES = ("highest_authority", "primary_wins", "flag_for_review")
ON_UNRESOLVED = ("flag", "fail")


@dataclass(frozen=True)
class CanonSource:
    id: str
    type: str
    path: str
    book: str
    authority: int = 0


@dataclass(frozen=True)
class Canon:
    primary_source: str
    sources: tuple[CanonSource, ...]
    series_dir: Path
    strategy: str = "highest_authority"
    on_unresolved: str = "flag"
    later_tome_overrides: bool = False

    def resolve_source(self, slug: str) -> CanonSource | None:
        """The authoritative source for book ``slug``, or None when undeclared."""
        candidates = [s for s in self.sources if s.book == slug]
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        winner = self._arbitrate(candidates)
        if winner is not None:
            return winner

        ids = ", ".join(s.id for s in candidates)
        message = f"'{self.strategy}' cannot arbitrate book '{slug}' between {ids}"
        if self.on_unresolved == "fail":
            raise ValueError(f"canon: {message}")
        fallback = next(
            (s for s in candidates if s.type == self.primary_source), candidates[0]
        )
        print(
            f"[canon] warning: {message}; falling back to '{fallback.id}'",
            file=sys.stderr,
        )
        return fallback

    def source_path(self, source: CanonSource) -> Path:
        return self.series_dir / source.path

    def _arbitrate(self, candidates: list[CanonSource]) -> CanonSource | None:
        if self.strategy == "primary_wins":
            primary = [s for s in candidates if s.type == self.primary_source]
            return primary[0] if len(primary) == 1 else None
        if self.strategy == "highest_authority":
            top = max(s.authority for s in candidates)
            best = [s for s in candidates if s.authority == top]
            return best[0] if len(best) == 1 else None
        return None  # flag_for_review — never auto-arbitrates


def _parse_source(raw: object, path: Path) -> CanonSource:
    if not isinstance(raw, dict):
        raise ValueError(f"canon: each source in {path} must be a mapping, got {raw!r}")
    source_path = str(raw.get("path") or "")
    if not source_path:
        raise ValueError(f"canon: source '{raw.get('id')}' in {path} declares no path")
    authority = raw.get("authority", 0)
    if isinstance(authority, bool) or not isinstance(authority, int):
        raise ValueError(
            f"canon: authority of '{raw.get('id')}' in {path} must be an integer, "
            f"got {authority!r}"
        )
    return CanonSource(
        id=str(raw.get("id", "")),
        type=str(raw.get("type", "")),
        path=source_path,
        # The tome a source speaks for. Defaults to the filename: a book's own
        # EPUB is already named after it.
        book=str(raw.get("book") or Path(source_path).stem),
        authority=authority,
    )


def load_canon(path: Path | str) -> Canon | None:
    """Parse a series ``canon.yaml``.

    None when no policy is declared (absent, empty, or no ``canon:`` block).
    ValueError when one is declared but malformed.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"canon: {path} is not valid YAML ({e})") from e
    if not isinstance(raw, dict):
        raise ValueError(f"canon: {path} must be a mapping, got {type(raw).__name__}")
    block = raw.get("canon") or {}
    if not block:
        return None

    sources = tuple(_parse_source(s, path) for s in block.get("sources") or [])
    if not sources:
        raise ValueError(f"canon: {path} declares no sources")
    duplicates = sorted({s.id for s in sources if [x.id for x in sources].count(s.id) > 1})
    if duplicates:
        raise ValueError(f"canon: duplicate source id(s) {', '.join(duplicates)} in {path}")

    primary_source = str(block.get("primary_source", ""))
    if not any(s.type == primary_source for s in sources):
        raise ValueError(
            f"canon: primary_source '{primary_source}' matches no declared source type "
            f"in {path}"
        )

    # Validated at load, not at arbitration: a typo would otherwise sit silent
    # until a tome declares a second source.
    conflict = block.get("conflict_resolution") or {}
    strategy = str(conflict.get("strategy", "highest_authority"))
    on_unresolved = str(conflict.get("on_unresolved", "flag"))
    for key, value, allowed in (
        ("strategy", strategy, STRATEGIES),
        ("on_unresolved", on_unresolved, ON_UNRESOLVED),
    ):
        if value not in allowed:
            raise ValueError(
                f"canon: unknown conflict_resolution.{key} '{value}' in {path} "
                f"(expected one of {', '.join(allowed)})"
            )

    cross_tome = block.get("cross_tome") or {}
    return Canon(
        primary_source=primary_source,
        sources=sources,
        series_dir=path.parent,
        strategy=strategy,
        on_unresolved=on_unresolved,
        later_tome_overrides=bool(cross_tome.get("later_tome_overrides", False)),
    )


def resolve_book_source(file_path: Path | str) -> Path:
    """The file to read for the book anchored at ``file_path``.

    Falls back to ``file_path`` when the series declares no canon, or declares
    no source for this book.
    """
    paths = book_paths_from_epub(file_path)
    canon = load_canon(paths.series_canon)
    if canon is None:
        return Path(file_path)
    source = canon.resolve_source(paths.processing.name)
    if source is None:
        print(
            f"[canon] warning: {paths.series_canon} declares no source for "
            f"'{paths.processing.name}'; reading {file_path}",
            file=sys.stderr,
        )
        return Path(file_path)
    return canon.source_path(source)
