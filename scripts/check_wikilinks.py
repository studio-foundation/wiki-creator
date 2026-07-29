#!/usr/bin/env python3
"""Wikilink integrity check (STU-725): assert every ``[[link]]`` in a rendered
wiki resolves to a page.

A standing, LLM-free gate over a rendered ``.wiki`` page set — the effect-side
guard for the canonicalization drift STU-719 shipped silently (``City_of_Emeralds``
page vs ``[[Emerald City]]`` link). Runs at either scope:

    python scripts/check_wikilinks.py --book <book.yaml>            # output/<slug>/
    python scripts/check_wikilinks.py --book <any-tome.yaml> --series  # output/_series/

Intentional red links (a mentioned-but-not-notable entity) are declared in the
book YAML ``export.red_links`` list and never reported. Exits non-zero when a
dead link is found, so it is a failing gate (``make check-wikilinks``); the pure
logic lives in :mod:`wiki_creator.wikilinks`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from wiki_creator.paths import book_paths_from_yaml
from wiki_creator.wikilinks import find_dead_links


def load_pages(wiki_dir: Path) -> list[tuple[str, str]]:
    """Every content page in ``wiki_dir`` as ``(title, body)``. The title is the
    file stem — its flat MediaWiki identity, already STU-506-disambiguated by the
    exporter. ``templates/`` holds infobox sources, not pages, and is excluded."""
    pages: list[tuple[str, str]] = []
    for wiki in sorted(wiki_dir.rglob("*.wiki")):
        rel = wiki.relative_to(wiki_dir).as_posix()
        if rel.startswith("templates/"):
            continue
        pages.append((wiki.stem, wiki.read_text(encoding="utf-8")))
    return pages


def _red_links(book_cfg: dict) -> list[str]:
    allow = ((book_cfg.get("export") or {}).get("red_links")) or []
    return [str(name) for name in allow]


def main() -> int:
    parser = argparse.ArgumentParser(description="Wikilink integrity check (STU-725)")
    parser.add_argument("--book", required=True, help="Path to a book YAML config")
    parser.add_argument(
        "--series",
        action="store_true",
        help="Check the series wiki (output/_series/) instead of the book's",
    )
    args = parser.parse_args()

    with open(args.book, encoding="utf-8") as f:
        book_cfg = yaml.safe_load(f) or {}
    paths = book_paths_from_yaml(args.book)
    wiki_dir = paths.series_output if args.series else paths.output

    if not wiki_dir.is_dir():
        print(f"[wikilink-check] no rendered wiki at {wiki_dir} — nothing to check", file=sys.stderr)
        return 0

    pages = load_pages(wiki_dir)
    dead = find_dead_links(pages, _red_links(book_cfg))

    scope = "series" if args.series else "book"
    if not dead:
        print(f"[wikilink-check] {scope}: {len(pages)} pages, 0 dead links", file=sys.stderr)
        return 0

    print(
        f"[wikilink-check] {scope}: {len(dead)} dead link(s) across {len(pages)} pages:",
        file=sys.stderr,
    )
    for link in dead:
        print(f"  {link.source}.wiki -> [[{link.target}]]", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
