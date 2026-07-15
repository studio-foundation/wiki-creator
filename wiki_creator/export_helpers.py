# wiki_creator/export_helpers.py
"""Helper functions for wiki export — pure logic, no I/O."""
from __future__ import annotations

from wiki_creator.tome_labels import tome_number


def page_filename(canonical_name: str) -> str:
    """Convert canonical name to wiki filename (spaces → underscores, slashes removed)."""
    name = canonical_name.replace(" ", "_")
    name = name.replace("/", "_")
    return name


# Per-tome category label key (in the `labels` dict) for each entity type that
# gets one (STU-486). EVENT is absent — event pages carry a single flat
# category, not per-tome provenance (cf. md2wiki._TEMPLATE_NAMES).
_TOME_LABEL_KEYS = {
    "PERSON": "persons_by_tome",
    "PLACE": "locations_by_tome",
    "ORG": "organizations_by_tome",
}


def category_tags(
    entity_type: str, importance: str, labels: dict, books: list[str] | None = None
) -> list[str]:
    """Return list of [[Category:X]] tags for a page, including one per-tome
    provenance category (STU-486) per entry in ``books`` (EntityRecord.books).
    ``books`` empty/omitted → no per-tome categories (registry absent or
    pre-multi-tome artifact)."""
    tags = []
    if entity_type == "PERSON":
        tags.append(f"[[Category:{labels['persons']}]]")
        if importance == "principal":
            tags.append(f"[[Category:{labels['principal']}]]")
        elif importance == "secondary":
            tags.append(f"[[Category:{labels['secondary']}]]")
    elif entity_type == "PLACE":
        tags.append(f"[[Category:{labels['locations']}]]")
    elif entity_type == "ORG":
        tags.append(f"[[Category:{labels['organizations']}]]")
    elif entity_type == "EVENT":
        tags.append(f"[[Category:{labels.get('events', 'Événements')}]]")

    tome_key = _TOME_LABEL_KEYS.get(entity_type)
    if tome_key:
        template = labels.get(tome_key, "")
        for book_id in books or []:
            if book_id and template:
                tags.append(f"[[Category:{template.format(n=tome_number(book_id))}]]")
    return tags


_INFOBOX_TEMPLATES = {
    "PERSON": """\
<includeonly>
{| class="infobox"
|-
! colspan="2" | {{{name}}}
|-
| '''Aussi connu comme''' || {{{aliases|}}}
|-
| '''Titre(s)''' || {{{titles|}}}
|-
| '''Statut''' || {{{status|}}}
|-
| '''Espèce/Race''' || {{{species|}}}
|-
| '''Occupation''' || {{{occupation|}}}
|-
| '''Résidence''' || {{{residence|}}}
|-
| '''Affiliation''' || {{{affiliation|}}}
|-
| '''Première apparition''' || {{{first_seen|}}}
|}
</includeonly>""",
    "PLACE": """\
<includeonly>
{| class="infobox"
|-
! colspan="2" | {{{name}}}
|-
| '''Type''' || {{{type|}}}
|-
| '''Localisation''' || {{{location|}}}
|-
| '''Première mention''' || {{{first_seen|}}}
|-
| '''Résidents notables''' || {{{residents|}}}
|}
</includeonly>""",
    "ORG": """\
<includeonly>
{| class="infobox"
|-
! colspan="2" | {{{name}}}
|-
| '''Type''' || {{{type|}}}
|-
| '''Leader(s)''' || {{{leaders|}}}
|-
| '''Membres notables''' || {{{members|}}}
|-
| '''Siège''' || {{{headquarters|}}}
|-
| '''Première mention''' || {{{first_seen|}}}
|}
</includeonly>""",
    "EVENT": """\
<includeonly>
{| class="infobox"
|-
! colspan="2" | {{{name}}}
|-
| '''Participants''' || {{{participants|}}}
|-
| '''Lieu''' || {{{lieu|}}}
|-
| '''Chapitre''' || {{{chapitre|}}}
|-
| '''Issue''' || {{{issue|}}}
|}
</includeonly>""",
}


def infobox_template_content(entity_type: str) -> str:
    """Return the MediaWiki template source for the given entity type."""
    if entity_type not in _INFOBOX_TEMPLATES:
        raise ValueError(f"No infobox template for entity type: {entity_type!r}")
    return _INFOBOX_TEMPLATES[entity_type]


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
) -> str:
    """Generate Main_Page.wiki content from pipeline data."""
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
            "== Synopsis ==",
            f"* [[{synopsis['title']}|Synopsis du livre]]",
            "",
        ]
    lines += [
        "== Personnages principaux ==",
    ]
    for p in principals:
        lines.append(f"* [[{p['title']}]]")
    lines += [
        "",
        "== Lieux importants ==",
    ]
    for p in major_places:
        lines.append(f"* [[{p['title']}]]")
    if events:
        lines += ["", "== Événements ==", ]
        for p in events:
            lines.append(f"* [[{p['title']}]]")
    lines += [
        "",
        "== Navigation ==",
        f"* [[:Category:{persons_label}|Tous les personnages]]",
        f"* [[:Category:{locations_label}|Tous les lieux]]",
        f"* [[:Category:{orgs_label}|Toutes les organisations]]",
    ]
    # Collective pages (STU-511) carry no category — Navigation is their only entry point.
    lines += [f"* [[{p['title']}]]" for p in collations]
    lines += [
        "",
        "== Statistiques ==",
        f"* {len(pages)} pages wiki",
        f"* {len(persons)} personnages",
        f"* {len(places)} lieux",
        f"* {len(orgs)} organisations",
    ]
    return "\n".join(lines)
