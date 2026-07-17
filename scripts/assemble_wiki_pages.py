#!/usr/bin/env python3
"""
Stage: wiki-generation (script executor, no LLM)

Assembles the export's page set from the four artifacts that hold pages —
wiki_pages.json (scripts/generate_wiki_pages.py), book_synopsis.json,
event_pages.json, collation_pages.json — dropping the ones that failed
generation, and disambiguating titles that would collide (STU-506).

Input (files on disk + the book config on stdin)
Output (stdout): {"pages": [...]}
"""

import json
import sys
from pathlib import Path

import yaml

from wiki_creator import studio_io
from wiki_creator.naming import disambiguate_page_titles, naming_policy
from wiki_creator.types import WikiPage

# entity_type → export label key, for the disambiguator's {type_label}.
_TYPE_LABEL_KEYS = {
    "PERSON": "persons",
    "PLACE": "locations",
    "ORG": "organizations",
    "EVENT": "events",
}


def _load_synopsis_page(processing_dir) -> dict | None:
    """Book synopsis page from book_synopsis.json (SP4, STU-482), or None when
    the artifact is absent, unreadable, or the generation failed."""
    path = Path(processing_dir) / "book_synopsis.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"[assemble-wiki-pages] Could not read {path} — skipping synopsis", file=sys.stderr)
        return None
    page = data.get("page") if isinstance(data, dict) else None
    if not isinstance(page, dict):
        return None
    if page.get("_failed"):
        print("[assemble-wiki-pages] Skipping _failed synopsis page", file=sys.stderr)
        return None
    return page


def _read_pages(path: Path) -> list[WikiPage]:
    """Load wiki_pages.json's `pages` array, validated against WikiPage."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return studio_io.from_dict(list[WikiPage], raw.get("pages", []))


def _load_extra_pages(processing_dir, filename: str, label: str) -> list[dict]:
    """Wiki pages from a sibling artifact's `pages` array, minus any that failed
    generation. Empty list when the artifact is absent or unreadable.

    Serves event_pages.json (SP3, STU-481) and collation_pages.json (STU-511).
    """
    path = Path(processing_dir) / filename
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(f"[assemble-wiki-pages] Could not read {path} — skipping {label}", file=sys.stderr)
        return []
    pages = data.get("pages") if isinstance(data, dict) else None
    if not isinstance(pages, list):
        return []
    return [p for p in pages if isinstance(p, dict) and not p.get("_failed")]


def _filter_failed_pages(pages: list[WikiPage]) -> list[WikiPage]:
    """Exclude pages that failed generation before they enter the export pipeline."""
    exportable = [p for p in pages if not p._failed]
    skipped = len(pages) - len(exportable)
    if skipped:
        failed_titles = [p.title for p in pages if p._failed]
        print(
            f"[assemble-wiki-pages] Skipping {skipped} _failed page(s): {', '.join(failed_titles)}",
            file=sys.stderr,
        )
    return exportable


def main() -> None:
    payload = studio_io.read_payload()
    paths = studio_io.paths_from_payload(payload)
    output_file = paths.processing / "wiki_pages.json"

    if not output_file.exists():
        print(
            f"[ERROR] {output_file} not found.\n"
            "Run first: python scripts/generate_wiki_pages.py",
            file=sys.stderr,
        )
        sys.exit(1)

    pages = _filter_failed_pages(_read_pages(output_file))
    # dict-only boundary: the synopsis page comes from a separate artifact
    # (book_synopsis.json, not wired to studio_io in this task) as a plain
    # dict, and the stdout payload mixes it in with the validated pages.
    output_pages = [studio_io.to_dict(p) for p in pages]
    synopsis = _load_synopsis_page(paths.processing)
    if synopsis is not None:
        output_pages.append(synopsis)
        print(
            f"[assemble-wiki-pages] Added synopsis page '{synopsis.get('title', '')}'",
            file=sys.stderr,
        )
    event_pages = _load_extra_pages(paths.processing, "event_pages.json", "event pages")
    if event_pages:
        output_pages.extend(event_pages)
        print(f"[assemble-wiki-pages] Added {len(event_pages)} event page(s)", file=sys.stderr)
    collation_pages = _load_extra_pages(paths.processing, "collation_pages.json", "collation pages")
    if collation_pages:
        output_pages.extend(collation_pages)
        print(f"[assemble-wiki-pages] Added {len(collation_pages)} collective page(s)", file=sys.stderr)
    print(f"[assemble-wiki-pages] Loaded {len(output_pages)} pages from {output_file}", file=sys.stderr)

    # STU-506: keep the flat MediaWiki title namespace collision-free. Two
    # different-type homonyms (a PERSON and a PLACE both named "X") now reach
    # export as distinct pages; disambiguate their titles so page_filename stays
    # unique (checked by the unique-page-title validator).
    cfg = yaml.safe_load(payload.get("additional_context", "") or "") or {}
    labels_cfg = (cfg.get("export", {}).get("categories", {}) or {}).get("labels", {}) or {}
    type_labels = {
        etype: labels_cfg[key]
        for etype, key in _TYPE_LABEL_KEYS.items()
        if labels_cfg.get(key)
    }
    for old, new in disambiguate_page_titles(output_pages, naming_policy(cfg), type_labels):
        print(f"[assemble-wiki-pages] Disambiguated title '{old}' → '{new}'", file=sys.stderr)

    json.dump({"pages": output_pages}, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
