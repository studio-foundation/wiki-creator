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

from wiki_creator.md2wiki import convert, make_infobox_call
from wiki_creator.export_helpers import (
    page_filename,
    category_tags,
    infobox_template_content,
    main_page_content,
)

_SUBDIR = {
    "PERSON": "characters",
    "PLACE": "locations",
    "ORG": "organizations",
}


def main() -> None:
    payload = json.load(sys.stdin)
    input_cfg = yaml.safe_load(payload["additional_context"])
    prev = payload["previous_outputs"]

    pages = prev["wiki-generation"]["pages"]
    epub = prev["epub-parse"]
    book_title = epub.get("title", "Wiki")
    author = epub.get("author", "")

    export_cfg = input_cfg.get("export", {})
    wiki_dir = Path(export_cfg.get("wiki_dir", "output/wiki"))
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
    main_content = main_page_content(book_title, author, pages)
    (wiki_dir / "Main_Page.wiki").write_text(main_content, encoding="utf-8")
    files_written += 1

    json.dump({"files_written": files_written, "wiki_dir": str(wiki_dir)}, sys.stdout)


def _build_categories_wiki(labels: dict) -> str:
    lines = [
        f"[[Category:{labels['principal']}|{labels['persons']}]]",
        f"[[Category:{labels['secondary']}|{labels['persons']}]]",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
