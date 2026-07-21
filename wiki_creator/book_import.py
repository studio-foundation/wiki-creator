"""Import an EPUB into the library and scaffold its book YAML (STU-597).

`wiki generate-books <epub>` reads the epub's title/author metadata, places a
copy at ``<root>/<author>/<series>/books/NN-<slug>.epub`` and writes a minimal
book YAML beside it. Minimal by design: the load-bearing, reader-authored fields
(``ner.invented_names``, ``notability``, ``classification`` roles) are decided by
someone who read the novel and measured against it — the project never guesses
them (see CLAUDE.md "Config Is Read By People Who Know Books"). ``--llm`` only
drafts low-risk prose (a ``novel_summary``) for the reader to review.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from wiki_creator.registry import entity_slug

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def read_metadata(epub_path: Path | str) -> tuple[str, str | None]:
    """(title, author) from the epub's Dublin Core metadata."""
    import ebooklib  # noqa: F401  (side-effect import kept next to epub)
    from ebooklib import epub

    book = epub.read_epub(str(epub_path))
    title = book.get_metadata("DC", "title")
    author = book.get_metadata("DC", "creator")
    return (
        title[0][0] if title else "Unknown",
        author[0][0] if author else None,
    )


@dataclass(frozen=True)
class ImportPlan:
    dest_epub: Path  # relative to root
    dest_yaml: Path  # relative to root
    yaml_text: str


def render_yaml(rel_epub: Path, title: str, author: str | None, summary: str | None) -> str:
    by = f" by {author}" if author else ""
    block = [
        "description: |",
        f'  Build a wiki for "{title}"{by}.',
        "  Parse the book, extract all named entities (characters, locations, organizations, events),",
        "  resolve aliases, and generate Markdown wiki pages for each entity.",
        "",
        f"file_path: {rel_epub.as_posix()}",
        "spacy_model: en_core_web_lg",
        "",
        "coref: false",
        "workers: 8",
        "",
        "min_mentions_absolute: 3",
    ]
    if summary:
        indented = "\n".join(f"  {line}" for line in summary.strip().splitlines())
        block += ["", "novel_summary: |", indented]
    return "\n".join(block) + "\n"


def plan_import(
    epub_path: Path | str,
    title: str,
    author: str | None,
    *,
    root: Path | str = "library",
    author_slug: str | None = None,
    series_slug: str | None = None,
    number: str = "01",
    summary: str | None = None,
) -> ImportPlan:
    """Where the epub/yaml go and what the yaml says — pure, no IO."""
    author_slug = author_slug or entity_slug(author or "unknown_author")
    series_slug = series_slug or entity_slug(title)
    stem = f"{number}-{series_slug}"
    books_dir = Path(root) / author_slug / series_slug / "books"
    dest_epub = books_dir / f"{stem}.epub"
    dest_yaml = books_dir / f"{stem}.yaml"
    return ImportPlan(
        dest_epub=dest_epub,
        dest_yaml=dest_yaml,
        yaml_text=render_yaml(dest_epub, title, author, summary),
    )


def generate_book(
    epub_path: Path | str,
    *,
    root: Path | str = "library",
    author_slug: str | None = None,
    series_slug: str | None = None,
    number: str = "01",
    force: bool = False,
    dry_run: bool = False,
    enrich: Callable[[str, str | None], str] | None = None,
    base: Path | None = None,
) -> ImportPlan:
    """Import one epub. Copies the epub and writes the YAML unless dry_run.

    `enrich(title, author) -> summary` supplies the optional `--llm` prose.
    `base` anchors relative dest paths (defaults to the project root).
    """
    epub_path = Path(epub_path)
    if not epub_path.is_file():
        raise FileNotFoundError(f"no such epub: {epub_path}")
    title, author = read_metadata(epub_path)
    summary = enrich(title, author) if enrich else None
    plan = plan_import(
        epub_path, title, author,
        root=root, author_slug=author_slug, series_slug=series_slug,
        number=number, summary=summary,
    )
    anchor = Path(base) if base is not None else _PROJECT_ROOT
    dest_epub, dest_yaml = anchor / plan.dest_epub, anchor / plan.dest_yaml
    if dest_yaml.exists() and not force:
        raise FileExistsError(f"{plan.dest_yaml} exists (use --force to overwrite)")
    if not dry_run:
        dest_epub.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(epub_path, dest_epub)
        dest_yaml.write_text(plan.yaml_text, encoding="utf-8")
    return plan
