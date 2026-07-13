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
from wiki_creator.paths import BookPaths
from wiki_creator import studio_io

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


def _copyright_gate(prev: dict) -> dict | None:
    """Return a blocking error payload if the copyright-check stage failed.

    Enforces INV-WC-01: a `status: "fail"` from copyright-check must stop the
    export — pages containing verbatim passages never reach the wikitext output.
    Returns None when the check passed or was not run in this pipeline.
    """
    result = prev.get("copyright-check") or {}
    if result.get("status") != "fail":
        return None
    violations = result.get("violations", [])
    titles = sorted({v.get("page_title", "?") for v in violations})
    return {
        "error": "copyright_check_failed",
        "feedback": result.get("feedback", ""),
        "violating_pages": titles,
        "violations": violations,
    }


def _filter_exportable_pages(pages: list[dict]) -> list[dict]:
    """Exclude pages that failed generation — they have no usable content."""
    exportable = [p for p in pages if not p.get("_failed")]
    skipped = len(pages) - len(exportable)
    if skipped:
        print(f"[wiki-export] Skipping {skipped} _failed page(s)", file=sys.stderr)
    return exportable


def render_page(page: dict, labels: dict) -> tuple[str, str]:
    """(path relative to the wiki dir, wikitext content) for one page.

    Entity pages keep the infobox + body + categories layout in their type
    subdir. SYNOPSIS pages (SP4, STU-482) render at the wiki root, body only —
    no infobox, no categories.
    """
    title = page["title"]
    entity_type = page.get("entity_type", "PERSON")
    body = convert(page.get("content", ""))
    filename = page_filename(title) + ".wiki"

    if entity_type == "SYNOPSIS":
        return filename, body

    infobox = make_infobox_call(entity_type, page.get("infobox_fields", {}))
    cats = category_tags(
        entity_type, page.get("importance", "secondaire"), labels, page.get("books")
    )
    page_content = infobox + "\n\n" + body
    if cats:
        page_content += "\n\n" + "\n".join(cats)
    subdir = _SUBDIR.get(entity_type, "characters")
    return f"{subdir}/{filename}", page_content


def main() -> None:
    payload = studio_io.read_payload()
    input_cfg = yaml.safe_load(payload["additional_context"])
    prev = payload["previous_outputs"]

    paths = studio_io.paths_from_payload(payload)

    gate_error = _copyright_gate(prev)
    if gate_error is not None:
        print(
            f"[wiki-export] BLOCKED — copyright-check failed for: "
            f"{', '.join(gate_error['violating_pages'])}",
            file=sys.stderr,
        )
        json.dump(gate_error, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    pages = (
        prev.get("copyright-check", {}).get("pages")
        or prev.get("wiki-generation", {}).get("pages")
        or []
    )
    pages = _filter_exportable_pages(pages)
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
        # Per-tome categories (STU-486): "{n}" is filled with the tome number.
        "persons_by_tome": labels_cfg.get("persons_by_tome", "Personnages du Tome {n}"),
        "locations_by_tome": labels_cfg.get("locations_by_tome", "Lieux du Tome {n}"),
        "organizations_by_tome": labels_cfg.get(
            "organizations_by_tome", "Organisations du Tome {n}"
        ),
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

    # Write entity pages (and the synopsis page at the wiki root, if present)
    for page in pages:
        rel_path, page_content = render_page(page, labels)
        path = wiki_dir / rel_path
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
