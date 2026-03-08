# Design: Library Structure Reorganization

**Date:** 2026-03-08
**Status:** Approved

## Problem

All data files (books, intermediate processing files, outputs) are either flat or
scattered across multiple top-level directories with no per-book isolation:

- `books/` — organized by author but no series level
- `processing_output/` — flat, all books share the same files (overwritten on each run)
- `wiki_inputs/` — flat
- `output/wiki/` — flat
- `persons_full.json`, `places_full.json`, `orgs_full.json`, `chapters.json` — hardcoded at project root

Processing two different books sequentially corrupts the intermediate files of the first.

## Design

### Directory Structure

A single `library/` root separates all data/content from the software (scripts, wiki_creator, Makefile, etc.).

Within `library/`, the hierarchy is `author / series / {books, processing_output, wiki_inputs, output}`:

```
library/
  sarah_j_maas/
    throne-of-glass/
      books/
        01-throne-of-glass.epub
        01-throne-of-glass.yaml
      processing_output/
        01-throne-of-glass/
          epub_data.json
          splits.json
          entities_classified.json
          wiki_pages.json
          persons_full.json
          places_full.json
          orgs_full.json
          chapters.json
      wiki_inputs/
        01-throne-of-glass/
          batch_001.json
          ...
      output/
        01-throne-of-glass/
          Character_Name.wiki
          ...

  carlos-ruiz-zafon/
    el-cementerio-de-los-libros-olvidados/
      books/
        02-le-jeu-de-lange.epub
        02-le-jeu-de-lange.yaml
      processing_output/
        02-le-jeu-de-lange/
          ...
      wiki_inputs/
        02-le-jeu-de-lange/
          ...
      output/
        02-le-jeu-de-lange/
          ...
```

Everything related to a series lives in one place. Adding a new book to a series means
adding files under that series folder only.

### Path Derivation

New module `wiki_creator/paths.py` derives all runtime paths from the yaml path:

```python
from pathlib import Path
from dataclasses import dataclass

@dataclass
class BookPaths:
    epub: Path
    processing: Path   # processing_output/<slug>/
    wiki_inputs: Path  # wiki_inputs/<slug>/
    output: Path       # output/<slug>/

def book_paths(yaml_path: Path) -> BookPaths:
    # yaml is at library/<author>/<series>/books/<slug>.yaml
    series_dir = yaml_path.parent.parent
    slug = yaml_path.stem
    return BookPaths(
        epub        = series_dir / "books" / f"{slug}.epub",
        processing  = series_dir / "processing_output" / slug,
        wiki_inputs = series_dir / "wiki_inputs" / slug,
        output      = series_dir / "output" / slug,
    )
```

All scripts that currently hardcode paths are updated to call `book_paths()`.

### File Migration

| Before | After |
|--------|-------|
| `books/sarah_j_maas/throne_of_glass.epub` | `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub` |
| `books/sarah_j_maas/throne_of_glass.yaml` | `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml` |
| `books/carlos-ruiz-zafon/le-jeu-de-lange.epub` | `library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.epub` |
| `books/carlos-ruiz-zafon/le-jeu-de-lange.yaml` | `library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.yaml` |

The root `books/` directory is removed after migration.

### .gitignore Updates

Generated/runtime files inside `library/` are gitignored:

```gitignore
library/**/processing_output/
library/**/wiki_inputs/
library/**/output/
```

Book files (`.epub`, `.yaml`) are committed.

### Makefile Update

```makefile
BOOK ?= library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
```

### YAML Config Update

The `file_path` field inside each yaml is updated to the new epub location:

```yaml
file_path: library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub
```

## Scope of Code Changes

1. **New:** `wiki_creator/paths.py` — `BookPaths` dataclass + `book_paths()` function
2. **Update:** all scripts that hardcode `processing_output/`, `wiki_inputs/`, `output/wiki/`, or root-level JSON files → use `book_paths()`
3. **Update:** `Makefile` — default `BOOK` path
4. **Update:** `.gitignore` — replace old patterns with `library/**/` patterns
5. **Update:** both `.yaml` config files — `file_path` field
6. **Migrate:** move files to new locations, remove old `books/` directory
