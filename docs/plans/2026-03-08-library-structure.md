# Library Structure Reorganization — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reorganize all book data under `library/<author>/<series>/` with `books/`, `processing_output/`, `wiki_inputs/`, and `output/` subdirs per series.

**Architecture:** A new `wiki_creator/paths.py` module derives all runtime paths from the epub/yaml path. Every script that currently hardcodes `processing_output/`, `wiki_inputs/`, `output/wiki/`, or root-level JSON filenames is updated to call `book_paths_from_epub()`. The studio pipeline context already propagates `file_path` (the epub path) in `additional_context` for all stages that include `input` — one stage (`split-clusters` in wiki-extraction) needs `input` added to its context.

**Tech Stack:** Python 3.11+, pathlib, pytest, Studio pipeline YAMLs

---

### Task 1: Create `wiki_creator/paths.py` (TDD)

**Files:**
- Create: `wiki_creator/paths.py`
- Create: `tests/test_paths.py`

**Step 1: Write the failing test**

```python
# tests/test_paths.py
from pathlib import Path
from wiki_creator.paths import book_paths_from_epub, book_paths_from_yaml

def test_book_paths_from_epub():
    paths = book_paths_from_epub("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub")
    assert paths.epub == Path("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub")
    assert paths.processing == Path("library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass")
    assert paths.wiki_inputs == Path("library/sarah_j_maas/throne-of-glass/wiki_inputs/01-throne-of-glass")
    assert paths.output == Path("library/sarah_j_maas/throne-of-glass/output/01-throne-of-glass")

def test_book_paths_from_yaml():
    paths = book_paths_from_yaml("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml")
    assert paths.epub == Path("library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub")
    assert paths.processing == Path("library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass")
    assert paths.wiki_inputs == Path("library/sarah_j_maas/throne-of-glass/wiki_inputs/01-throne-of-glass")
    assert paths.output == Path("library/sarah_j_maas/throne-of-glass/output/01-throne-of-glass")

def test_paths_accept_path_object():
    p = Path("library/carlos-ruiz-zafon/el-cementerio/books/02-le-jeu.epub")
    paths = book_paths_from_epub(p)
    assert paths.processing == Path("library/carlos-ruiz-zafon/el-cementerio/processing_output/02-le-jeu")
```

**Step 2: Run test to confirm it fails**

