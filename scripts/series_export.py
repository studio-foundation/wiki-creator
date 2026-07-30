#!/usr/bin/env python3
"""Stage series-export (STU-709): the series wiki as wikitext under output/_series/.

Renders what `series-assemble` wrote — one merged page per cross-tome entity
(STU-668/706) plus the hub (STU-707/708) — into the series-scoped published dir
(STU-705). Reads ``series_assembly.json`` from disk, like every cross-pipeline
consumer (STU-455).

A stateless full rebuild: the output dir is rewritten from the assembly, so an
entity that no longer assembles leaves no stale page behind.

Usage:
    python scripts/series_export.py --series library/<author>/<series>
    python scripts/series_export.py --book library/<author>/<series>/books/01-x.yaml
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import yaml

from scripts.series_assemble import ASSEMBLY_FILENAME
from wiki_creator import entity_taxonomy, studio_io
from wiki_creator.editorial_stance import editorial_stance
from wiki_creator.export_helpers import category_labels
from wiki_creator.page_templates import output_language
from wiki_creator.paths import book_paths_from_yaml, series_output_dir
from wiki_creator.series import SeriesCharacter, discover_series_books
from wiki_creator.series_hub import SeriesHub, render_series_hub
from wiki_creator.series_pages import render_series_character_page


def load_assembly(series_dir: Path | str) -> tuple[SeriesHub, list[SeriesCharacter], str | None, dict]:
    path = Path(series_dir) / ASSEMBLY_FILENAME
    if not path.exists():
        raise SystemExit(f"[series-export] no assembly at {path} — run series-assemble first")
    data = json.loads(path.read_text(encoding="utf-8"))
    hub = studio_io.from_dict(SeriesHub, data["hub"])
    characters = studio_io.from_dict(list[SeriesCharacter], data["characters"])
    arc = data.get("arc")
    return hub, characters, arc if isinstance(arc, str) else None, data


def _write_infobox_templates(wiki_dir: Path, lang: str) -> int:
    written = 0
    for entity_type in entity_taxonomy.declared_types():
        source = entity_taxonomy.infobox_source(entity_type, lang)
        template_name = entity_taxonomy.infobox_template_name(entity_type)
        if not source or not template_name:
            continue
        path = wiki_dir / "templates" / f"{template_name.replace(' ', '_')}.wiki"
        path.write_text(source, encoding="utf-8")
        written += 1
    return written


def export_series(series_dir: Path | str) -> dict:
    """Render the whole series wiki. Language, register and category labels come
    from the first tome's config — they are properties of the series' published
    wiki, and every tome of one series declares the same (as the arc pass does)."""
    series_dir = Path(series_dir)
    hub, characters, arc, assembly = load_assembly(series_dir)
    targets = assembly.get("link_targets") or {}
    determiners = assembly.get("determiners") or []

    first_cfg = yaml.safe_load(discover_series_books(series_dir)[0].read_text(encoding="utf-8")) or {}
    lang = output_language(first_cfg)
    labels_cfg = first_cfg.get("export", {}).get("categories", {}).get("labels", {})
    labels = category_labels(labels_cfg, lang)
    stance = editorial_stance(first_cfg)

    wiki_dir = series_output_dir(series_dir)
    # Not ignore_errors: a swallowed wipe leaves a stale-case page behind on a
    # case-insensitive filesystem — the rewrite of `Billina.wiki` keeps the old
    # `BILLINA.wiki` name and every `[[Billina]]` link dies (STU-746).
    if wiki_dir.exists():
        shutil.rmtree(wiki_dir)
    (wiki_dir / "templates").mkdir(parents=True)
    for subdir in entity_taxonomy.subdirs():
        (wiki_dir / subdir).mkdir()

    files_written = _write_infobox_templates(wiki_dir, lang)

    for character in characters:
        rel_path, content = render_series_character_page(
            character, labels, lang=lang,
            expose_importance_tier=stance.expose_importance_tier,
            targets=targets, determiners=determiners,
        )
        (wiki_dir / rel_path).write_text(content, encoding="utf-8")
        files_written += 1

    rel_path, content = render_series_hub(hub, labels, lang=lang, arc=arc)
    (wiki_dir / rel_path).write_text(content, encoding="utf-8")
    files_written += 1

    return {"files_written": files_written, "wiki_dir": str(wiki_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the series wiki to wikitext (STU-709)")
    parser.add_argument("--series", help="Series directory (standalone mode)")
    parser.add_argument("--book", help="Any tome's YAML — its series is exported (standalone mode)")
    args, _ = parser.parse_known_args()

    standalone = bool(args.series or args.book)
    if args.series:
        series_dir = Path(args.series)
    elif args.book:
        series_dir = book_paths_from_yaml(args.book).series_dir
    else:
        series_dir = studio_io.paths_from_payload(studio_io.read_payload()).series_dir

    result = export_series(series_dir)
    print(
        f"[series-export] {result['files_written']} files -> {result['wiki_dir']}",
        file=sys.stderr,
    )
    if not standalone:
        studio_io.write_output(result)


if __name__ == "__main__":
    main()
