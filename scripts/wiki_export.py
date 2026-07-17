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

from wiki_creator import entity_taxonomy
from wiki_creator.editorial_stance import EditorialStance, editorial_stance
from wiki_creator.md2wiki import convert, make_infobox_call
from wiki_creator.export_helpers import (
    page_filename,
    category_tags,
    index_limits,
    main_page_content,
)
from wiki_creator.page_templates import output_language
from wiki_creator.paths import BookPaths
from wiki_creator import studio_io
from wiki_creator.spoiler_blocks import (
    wrap_collapsible,
    wrap_relation_collapsibles,
    inject_relationship_index,
    spoiler_collapse_after,
)

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


def render_page(
    page: dict,
    labels: dict,
    collapse_after: int | None = None,
    stance: EditorialStance | None = None,
    lang: str = "fr",
) -> tuple[str, str]:
    """(path relative to the wiki dir, wikitext content) for one page.

    Entity pages keep the infobox + body + categories layout in their type
    subdir. SYNOPSIS pages (SP4, STU-482) and COLLATION pages (STU-511) render
    at the wiki root, body only — no infobox, no categories.

    STU-492: the Relations index is injected under the Relations section, and —
    when ``collapse_after`` is set — sections first revealed after that chapter
    are wrapped in native mw-collapsible blocks. ``collapse_after=None`` keeps the
    output byte-identical to pre-STU-492.
    """
    stance = stance or EditorialStance()
    title = page["title"]
    entity_type = page.get("entity_type", "PERSON")
    body = convert(page.get("content", ""))
    relation_units = page.get("relation_units")
    if relation_units:
        if collapse_after is not None:
            body = wrap_collapsible(body, page.get("content_units") or [], collapse_after, lang)
            body = wrap_relation_collapsibles(body, relation_units, collapse_after, lang)
    else:
        body = inject_relationship_index(body, page.get("relationship_index") or [], lang)
        if collapse_after is not None:
            body = wrap_collapsible(body, page.get("content_units") or [], collapse_after, lang)
    filename = page_filename(title) + ".wiki"

    if entity_type in ("SYNOPSIS", "COLLATION"):
        return filename, body

    infobox = make_infobox_call(entity_type, page.get("infobox_fields", {}))
    cats = category_tags(
        entity_type, page.get("importance", "secondary"), labels, page.get("books"),
        expose_importance_tier=stance.expose_importance_tier,
    )
    page_content = infobox + "\n\n" + body
    if cats:
        page_content += "\n\n" + "\n".join(cats)
    subdir = entity_taxonomy.subdir(entity_type)
    return f"{subdir}/{filename}", page_content


def _load_book_config(payload: dict) -> dict:
    """Read the book YAML (generation.spoiler / generation.editorial_stance live
    there) from additional_context."""
    ctx = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    file_path = ctx.get("file_path")
    if not file_path:
        return {}
    yaml_path = Path(file_path).with_suffix(".yaml")
    if not yaml_path.exists():
        return {}
    try:
        with open(yaml_path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def main() -> None:
    payload = studio_io.read_payload()
    input_cfg = yaml.safe_load(payload["additional_context"])
    prev = payload["previous_outputs"]

    paths = studio_io.paths_from_payload(payload)
    book_cfg = _load_book_config(payload)
    collapse_after = spoiler_collapse_after(book_cfg)
    stance = editorial_stance(book_cfg)
    lang = output_language(book_cfg)

    gate_error = _copyright_gate(prev)
    if gate_error is not None:
        print(
            f"[wiki-export] BLOCKED — copyright-check failed for: "
            f"{', '.join(gate_error['violating_pages'])}",
            file=sys.stderr,
        )
        json.dump(gate_error, sys.stdout, ensure_ascii=False)
        sys.exit(1)

    pages = _filter_exportable_pages(prev.get("copyright-check", {}).get("pages") or [])
    epub = _load_epub_data(paths)
    book_title = epub.get("title", "Wiki")
    author = epub.get("author", "")

    export_cfg = input_cfg.get("export", {})
    wiki_dir = paths.output
    labels_cfg = export_cfg.get("categories", {}).get("labels", {})
    labels = {
        "principal": labels_cfg.get("principal", "Personnages principaux"),
        "secondary": labels_cfg.get("secondary", "Personnages secondaires"),
        # Per-tome categories (STU-486): "{n}" is filled with the tome number.
        "persons_by_tome": labels_cfg.get("persons_by_tome", "Personnages du Tome {n}"),
        "locations_by_tome": labels_cfg.get("locations_by_tome", "Lieux du Tome {n}"),
        "organizations_by_tome": labels_cfg.get(
            "organizations_by_tome", "Organisations du Tome {n}"
        ),
    }
    # Per-type category labels come from base.yaml defaults (STU-505), overridable
    # by the book YAML's export.categories.labels.
    for etype in entity_taxonomy.declared_types():
        cat_key = entity_taxonomy.category_key(etype)
        if cat_key and cat_key not in labels:
            labels[cat_key] = labels_cfg.get(cat_key) or entity_taxonomy.category_default(etype)

    # Create directories
    (wiki_dir / "templates").mkdir(parents=True, exist_ok=True)
    for subdir in entity_taxonomy.subdirs():
        (wiki_dir / subdir).mkdir(exist_ok=True)

    files_written = 0

    # Write infobox templates (one per declared type with an infobox source)
    for entity_type in entity_taxonomy.declared_types():
        source = entity_taxonomy.infobox_source(entity_type)
        template_name = entity_taxonomy.infobox_template_name(entity_type)
        if not source or not template_name:
            continue
        path = wiki_dir / "templates" / f"{template_name.replace(' ', '_')}.wiki"
        path.write_text(source, encoding="utf-8")
        files_written += 1

    # Write entity pages (and the synopsis page at the wiki root, if present)
    for page in pages:
        rel_path, page_content = render_page(page, labels, collapse_after, stance, lang)
        path = wiki_dir / rel_path
        path.write_text(page_content, encoding="utf-8")
        files_written += 1

    # Write categories.wiki
    cats_content = _build_categories_wiki(labels)
    (wiki_dir / "categories.wiki").write_text(cats_content, encoding="utf-8")
    files_written += 1

    # Write Main_Page.wiki
    principals_shown, places_shown = index_limits(export_cfg)
    main_content = main_page_content(
        book_title, author, pages, labels, principals_shown, places_shown,
        expose_pipeline_metadata=stance.expose_pipeline_metadata,
        lang=lang,
    )
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
        "",
        f"== {labels['events']} ==",
        f"* [[Category:{labels['events']}]]",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
