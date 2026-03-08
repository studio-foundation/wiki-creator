from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BookPaths:
    epub: Path
    processing: Path   # …/processing_output/<slug>/
    wiki_inputs: Path  # …/wiki_inputs/<slug>/
    output: Path       # …/output/<slug>/


def book_paths_from_epub(epub_path: Path | str) -> BookPaths:
    """Derive all book working directories from the epub path.

    Expects structure: library/<author>/<series>/books/<slug>.epub
    Returns paths relative to the project root (CWD).
    """
    p = Path(epub_path)
    series_dir = p.parent.parent  # up from books/
    slug = p.stem
    return BookPaths(
        epub=p,
        processing=series_dir / "processing_output" / slug,
        wiki_inputs=series_dir / "wiki_inputs" / slug,
        output=series_dir / "output" / slug,
    )


def book_paths_from_yaml(yaml_path: Path | str) -> BookPaths:
    """Derive all book working directories from the yaml config path.

    Expects structure: library/<author>/<series>/books/<slug>.yaml
    """
    p = Path(yaml_path)
    series_dir = p.parent.parent
    slug = p.stem
    epub = series_dir / "books" / f"{slug}.epub"
    return book_paths_from_epub(epub)