```bash
pytest tests/test_paths.py -v
```
Expected: ImportError (module doesn't exist yet)

**Step 3: Implement `wiki_creator/paths.py`**

```python
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
```

**Step 4: Run test to confirm it passes**

```bash
pytest tests/test_paths.py -v
```
Expected: 3 PASSED

**Step 5: Commit**

```bash
git add wiki_creator/paths.py tests/test_paths.py
git commit -m "feat(paths): add BookPaths module for library structure"
```

---

### Task 2: Migrate existing book files

**Files:**
- Create dirs: `library/sarah_j_maas/throne-of-glass/books/`, `library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/`
- Move: all files under `books/` to new locations

**Step 1: Create the new directory structure**

```bash
mkdir -p library/sarah_j_maas/throne-of-glass/books
mkdir -p library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books
```

**Step 2: Move book files with git mv**

```bash
git mv books/sarah_j_maas/throne_of_glass.epub \
    library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub
git mv books/sarah_j_maas/throne_of_glass.yaml \
    library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
git mv books/carlos-ruiz-zafon/le-jeu-de-lange.epub \
    library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.epub
git mv books/carlos-ruiz-zafon/le-jeu-de-lange.yaml \
    library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.yaml
```

**Step 3: Remove the now-empty `books/` directory**

```bash
rmdir books/sarah_j_maas books/carlos-ruiz-zafon books/
```

**Step 4: Update `file_path` in each yaml config**

In `library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml`, change:
```yaml
# before
file_path: books/sarah_j_maas/throne_of_glass.epub
# after
file_path: library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub
```

In `library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.yaml`, change:
```yaml
# before
file_path: books/carlos-ruiz-zafon/le-jeu-de-lange.epub
# after
file_path: library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/books/02-le-jeu-de-lange.epub
```

Also remove the `export.wiki_dir` field from both yamls (it will be derived from paths now):
```yaml
# remove this block entirely:
export:
  wiki_dir: output/wiki
  ...
# keep only:
export:
  categories:
    language: en
    labels:
      ...
```

**Step 5: Commit**

```bash
git add library/ && git rm -r books/
git commit -m "feat(library): migrate books to library/<author>/<series>/books/ structure"
```

---

### Task 3: Update `.gitignore` and `Makefile`

**Files:**
- Modify: `.gitignore`
- Modify: `Makefile`

**Step 1: Update `.gitignore`**

Replace the bottom section:

```gitignore
# Before (remove these lines):
persons_full.json
places_full.json
orgs_full.json
extraction-*.jsonl
chapters.json
wiki_inputs/
books/
!books/**/*.yaml
processing_output/
.wiki_runs/
!processing_output/.gitkeep
output/wiki/

# After (add these lines):
# Library — generated runtime data (books tracked, processing ignored)
library/**/processing_output/
library/**/wiki_inputs/
library/**/output/
# Legacy root-level artifacts (keep during transition, remove when all scripts updated)
persons_full.json
places_full.json
orgs_full.json
extraction-*.jsonl
chapters.json
# Orchestrator state
.wiki_runs/
```

**Step 2: Add `.gitkeep` files in each series**

```bash
mkdir -p library/sarah_j_maas/throne-of-glass/processing_output
mkdir -p library/sarah_j_maas/throne-of-glass/wiki_inputs
mkdir -p library/sarah_j_maas/throne-of-glass/output
mkdir -p library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/processing_output
mkdir -p library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/wiki_inputs
mkdir -p library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/output
touch library/sarah_j_maas/throne-of-glass/processing_output/.gitkeep
touch library/sarah_j_maas/throne-of-glass/wiki_inputs/.gitkeep
touch library/sarah_j_maas/throne-of-glass/output/.gitkeep
touch library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/processing_output/.gitkeep
touch library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/wiki_inputs/.gitkeep
touch library/carlos-ruiz-zafon/el-cementerio-de-los-libros-olvidados/output/.gitkeep
```

**Step 3: Update `Makefile`**

```makefile
# Change default BOOK:
BOOK ?= library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml

# Update clean target to use new paths (derive from BOOK):
clean:
	@SERIES_DIR=$$(python -c "from wiki_creator.paths import book_paths_from_yaml; p = book_paths_from_yaml('$(BOOK)'); print(p.processing.parent.parent)"); \
	find $$SERIES_DIR/processing_output $$SERIES_DIR/wiki_inputs $$SERIES_DIR/output \
	     -not -name '.gitkeep' -delete 2>/dev/null || true
```

**Step 4: Commit**

```bash
git add .gitignore Makefile library/
git commit -m "feat(library): update gitignore and Makefile for new structure"
```

---

### Task 4: Add `input` context to `split-clusters` stage in wiki-extraction pipeline

**Files:**
- Modify: `.studio/pipelines/wiki-extraction.pipeline.yaml`

`split_clusters.py` writes `processing_output/splits.json` but currently has no `input` context, so it can't derive the epub path. Fix:

**Step 1: Edit pipeline yaml**

In `wiki-extraction.pipeline.yaml`, find the `split-clusters` stage and add `input`:

```yaml
  - name: split-clusters
    kind: extraction
    executor: script
    runtime: python
    script: scripts/split_clusters.py
    contract: split-clusters
    context:
      include:
        - input                    # ← add this line
        - previous_stage_output
```

**Step 2: Commit**

```bash
git add .studio/pipelines/wiki-extraction.pipeline.yaml
git commit -m "fix(pipeline): add input context to split-clusters stage"
```

---

### Task 5: Add `_get_book_paths` helper — shared pattern for all Studio scripts

All Studio scripts will use this identical pattern to get paths from the payload. Rather than copy-pasting it, document it here once — each script adds these lines near the top of its `main()` / executor block:

```python
import yaml
from wiki_creator.paths import book_paths_from_epub, BookPaths

def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)
```

No commit needed — this is reference code used in the following tasks.

---

### Task 6: Update `scripts/parse_epub.py`

**Files:**
- Modify: `scripts/parse_epub.py`

Currently writes `processing_output/epub_data.json` hardcoded at project root.

**Step 1: Find the write block** (around line 253)

```python
# Before:
os.makedirs("processing_output", exist_ok=True)
with open("processing_output/epub_data.json", "w", encoding="utf-8") as _f:
    json.dump(result, _f, ensure_ascii=False)

# After:
paths = _paths_from_payload(payload)
paths.processing.mkdir(parents=True, exist_ok=True)
with open(paths.processing / "epub_data.json", "w", encoding="utf-8") as _f:
    json.dump(result, _f, ensure_ascii=False)
```

Add `_paths_from_payload` helper (from Task 5) to the file's imports/helpers section.

**Step 2: Verify manually**

```bash
echo '{"additional_context": "file_path: library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.epub\n"}' \
  | python scripts/parse_epub.py
ls library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/epub_data.json
```

Expected: file exists at new path.

**Step 3: Commit**

```bash
git add scripts/parse_epub.py
git commit -m "feat(parse_epub): write epub_data.json to library/<series>/processing_output/"
```

---

### Task 7: Update `scripts/entity_extraction.py`

**Files:**
- Modify: `scripts/entity_extraction.py`

Currently writes `persons_full.json`, `places_full.json`, `orgs_full.json` and `chapters.json` to the project root.

**Step 1: Find `save_full_json` / write block** (around line 316)

```python
# Before: file tuples like ("persons_full.json", "persons_full")
# After: paths.processing / "persons_full.json"
```

Update the file path tuples/constants throughout to use `paths.processing`:

```python
# In the executor main block, after getting payload:
paths = _paths_from_payload(payload)
paths.processing.mkdir(parents=True, exist_ok=True)

# Change save calls:
ENTITY_FILES = {
    "PERSON": (paths.processing / "persons_full.json", "persons_full"),
    "PLACE":  (paths.processing / "places_full.json",  "places_full"),
    "ORG":    (paths.processing / "orgs_full.json",    "orgs_full"),
}

# For save_chapters_json call — pass explicit path:
save_chapters_json(chapters, path=str(paths.processing / "chapters.json"))
```

**Step 2: Update `save_chapters_json` signature** (line 324)

```python
def save_chapters_json(chapters: list[dict], path: str = "chapters.json") -> None:
    # signature already accepts `path`, just ensure the call passes the new path
```

**Step 3: Commit**

```bash
git add scripts/entity_extraction.py
git commit -m "feat(entity_extraction): write *_full.json and chapters.json to processing_output/"
```

---

### Task 8: Update `scripts/split_clusters.py`

**Files:**
- Modify: `scripts/split_clusters.py`

**Step 1: Find write block** (around line 83)

```python
# Before:
os.makedirs("processing_output", exist_ok=True)
with open("processing_output/splits.json", "w", encoding="utf-8") as _f:

# After:
paths = _paths_from_payload(payload)
paths.processing.mkdir(parents=True, exist_ok=True)
with open(paths.processing / "splits.json", "w", encoding="utf-8") as _f:
```

Add `_paths_from_payload` helper.

**Step 2: Commit**

```bash
git add scripts/split_clusters.py
git commit -m "feat(split_clusters): write splits.json to library processing_output"
```

---

### Task 9: Update loader scripts (load_epub_data, load_splits, load_classified_entities, load_wiki_pages)

**Files:**
- Modify: `scripts/load_epub_data.py`
- Modify: `scripts/load_splits.py`
- Modify: `scripts/load_classified_entities.py`
- Modify: `scripts/load_wiki_pages.py`

All four follow the same pattern. Each has a hardcoded `path = "processing_output/xyz.json"`.

**Step 1: Update each script**

`load_epub_data.py` (around line 15):
```python
# Before:
path = "processing_output/epub_data.json"
# After:
paths = _paths_from_payload(payload)
path = str(paths.processing / "epub_data.json")
```

`load_splits.py`:
```python
path = str(paths.processing / "splits.json")
```

`load_classified_entities.py`:
```python
path = str(paths.processing / "entities_classified.json")
```

`load_wiki_pages.py` (around line 16, constant `OUTPUT_FILE`):
```python
# Remove module-level constant. In main():
paths = _paths_from_payload(payload)
output_file = paths.processing / "wiki_pages.json"
```

**Step 2: Commit**

```bash
git add scripts/load_epub_data.py scripts/load_splits.py \
        scripts/load_classified_entities.py scripts/load_wiki_pages.py
git commit -m "feat(loaders): derive processing_output paths from book yaml"
```

---

### Task 10: Update `scripts/entity_classification.py`

**Files:**
- Modify: `scripts/entity_classification.py`

Reads `persons_full.json` etc. from root, writes `processing_output/entities_classified.json`.

**Step 1: Find `_load_entity_files()` (around line 216) and main write (line 265)**

```python
# Before in _load_entity_files():
load("persons_full.json", "persons_full"),
load("places_full.json", "places_full"),
load("orgs_full.json", "orgs_full"),

# After — pass processing_dir as param:
def _load_entity_files(processing_dir: Path) -> tuple:
    def load(name, key):
        p = processing_dir / name
        ...
    return (
        load("persons_full.json", "persons_full"),
        load("places_full.json", "places_full"),
        load("orgs_full.json", "orgs_full"),
    )
```

```python
# Before write (line 265):
os.makedirs("processing_output", exist_ok=True)
with open("processing_output/entities_classified.json", "w", ...) as _f:

# After:
paths = _paths_from_payload(payload)
paths.processing.mkdir(parents=True, exist_ok=True)
persons_full, places_full, orgs_full = _load_entity_files(paths.processing)
...
with open(paths.processing / "entities_classified.json", "w", ...) as _f:
```

**Step 2: Commit**

```bash
git add scripts/entity_classification.py
git commit -m "feat(entity_classification): use library paths for input/output files"
```

---

### Task 11: Update `scripts/relationship_extraction.py`

**Files:**
- Modify: `scripts/relationship_extraction.py`

Reads `persons_full.json` (line 840) and `chapters.json` (line 940) from root.

**Step 1: Find the live-mode entry point** (around line 826)

```python
# Before (lines ~830-841):
if not os.path.exists("persons_full.json"):
    print("persons_full.json not found...", file=sys.stderr)
    sys.exit(1)
with open("persons_full.json", encoding="utf-8") as f:
    ...

# After — accept processing_dir parameter:
def run_live(payload: dict) -> None:
    paths = _paths_from_payload(payload)
    persons_path = paths.processing / "persons_full.json"
    if not persons_path.exists():
        print(f"{persons_path} not found...", file=sys.stderr)
        sys.exit(1)
    with open(persons_path, encoding="utf-8") as f:
        ...
```

```python
# chapters.json read (lines ~937-940):
chapters_path = paths.processing / "chapters.json"
if not chapters_path.exists():
    ...
with open(chapters_path, encoding="utf-8") as f:
```

Also update the `--live` CLI flag block (line ~1070):
```python
chapters_path = paths.processing / "chapters.json"
if chapters_path.exists():
    with open(chapters_path, ...) as f:
```

**Step 2: Commit**

```bash
git add scripts/relationship_extraction.py
git commit -m "feat(relationship_extraction): read persons/chapters from library processing_output"
```

---

### Task 12: Update `scripts/wiki_preparation.py`

**Files:**
- Modify: `scripts/wiki_preparation.py`

Reads `*_full.json` from root (line 203), writes `wiki_inputs/batch_*.json` (lines 137, 153).

**Step 1: Find the registry load block** (around line 203)

```python
# Before:
persons = load_registry("persons_full.json", "persons_full")
places = load_registry("places_full.json", "places_full")
orgs = load_registry("orgs_full.json", "orgs_full")
os.makedirs("wiki_inputs", exist_ok=True)

# After:
paths = _paths_from_payload(payload)
persons = load_registry(str(paths.processing / "persons_full.json"), "persons_full")
places = load_registry(str(paths.processing / "places_full.json"), "places_full")
orgs = load_registry(str(paths.processing / "orgs_full.json"), "orgs_full")
paths.wiki_inputs.mkdir(parents=True, exist_ok=True)
```

**Step 2: Update batch file path** (around line 137)

```python
# Before:
file_path = f"wiki_inputs/{batch_id}.json"
# After:
file_path = str(paths.wiki_inputs / f"{batch_id}.json")
```

Pass `paths` into `write_batches()` or restructure to call `_paths_from_payload` at entry and pass `paths` down.

**Step 3: Commit**

```bash
git add scripts/wiki_preparation.py
git commit -m "feat(wiki_preparation): use library paths for *_full.json and wiki_inputs"
```

---

### Task 13: Update `scripts/wiki_export.py`

**Files:**
- Modify: `scripts/wiki_export.py`

Reads `processing_output/epub_data.json` (line 33), writes to `output/wiki` (line 55).

**Step 1: Find read/write blocks**

```python
# Before (line 33):
path = "processing_output/epub_data.json"

# After:
paths = _paths_from_payload(payload)
path = str(paths.processing / "epub_data.json")
```

```python
# Before (line 55):
wiki_dir = Path(export_cfg.get("wiki_dir", "output/wiki"))

# After — always derive from paths, ignore yaml wiki_dir:
wiki_dir = paths.output
```

**Step 2: Commit**

```bash
git add scripts/wiki_export.py
git commit -m "feat(wiki_export): derive output dir from library structure"
```

---

### Task 14: Update `scripts/generate_wiki_pages.py` (standalone)

**Files:**
- Modify: `scripts/generate_wiki_pages.py`

This script is standalone (no Studio context). It currently uses module-level constants for paths. Add `--book` argument.

**Step 1: Update argparse block**

```python
# Add to argument parser:
parser.add_argument(
    "--book",
    required=True,
    help="Path to book yaml config, e.g. library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml",
)
```

**Step 2: Replace module-level constants with derived paths**

```python
# Before (lines 23-24):
OUTPUT_FILE = "processing_output/wiki_pages.json"
WIKI_INPUTS_DIR = "wiki_inputs"

# After — in main(), after parsing args:
from wiki_creator.paths import book_paths_from_yaml
book_paths = book_paths_from_yaml(args.book)
OUTPUT_FILE = str(book_paths.processing / "wiki_pages.json")
WIKI_INPUTS_DIR = str(book_paths.wiki_inputs)
```

Also update the epub_data.json read (line 149):
```python
# Before:
with open("processing_output/epub_data.json", ...) as f:
# After:
with open(book_paths.processing / "epub_data.json", ...) as f:
```

**Step 3: Update `Makefile` generate-pages target**

```makefile
generate-pages:
	python scripts/generate_wiki_pages.py --book $(BOOK)

generate-pages-dry:
	python scripts/generate_wiki_pages.py --book $(BOOK) --dry-run
```

**Step 4: Commit**

```bash
git add scripts/generate_wiki_pages.py Makefile
git commit -m "feat(generate_wiki_pages): add --book arg to use library paths"
```

---

### Task 15: Update `run_wiki.py`

**Files:**
- Modify: `run_wiki.py`

The `REQUIRED_FILES` dict hardcodes paths (lines ~27-36). Update to derive from the book yaml.

**Step 1: Replace hardcoded `REQUIRED_FILES` with a function**

```python
from wiki_creator.paths import book_paths_from_yaml

def required_files(book_path: str) -> dict[str, list[str]]:
    p = book_paths_from_yaml(book_path)
    return {
        "wiki-extraction": [
            str(p.processing / "splits.json"),
            str(p.processing / "epub_data.json"),
        ],
        "wiki-resolution": [
            str(p.processing / "entities_classified.json"),
        ],
        "wiki-preparation": [str(p.wiki_inputs)],
        "pages-export": [
            str(p.processing / "wiki_pages.json"),
        ],
    }
```

Replace references to `REQUIRED_FILES` with `required_files(book_path)`.

**Step 2: Update `book_slug` function** (line 44)

```python
def book_slug(book_path: str) -> str:
    p = Path(book_path)
    # e.g. sarah_j_maas__throne-of-glass__01-throne-of-glass
    return "__".join([p.parent.parent.parent.name, p.parent.parent.name, p.stem])
```

**Step 3: Commit**

```bash
git add run_wiki.py
git commit -m "feat(run_wiki): derive REQUIRED_FILES from library paths"
```

---

### Task 16: Update test/utility scripts

**Files:**
- Modify: `scripts/test_extraction.py`
- Modify: `scripts/test_fastcoref.py`
- Modify: `scripts/verify_entity_types.py`

**Step 1: `test_extraction.py`** — add `--book` arg, write `extraction-*.jsonl` to `paths.processing`

```python
# Add argparse with --book
# Replace ("persons_full.json", ...) tuples with (str(paths.processing / "persons_full.json"), ...)
# Write extraction-*.jsonl to paths.processing / "extraction-{type}.jsonl"
```

Update `Makefile`:
```makefile
test-extraction:
	python scripts/test_extraction.py --book $(BOOK)
```

**Step 2: `test_fastcoref.py`** — add `--book` arg, derive `chapters.json` path

```python
# Replace CHAPTERS_PATH constant with:
parser.add_argument("--book", required=True)
args = parser.parse_args()
from wiki_creator.paths import book_paths_from_yaml
CHAPTERS_PATH = book_paths_from_yaml(args.book).processing / "chapters.json"
```

**Step 3: `verify_entity_types.py`** — update to read from `paths.processing` (has `input` context)

```python
# Replace "PLACE": "places_full.json" dict entries with:
paths = _paths_from_payload(payload)
TYPE_FILES = {
    "PLACE": str(paths.processing / "places_full.json"),
    "ORG":   str(paths.processing / "orgs_full.json"),
}
```

**Step 4: Commit**

```bash
git add scripts/test_extraction.py scripts/test_fastcoref.py scripts/verify_entity_types.py Makefile
git commit -m "feat(test_scripts): add --book arg and use library paths"
```

---

### Task 17: Run full test suite and verify

**Step 1: Run pytest**

```bash
pytest -v
```
Expected: all tests pass (including `tests/test_paths.py`).

**Step 2: Smoke test parse_epub**

```bash
make test-extraction BOOK=library/sarah_j_maas/throne-of-glass/books/01-throne-of-glass.yaml
ls library/sarah_j_maas/throne-of-glass/processing_output/01-throne-of-glass/
```
Expected: `persons_full.json`, `places_full.json`, `orgs_full.json`, `chapters.json`, `extraction-*.jsonl` present.

**Step 3: Final commit**

```bash
git commit --allow-empty -m "feat: complete library structure reorganization"
```
