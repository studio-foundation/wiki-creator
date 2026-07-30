"""Render one merged wiki page per series character (STU-668).

Pure wikitext render, no I/O, no LLM — the series-scope counterpart of
``scripts/wiki_export.py::render_page``. A ``SeriesCharacter`` (built by
``wiki_creator.series.build_series_characters``) becomes one page:

- a single infobox — reconciled latest-wins Status, collapsed by default, and a
  multi-tome ``apparition`` line;
- one ``mw-collapsible`` section per tome (``tome_collapsible_section``), headed by
  the tome's own title and holding only that tome's narrative (its Biography prose
  and events), all collapsed — spoiler safety rides on the reader expanding the
  tomes they have read, replacing the coarse per-tome export gate (STU-232 axis);
- the character's attribute sections (Personality, Trivia, …) consolidated once,
  latest tome winning, instead of repeated inside every tome body (STU-718);
- a merged, latest-first relationship evolution index across every tome.

Under A2 there is exactly one page per character, so no cross-tome title
disambiguation is needed (STU-553's collision killer does not apply).
"""

from __future__ import annotations

import re

from wiki_creator import entity_taxonomy
from wiki_creator.entity_status import death_label, status_label
from wiki_creator.export_helpers import category_tags, page_filename
from wiki_creator.md2wiki import convert, make_infobox_call
from wiki_creator.page_templates import chrome_label, load_base_template, slot_label
from wiki_creator.series import SeriesCharacter, TomeContribution
from wiki_creator.spoiler_blocks import gate_infobox_spoilers, tome_collapsible_section
from wiki_creator.tome_labels import appearance_label


def _infobox_fields(character: SeriesCharacter, lang: str) -> dict:
    """Fresh infobox for the merged character: name, aliases, multi-tome
    appearance, and the latest-wins Status/death (gated collapsed like the
    per-tome exporter). Status is added only when a tome delivered a verdict —
    an absent verdict drops the row rather than asserting ``unknown``."""
    fields: dict = {"nom": character.canonical_name}
    aliases = [a for a in character.aliases if a and a != character.canonical_name]
    if aliases:
        fields["alias"] = ", ".join(aliases)
    appearance = appearance_label(character.books, lang=lang)
    if appearance:
        fields["apparition"] = appearance
    if character.status:
        fields["status"] = status_label(character.status.get("status"), lang)
        death = death_label(character.status.get("agent"), character.status.get("place"), lang)
        if death:
            fields["death"] = death
    return gate_infobox_spoilers(fields, lang=lang)


_HEADING_LINE_RE = re.compile(r"(?m)^(=+) (.+?) (=+)$")
_H2_SECTION_RE = re.compile(r"(?m)^(== .+? ==)$")


def _norm_heading(heading: str) -> str:
    return heading.strip("= ").strip().lower()


def _demote_headings(wikitext: str) -> str:
    """Add one level to every heading so an unrecognized section nests under the
    collapsible tome heading (STU-718) instead of siding it — its ``== Foo ==``
    becomes ``=== Foo ===``, a subsection of the tome."""
    return _HEADING_LINE_RE.sub(lambda m: f"={m.group(1)} {m.group(2)} {m.group(3)}=", wikitext)


def _section_tokens(entity_type: str) -> list[str]:
    """The ordered section-slot tokens this entity type declares (base template)."""
    groups = (load_base_template().get("entity_types") or {}).get(str(entity_type).upper()) or {}
    return [s["token"] for s in (groups.get("sections") or []) if s.get("token")]


def _split_sections(content: str) -> list[tuple[str | None, str]]:
    """Convert a tome page body and split into ``(heading | None, text)`` sections.
    The first tuple carries any pre-heading text with ``heading=None``."""
    parts = _H2_SECTION_RE.split(convert(content or ""))
    sections: list[tuple[str | None, str]] = []
    if parts[0].strip():
        sections.append((None, parts[0].strip()))
    for heading, body in zip(parts[1::2], parts[2::2]):
        sections.append((heading, body.strip()))
    return sections


