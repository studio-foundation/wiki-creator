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
_DEFAULT_TITLE_LABELS = {
    "minor_persons": "Personnages mineurs",
    "minor_locations": "Lieux mineurs",
    "minor_organizations": "Organisations mineures",
    "minor_other": "Autres entités mineures",
}


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


def collation_labels(export_cfg: dict) -> dict[str, str]:
    """Collective page titles from ``export.categories.labels``, French defaults."""
    labels = ((export_cfg or {}).get("categories") or {}).get("labels") or {}
    return {key: labels.get(key, default) for key, default in _DEFAULT_TITLE_LABELS.items()}


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


def _entry(entity: dict) -> str:
    """One collective-page entry. Every line is a fact the classification
    artifact already carries; no LLM."""
    lines = [f"## {entity.get('canonical_name', '')}"]
    aliases = [str(a) for a in entity.get("aliases") or [] if a]
    if aliases:
        lines.append(f"*Alias : {', '.join(aliases)}*")
    mentions = entity.get("total_mentions", 0)
    chapters = entity.get("chapters_present", 0)
    lines.append(f"Mentionné {mentions} fois dans {chapters} chapitre(s).")
    return "\n\n".join(lines)


def collective_pages(entities: list[dict], labels: dict[str, str]) -> list[dict]:
    """One page per title key, entries ordered by canonical name.

    Grouped by title, not by entity type: EVENT and OTHER share ``minor_other``,
    and two pages with the same title collide in the flat wiki namespace.
    """
    by_key: dict[str, list[dict]] = {}
    for entity in entities:
        key = _TITLE_LABEL_KEYS.get(entity.get("type", "OTHER"), _DEFAULT_TITLE_LABEL_KEY)
        by_key.setdefault(key, []).append(entity)

    pages = []
    for key in _DEFAULT_TITLE_LABELS:
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
                "content": "\n\n".join(_entry(e) for e in group),
            }
        )
    return pages
