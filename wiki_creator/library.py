"""Library discovery and short-alias resolution for the `wiki` CLI (STU-597).

Pure logic over the existing library layout
(``<root>/<author>/<series>/books/NN_slug.yaml`` under ``library/`` and
``public_domain/``); no manifest. A book resolves from a short query — its
slug, series, author, or an explicit ``aliases:`` list in the book YAML (so an
acronym like ``tog`` reaches throne-of-glass). Series resolve from the series
directory name.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBRARY_ROOTS = ("library", "public_domain")


@dataclass(frozen=True)
class BookEntry:
    yaml_path: Path  # relative to project root
    slug: str
    series: str
    author: str
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def keys(self) -> tuple[str, ...]:
        """Every string this book answers to, exact-match first."""
        return (self.slug, *self.aliases, self.series, self.author)


def _read_aliases(yaml_path: Path) -> tuple[str, ...]:
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return ()
    raw = data.get("aliases") if isinstance(data, dict) else None
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(a) for a in raw)
    return ()


def discover_books(root: Path | str | None = None) -> list[BookEntry]:
    """Every book YAML under the library roots, sorted by path."""
    base = Path(root) if root is not None else _PROJECT_ROOT
    entries: list[BookEntry] = []
    for lib in LIBRARY_ROOTS:
        for yaml_path in sorted((base / lib).glob("*/*/books/*.yaml")):
            rel = yaml_path.relative_to(base)
            # <root>/<author>/<series>/books/<slug>.yaml
            entries.append(
                BookEntry(
                    yaml_path=rel,
                    slug=yaml_path.stem,
                    series=yaml_path.parent.parent.name,
                    author=yaml_path.parent.parent.parent.name,
                    aliases=_read_aliases(yaml_path),
                )
            )
    return sorted(entries, key=lambda e: str(e.yaml_path))


def discover_series(root: Path | str | None = None) -> dict[str, Path]:
    """Series directory name -> path (relative to project root), for series
    holding at least one book YAML."""
    base = Path(root) if root is not None else _PROJECT_ROOT
    series: dict[str, Path] = {}
    for book in discover_books(root):
        series_dir = (base / book.yaml_path).parent.parent.relative_to(base)
        series[series_dir.name] = series_dir
    return series


class ResolutionError(ValueError):
    """A query matched no book/series, or was ambiguous."""


def _suggest(query: str, candidates: list[str]) -> str:
    hits = [c for c in candidates if query.lower() in c.lower()]
    pool = hits or candidates
    return ", ".join(sorted(pool)[:8])


def resolve_book(query: str, root: Path | str | None = None) -> Path:
    """Resolve a short query to a book YAML path (relative to project root).

    Exact match on slug or alias wins; else a unique substring match across
    slug/alias/series/author. Ambiguous or empty raises ResolutionError.
    """
    books = discover_books(root)
    q = query.lower()

    exact = [b for b in books if q in (k.lower() for k in (b.slug, *b.aliases))]
    if len(exact) == 1:
        return exact[0].yaml_path
    if len(exact) > 1:
        raise ResolutionError(
            f"{query!r} matches several books: "
            + ", ".join(b.slug for b in exact)
        )

    substr = [b for b in books if any(q in k.lower() for k in b.keys)]
    if len(substr) == 1:
        return substr[0].yaml_path
    if len(substr) > 1:
        raise ResolutionError(
            f"{query!r} is ambiguous: "
            + ", ".join(b.slug for b in substr)
        )
    raise ResolutionError(
        f"no book matches {query!r}. Try: "
        + _suggest(query, [b.slug for b in books])
    )


def resolve_series(query: str, root: Path | str | None = None) -> Path:
    """Resolve a short query to a series directory (relative to project root)."""
    series = discover_series(root)
    q = query.lower()
    if query in series:
        return series[query]

    substr = [name for name in series if q in name.lower()]
    if len(substr) == 1:
        return series[substr[0]]
    if len(substr) > 1:
        raise ResolutionError(
            f"{query!r} is ambiguous: " + ", ".join(sorted(substr))
        )
    raise ResolutionError(
        f"no series matches {query!r}. Try: " + _suggest(query, list(series))
    )
