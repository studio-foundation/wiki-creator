"""Binary checks run against the real `wiki-page` stage output by the contract's
external validators. Pure logic — no I/O."""
from __future__ import annotations

from collections import defaultdict

from wiki_creator.export_helpers import page_filename


def _title(page: dict) -> str:
    return str(page.get("title") or "<untitled>")


def undeclared_entity_types(pages: list[dict], declared: set[str]) -> list[str]:
    """One error per page whose `entity_type` is absent from `declared`."""
    return [
        f"page '{_title(p)}': entity_type {p.get('entity_type')!r} "
        f"is not declared in base.yaml#entity_types "
        f"(declared: {', '.join(sorted(declared))})"
        for p in pages
        if p.get("entity_type") not in declared
    ]


def duplicate_page_titles(pages: list[dict]) -> list[str]:
    """One error per rendered `page_filename` claimed by 2+ pages. Per-type
    subdirectories keep the files apart, but the wiki title namespace is flat,
    so two such pages are one ambiguous `[[link]]` target."""
    by_filename: dict[str, list[str]] = defaultdict(list)
    for page in pages:
        by_filename[page_filename(_title(page))].append(_title(page))
    return [
        f"page_filename '{filename}' is claimed by {len(titles)} pages: "
        f"{', '.join(sorted(titles))}"
        for filename, titles in by_filename.items()
        if len(titles) > 1
    ]
