"""Collation (STU-511): the per-tier decision on what kind of page an entity
earns — its own dedicated page, one entry on a shared collective page, or
nothing at all. Pure logic; the wiring lives in scripts/wiki_preparation.py.

Driven by book YAML ``generation.collation``:

    generation:
      collation:
        figurant:
          mode: collective        # dedicated | collective | drop
          promote_if:
            appears_in_event_salience_above: 0.7

A tier with no entry keeps ``dedicated`` — the pre-STU-511 behavior.
"""
from __future__ import annotations

from dataclasses import dataclass

from wiki_creator.page_templates import chrome_label

DEFAULT_MODE = "dedicated"
MODES = ("dedicated", "collective", "drop")

COLLATION_ENTITY_TYPE = "COLLATION"
COLLATION_IMPORTANCE = "figurant"

# Values key into the export labels dict.
_TITLE_LABEL_KEYS = {
    "PERSON": "minor_persons",
    "PLACE": "minor_locations",
    "ORG": "minor_organizations",
}
_DEFAULT_TITLE_LABEL_KEY = "minor_other"

# Deliberately not the `secondary` category labels: a collective page holds the
# tier below. A page title colliding with a category name reads as a bug.
_TITLE_LABEL_ORDER = ("minor_persons", "minor_locations", "minor_organizations", "minor_other")


@dataclass
class TierCollation:
    mode: str
    promote_above: float | None


def collation_config(book_cfg: dict) -> dict[str, TierCollation]:
    """{tier: TierCollation} from ``generation.collation``. An unknown mode
    falls back to ``dedicated`` rather than silently dropping pages."""
    cfg = (book_cfg.get("generation") or {}).get("collation") or {}
    config: dict[str, TierCollation] = {}
    for tier, raw in cfg.items():
        raw = raw or {}
        mode = raw.get("mode", DEFAULT_MODE)
        threshold = (raw.get("promote_if") or {}).get("appears_in_event_salience_above")
        try:
            promote_above = None if threshold is None else float(threshold)
        except (TypeError, ValueError):
            promote_above = None
        config[str(tier)] = TierCollation(
            mode if mode in MODES else DEFAULT_MODE, promote_above
        )
    return config


def collation_labels(export_cfg: dict, lang: str = "fr") -> dict[str, str]:
    """Collective page titles: ``export.categories.labels`` override the
    ``lang``-localized base.yaml defaults (STU-514)."""
    labels = ((export_cfg or {}).get("categories") or {}).get("labels") or {}
    return {key: labels.get(key) or chrome_label(key, lang) for key in _TITLE_LABEL_ORDER}


def _promoted(entity: dict, events: list[dict], threshold: float | None) -> bool:
    """True when the entity takes part in an event salient enough to earn a
    dedicated page despite its tier. Participants or places, matching
    wiki_preparation.events_for_entity."""
    if threshold is None:
        return False
    name = entity.get("canonical_name", "")
    return any(
        (name in (event.get("participants") or []) or name in (event.get("places") or []))
        and float(event.get("salience", 0.0)) > threshold
        for event in events
    )


def partition_by_collation(
    entities: list[dict], config: dict[str, TierCollation], events: list[dict]
) -> tuple[list[dict], list[dict], list[dict]]:
    """Split entities into (dedicated, collective, dropped) per their tier's mode."""
    dedicated: list[dict] = []
    collective: list[dict] = []
    dropped: list[dict] = []
    for entity in entities:
        rule = config.get(entity.get("importance", "figurant"))
        if rule is None or rule.mode == "dedicated" or _promoted(entity, events, rule.promote_above):
            dedicated.append(entity)
        elif rule.mode == "collective":
            collective.append(entity)
        else:
            dropped.append(entity)
    return dedicated, collective, dropped


def _entry(entity: dict, lang: str = "fr") -> str:
    """One collective-page entry. Every line is a fact the classification
    artifact already carries; no LLM."""
    lines = [f"## {entity.get('canonical_name', '')}"]
    aliases = [str(a) for a in entity.get("aliases") or [] if a]
    if aliases:
        lines.append(f"*{chrome_label('collation_aliases', lang).format(aliases=', '.join(aliases))}*")
    mentions = entity.get("total_mentions", 0)
    chapters = entity.get("chapters_present", 0)
    lines.append(chrome_label("collation_mentions", lang).format(mentions=mentions, chapters=chapters))
    return "\n\n".join(lines)


def collective_pages(entities: list[dict], labels: dict[str, str], lang: str = "fr") -> list[dict]:
    """One page per title key, entries ordered by canonical name.

    Grouped by title, not by entity type: EVENT and OTHER share ``minor_other``,
    and two pages with the same title collide in the flat wiki namespace.
    """
    by_key: dict[str, list[dict]] = {}
    for entity in entities:
        key = _TITLE_LABEL_KEYS.get(entity.get("type", "OTHER"), _DEFAULT_TITLE_LABEL_KEY)
        by_key.setdefault(key, []).append(entity)

    pages = []
    for key in _TITLE_LABEL_ORDER:
        group = by_key.get(key)
        if not group:
            continue
        group = sorted(group, key=lambda e: str(e.get("canonical_name", "")).casefold())
        pages.append(
            {
                "title": labels[key],
                "importance": COLLATION_IMPORTANCE,
                "entity_type": COLLATION_ENTITY_TYPE,
                "infobox_fields": {},
                "content": "\n\n".join(_entry(e, lang) for e in group),
            }
        )
    return pages
