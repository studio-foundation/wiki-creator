from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

# Project root = directory containing wiki_creator (repo root)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve(path: Path | str) -> Path:
    """Resolve path relative to project root if not absolute."""
    p = Path(path)
    if p.is_absolute():
        return p
    return (_PROJECT_ROOT / p).resolve()


@dataclass
class BookPaths:
    epub: Path
    processing: Path   # …/processing_output/<slug>/
    wiki_inputs: Path  # …/wiki_inputs/<slug>/
    output: Path       # …/output/<slug>/

    @property
    def series_character_graph(self) -> Path:
        """Series-level graph: library/<author>/<series>/character_graph.json"""
        return self.epub.parent.parent / "character_graph.json"

    @property
    def book_graph_delta(self) -> Path:
        """Per-book delta graph: processing_output/<slug>/character_graph_delta.json"""
        return self.processing / "character_graph_delta.json"

    @property
    def series_registry(self) -> Path:
        """Series-level identity registry: library/<author>/<series>/registry.json"""
        return self.epub.parent.parent / "registry.json"

    @property
    def book_registry_delta(self) -> Path:
        """Per-book accumulation delta: processing_output/<slug>/registry_delta.json"""
        return self.processing / "registry_delta.json"


def book_paths_from_epub(epub_path: Path | str) -> BookPaths:
    """Derive all book working directories from the epub path.

    Expects structure: library/<author>/<series>/books/<slug>.epub
    Relative paths are resolved against the project root (repo root).
    """
    p = _resolve(epub_path)
    series_dir = p.parent.parent  # up from books/
    slug = p.stem
    if not slug:
        raise ValueError("epub path must have a non-empty stem (e.g. book.epub)")
    try:
        # Return paths relative to project root so CWD=project root works
        base = series_dir.relative_to(_PROJECT_ROOT)
    except ValueError:
        base = series_dir
    return BookPaths(
        epub=base / "books" / p.name,
        processing=base / "processing_output" / slug,
        wiki_inputs=base / "wiki_inputs" / slug,
        output=base / "output" / slug,
    )


def book_paths_from_yaml(yaml_path: Path | str) -> BookPaths:
    """Derive all book working directories from the yaml config path.

    Expects structure: library/<author>/<series>/books/<slug>.yaml
    Relative paths are resolved against the project root (repo root).
    """
    p = _resolve(yaml_path)
    series_dir = p.parent.parent
    slug = p.stem
    epub = series_dir / "books" / f"{slug}.epub"
    return book_paths_from_epub(epub)
