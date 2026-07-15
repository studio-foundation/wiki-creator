# wiki_creator/export_helpers.py
"""Helper functions for wiki export — pure logic, no I/O."""
from __future__ import annotations

from wiki_creator import entity_taxonomy
from wiki_creator.page_templates import chrome_label, slot_label
from wiki_creator.tome_labels import tome_number


def page_filename(canonical_name: str) -> str:
    """Convert canonical name to wiki filename (spaces → underscores, slashes removed)."""
    name = canonical_name.replace(" ", "_")
    name = name.replace("/", "_")
    return name


def category_tags(
    entity_type: str,
    importance: str,
    labels: dict,
    books: list[str] | None = None,
    expose_importance_tier: bool = True,
) -> list[str]:
    """Return list of [[Category:X]] tags for a page, including one per-tome
    provenance category (STU-486) per entry in ``books`` (EntityRecord.books).
    ``books`` empty/omitted → no per-tome categories (registry absent or
    pre-multi-tome artifact).

    Category key, default label, per-tome key and whether the type carries
    importance-tier categories all come from base.yaml#entity_types.export
    (STU-505).

    ``expose_importance_tier`` (STU-507): the tier is a pipeline ranking, not a
    fact of the fiction — False drops the principal/secondary categories."""
    tags = []
    cat_key = entity_taxonomy.category_key(entity_type)
    if cat_key:
        label = labels.get(cat_key) or entity_taxonomy.category_default(entity_type)
        if label:
            tags.append(f"[[Category:{label}]]")
        if (
            entity_taxonomy.exposes_importance_categories(entity_type)
            and expose_importance_tier
            and importance in ("principal", "secondary")
        ):
            tags.append(f"[[Category:{labels[importance]}]]")

    tome_key = entity_taxonomy.tome_label_key(entity_type)
    if tome_key:
        template = labels.get(tome_key, "")
        for book_id in books or []:
            if book_id and template:
                tags.append(f"[[Category:{template.format(n=tome_number(book_id))}]]")
    return tags


def infobox_template_content(entity_type: str) -> str:
    """Return the MediaWiki template source for the given entity type
    (base.yaml#entity_types.export.infobox_source, STU-505)."""
    source = entity_taxonomy.infobox_source(entity_type)
    if not source:
        raise ValueError(f"No infobox template for entity type: {entity_type!r}")
    return source


# An editorial choice, so it belongs in book YAML `export.index`, not in a
# slice (STU-511).
DEFAULT_PRINCIPALS_SHOWN = 8
DEFAULT_PLACES_SHOWN = 5


def index_limits(export_cfg: dict | None) -> tuple[int, int]:
    """(principals_shown, places_shown) from `export.index`. 0 empties a
    section; a negative or unparseable value falls back to the default."""
    cfg = (export_cfg or {}).get("index") or {}

    def _limit(key: str, default: int) -> int:
        try:
            value = int(cfg.get(key, default))
        except (TypeError, ValueError):
            return default
        return value if value >= 0 else default

    return (
        _limit("principals_shown", DEFAULT_PRINCIPALS_SHOWN),
        _limit("places_shown", DEFAULT_PLACES_SHOWN),
    )


def main_page_content(
    book_title: str,
    author: str,
    pages: list[dict],
    labels: dict | None = None,
    principals_shown: int = DEFAULT_PRINCIPALS_SHOWN,
    places_shown: int = DEFAULT_PLACES_SHOWN,
    expose_pipeline_metadata: bool = True,
    lang: str = "fr",
) -> str:
    """Generate Main_Page.wiki content from pipeline data.

    ``expose_pipeline_metadata`` (STU-507): the page counts describe the run, not
    the fiction — False drops the Statistiques block.

    Headings, navigation link text and statistics labels follow ``lang`` (the
    wiki's ``output_language``, STU-514) — only the ``[[:Category:X]]`` targets
    stay on the separate ``export.categories`` axis carried by ``labels``."""
    persons = [p for p in pages if p["entity_type"] == "PERSON"]
    places = [p for p in pages if p["entity_type"] == "PLACE"]
    orgs = [p for p in pages if p["entity_type"] == "ORG"]
    events = [p for p in pages if p["entity_type"] == "EVENT"]
    synopsis = next((p for p in pages if p.get("entity_type") == "SYNOPSIS"), None)
    collations = [p for p in pages if p.get("entity_type") == "COLLATION"]

    principals = [p for p in persons if p["importance"] == "principal"][:principals_shown]
    major_places = [p for p in places if p["importance"] == "principal"][:places_shown]

    persons_label = labels.get("persons", "Personnages") if labels else "Personnages"
    locations_label = labels.get("locations", "Lieux") if labels else "Lieux"
    orgs_label = labels.get("organizations", "Organisations") if labels else "Organisations"

    lines = [
        f"= {book_title} =",
        f"''{author}''",
        "",
    ]
    if synopsis is not None:
        lines += [
            f"== {chrome_label('synopsis', lang)} ==",
            f"* [[{synopsis['title']}|{chrome_label('synopsis_link', lang)}]]",
            "",
        ]
    lines += [
        f"== {chrome_label('main_characters', lang)} ==",
    ]
    for p in principals:
        lines.append(f"* [[{p['title']}]]")
    lines += [
        "",
        f"== {chrome_label('main_locations', lang)} ==",
    ]
    for p in major_places:
        lines.append(f"* [[{p['title']}]]")
    if events:
        lines += ["", f"== {slot_label('events', lang)} ==", ]
        for p in events:
            lines.append(f"* [[{p['title']}]]")
    lines += [
        "",
        f"== {chrome_label('navigation', lang)} ==",
        f"* [[:Category:{persons_label}|{chrome_label('all_characters', lang)}]]",
        f"* [[:Category:{locations_label}|{chrome_label('all_locations', lang)}]]",
        f"* [[:Category:{orgs_label}|{chrome_label('all_organizations', lang)}]]",
    ]
    # Collective pages (STU-511) carry no category — Navigation is their only entry point.
    lines += [f"* [[{p['title']}]]" for p in collations]
    if expose_pipeline_metadata:
        lines += [
            "",
            f"== {chrome_label('statistics', lang)} ==",
            f"* {len(pages)} {chrome_label('stat_pages', lang)}",
            f"* {len(persons)} {chrome_label('stat_characters', lang)}",
            f"* {len(places)} {chrome_label('stat_locations', lang)}",
            f"* {len(orgs)} {chrome_label('stat_organizations', lang)}",
        ]
    return "\n".join(lines)