def _tome_narrative(contribution: TomeContribution, biography: str, lang: str) -> str:
    """The tome's own récit: its Biography prose (no sub-heading — the tome title
    heads it) followed by that tome's events."""
    parts = [biography] if biography else []
    events = sorted(contribution.events, key=lambda e: e.get("chapter") or 0)
    if events:
        heading = slot_label("events", lang)
        bullets = "\n".join(f"* {e.get('description', '')}".rstrip() for e in events)
        parts.append(f"=== {heading} ===\n\n{bullets}")
    return "\n\n".join(parts)


_REL_TARGET_RE = re.compile(r"\[\[([^\]|]+)")


def _merged_relationship_index(character: SeriesCharacter) -> list[str]:
    """Every tome's ``relationship_index`` merged to one line per related entity,
    latest tome winning the chapter span — the same latest-wins reconciliation as
    Status. Walked latest tome first so the first line seen for a target is kept;
    within a tome the lines are already most-recent-reveal first."""
    seen: set[str] = set()
    merged: list[str] = []
    for contribution in reversed(character.contributions):
        for line in (contribution.page or {}).get("relationship_index") or []:
            match = _REL_TARGET_RE.search(line)
            key = match.group(1).strip() if match else line
            if key not in seen:
                seen.add(key)
                merged.append(line)
    return merged


def render_series_character_page(
    character: SeriesCharacter,
    labels: dict,
    *,
    lang: str,
    expose_importance_tier: bool = True,
) -> tuple[str, str]:
    """``(path relative to the series wiki dir, wikitext)`` for one merged character.

    Per-tome sections carry only that tome's Biography récit (headed by the tome
    title); the character's attribute sections are consolidated once, latest tome
    winning; Relationships is the single merged evolution index (STU-718)."""
    infobox = make_infobox_call(character.entity_type, _infobox_fields(character, lang))

    collapse = chrome_label("collapse", lang)
    tokens = _section_tokens(character.entity_type)
    label_to_token = {_norm_heading(slot_label(t, lang)): t for t in tokens}
    global_tokens = set(tokens) - {"biography", "relationships"}

    globals_content: dict[str, str] = {}
    sections: list[str] = []
    for contribution in character.contributions:
        if not contribution.page:
            continue
        biography: list[str] = []
        for heading, text in _split_sections((contribution.page or {}).get("content", "")):
            token = label_to_token.get(_norm_heading(heading)) if heading else "biography"
            if token in global_tokens:
                globals_content[token] = text  # latest tome wins
            elif token == "relationships":
                continue  # replaced by the merged cross-tome index
            elif token is None and heading:
                biography.append(_demote_headings(f"{heading}\n\n{text}"))  # keep unknowns local
            elif text:
                biography.append(text)
        heading = contribution.title or chrome_label("tome_heading", lang).format(tome=contribution.tome_number)
        expand = chrome_label("reveal_tome", lang).format(tome=contribution.tome_number)
        narrative = _tome_narrative(contribution, "\n\n".join(biography), lang)
        sections.append(tome_collapsible_section(heading, narrative, expand, collapse))

    body = "".join(sections)

    rel_lines = _merged_relationship_index(character)
    for token in tokens:
        if token == "relationships":
            if rel_lines:
                relations = slot_label("relationships", lang)
                evolution = chrome_label("evolution", lang)
                body += f"\n== {relations} ==\n\n''{evolution}''\n" + "\n".join(rel_lines) + "\n"
        elif token in globals_content:
            body += f"\n== {slot_label(token, lang)} ==\n\n{globals_content[token]}\n"

    page_content = infobox + "\n\n" + body.rstrip()
    cats = category_tags(
        character.entity_type, character.importance, labels, character.books,
        expose_importance_tier=expose_importance_tier,
    )
    if cats:
        page_content += "\n\n" + "\n".join(cats)

    subdir = entity_taxonomy.subdir(character.entity_type)
    return f"{subdir}/{page_filename(character.canonical_name)}.wiki", page_content
