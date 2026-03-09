#!/usr/bin/env python3
# scripts/wiki_export.py
"""Stage wiki-export — converts wiki-generation Markdown output to wikitext files.

Studio script executor interface:
  Input (stdin): {"additional_context": "<yaml>", "previous_outputs": {...}}
  Output (stdout): {"files_written": N, "wiki_dir": "output/wiki"}
"""
import json
import sys
from pathlib import Path

import yaml

# Ensure project root is importable when running as `python scripts/<file>.py`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wiki_creator.md2wiki import convert, make_infobox_call
from wiki_creator.export_helpers import (
    page_filename,
    category_tags,
    infobox_template_content,
    main_page_content,
)
from wiki_creator.paths import book_paths_from_epub, BookPaths


def _paths_from_payload(payload: dict) -> BookPaths:
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        raise ValueError("missing file_path in additional_context")
    return book_paths_from_epub(file_path)

_SUBDIR = {
    "PERSON": "characters",
    "PLACE": "locations",
    "ORG": "organizations",
}


def _load_epub_data(paths: BookPaths) -> dict:
    """Fallback: read epub metadata directly from disk."""
    path = paths.processing / "epub_data.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def main() -> None:
    payload = json.load(sys.stdin)
    input_cfg = yaml.safe_load(payload["additional_context"])
    prev = payload["previous_outputs"]

    paths = _paths_from_payload(payload)

    pages = (
        prev.get("copyright-check", {}).get("pages")
        or prev.get("wiki-generation", {}).get("pages")
        or []
    )
    epub = prev.get("epub-parse") or _load_epub_data(paths)
    book_title = epub.get("title", "Wiki")
    author = epub.get("author", "")

    export_cfg = input_cfg.get("export", {})
    wiki_dir = paths.output
    labels_cfg = export_cfg.get("categories", {}).get("labels", {})
    labels = {
        "persons": labels_cfg.get("persons", "Personnages"),
        "principal": labels_cfg.get("principal", "Personnages principaux"),
        "secondary": labels_cfg.get("secondary", "Personnages secondaires"),
        "locations": labels_cfg.get("locations", "Lieux"),
        "organizations": labels_cfg.get("organizations", "Organisations"),
    }

    # Create directories
    (wiki_dir / "templates").mkdir(parents=True, exist_ok=True)
    for subdir in _SUBDIR.values():
        (wiki_dir / subdir).mkdir(exist_ok=True)

    files_written = 0

    # Write infobox templates
    for entity_type, template_name in [
        ("PERSON", "Infobox_character"),
        ("PLACE", "Infobox_location"),
        ("ORG", "Infobox_organization"),
    ]:
        path = wiki_dir / "templates" / f"{template_name}.wiki"
        path.write_text(infobox_template_content(entity_type), encoding="utf-8")
        files_written += 1

    # Write entity pages
    for page in pages:
        title = page["title"]
        entity_type = page.get("entity_type", "PERSON")
        importance = page.get("importance", "secondary")
        infobox_fields = page.get("infobox_fields", {})
        content_md = page.get("content", "")

        infobox = make_infobox_call(entity_type, infobox_fields)
        body = convert(content_md)
        cats = category_tags(entity_type, importance, labels)

        page_content = infobox + "\n\n" + body
        if cats:
            page_content += "\n\n" + "\n".join(cats)

        subdir = _SUBDIR.get(entity_type, "characters")
        filename = page_filename(title) + ".wiki"
        path = wiki_dir / subdir / filename
        path.write_text(page_content, encoding="utf-8")
        files_written += 1

    # Write categories.wiki
    cats_content = _build_categories_wiki(labels)
    (wiki_dir / "categories.wiki").write_text(cats_content, encoding="utf-8")
    files_written += 1

    # Write Main_Page.wiki
    main_content = main_page_content(book_title, author, pages, labels)
    (wiki_dir / "Main_Page.wiki").write_text(main_content, encoding="utf-8")
    files_written += 1

    json.dump({"files_written": files_written, "wiki_dir": str(wiki_dir)}, sys.stdout)


def _build_categories_wiki(labels: dict) -> str:
    """Generate categories.wiki — a reference page listing the wiki's category hierarchy."""
    lines = [
        "= Catégories =",
        "This page documents the category hierarchy used in this wiki.",
        "",
        f"== {labels['persons']} ==",
        f"* [[Category:{labels['persons']}]]",
        f"** [[Category:{labels['principal']}]]",
        f"** [[Category:{labels['secondary']}]]",
        "",
        f"== {labels['locations']} ==",
        f"* [[Category:{labels['locations']}]]",
        "",
        f"== {labels['organizations']} ==",
        f"* [[Category:{labels['organizations']}]]",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
