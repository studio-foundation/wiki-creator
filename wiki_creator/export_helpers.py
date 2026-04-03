# wiki_creator/export_helpers.py
"""Helper functions for wiki export — pure logic, no I/O."""
from __future__ import annotations


def page_filename(canonical_name: str) -> str:
    """Convert canonical name to wiki filename (spaces → underscores, slashes removed)."""
    name = canonical_name.replace(" ", "_")
    name = name.replace("/", "_")
    return name


def category_tags(entity_type: str, importance: str, labels: dict) -> list[str]:
    """Return list of [[Category:X]] tags for a page."""
    tags = []
    if entity_type == "PERSON":
        tags.append(f"[[Category:{labels['persons']}]]")
        if importance == "principal":
            tags.append(f"[[Category:{labels['principal']}]]")
        elif importance in ("secondary", "secondaire"):
            tags.append(f"[[Category:{labels['secondary']}]]")
    elif entity_type == "PLACE":
        tags.append(f"[[Category:{labels['locations']}]]")
    elif entity_type == "ORG":
        tags.append(f"[[Category:{labels['organizations']}]]")
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
}


def infobox_template_content(entity_type: str) -> str:
    """Return the MediaWiki template source for the given entity type."""
    if entity_type not in _INFOBOX_TEMPLATES:
        raise ValueError(f"No infobox template for entity type: {entity_type!r}")
    return _INFOBOX_TEMPLATES[entity_type]


def main_page_content(book_title: str, author: str, pages: list[dict], labels: dict | None = None) -> str:
    """Generate Main_Page.wiki content from pipeline data."""
    persons = [p for p in pages if p["entity_type"] == "PERSON"]
    places = [p for p in pages if p["entity_type"] == "PLACE"]
    orgs = [p for p in pages if p["entity_type"] == "ORG"]

    principals = [p for p in persons if p["importance"] == "principal"][:8]
    major_places = [p for p in places if p["importance"] == "principal"][:5]

    persons_label = labels.get("persons", "Personnages") if labels else "Personnages"
    locations_label = labels.get("locations", "Lieux") if labels else "Lieux"
    orgs_label = labels.get("organizations", "Organisations") if labels else "Organisations"

    lines = [
        f"= {book_title} =",
        f"''{author}''",
        "",
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
    lines += [
        "",
        "== Navigation ==",
        f"* [[:Category:{persons_label}|Tous les personnages]]",
        f"* [[:Category:{locations_label}|Tous les lieux]]",
        f"* [[:Category:{orgs_label}|Toutes les organisations]]",
        "",
        "== Statistiques ==",
        f"* {len(pages)} pages wiki",
        f"* {len(persons)} personnages",
        f"* {len(places)} lieux",
        f"* {len(orgs)} organisations",
    ]
    return "\n".join(lines)
