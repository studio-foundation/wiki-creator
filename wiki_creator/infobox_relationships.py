"""Deterministic relationship buckets for the character infobox (STU-664).

Groups a PERSON's typed relationships into reader-facing infobox buckets —
Family / Romance / Friends & Allies / Enemies — each entry a ``[[wikilink]]``
with a ``†`` marker for a deceased related character. Pure logic, no LLM, no I/O:
the infobox rows are golden/unit-testable instead of trusting the writer's freeform
``infobox_fields``.

The type vocabulary is coarser than the sub-roles a real fandom infobox shows
(``father`` / ``wife`` / ``ex-girlfriend``): the classifier types a pair as
``family`` / ``romance``, so the qualifier stays the bucket, not the kin role.
Extending the vocabulary to sub-roles is a separate follow-up (STU-665).
"""

from __future__ import annotations

from wiki_creator.page_templates import canonical_relationship, output_language, sub_role_label
from wiki_creator.relationship_types import usable_relationship_type

# Canonical relationship type -> infobox bucket token. Types with no entry
# (acquaintance, employment, other, and any book-specific type) are too weak or
# too specific for the infobox and stay in the body section only (STU-664).
_BUCKET_BY_TYPE = {
    "family": "family",
    "romance": "romance",
    "budding_attraction": "romance",
    "friend": "friends_allies",
    "ally": "friends_allies",
    "mentor": "friends_allies",
    "strained_friendship": "friends_allies",
    "friendly_rivalry": "friends_allies",
    "wary_alliance": "friends_allies",
    "enemy": "enemies",
}

# Infobox row order: identity bonds first, conflict last.
INFOBOX_BUCKET_TOKENS = ("family", "romance", "friends_allies", "enemies")

_DECEASED_MARK = "†"


def bucket_for_type(token: str | None) -> str | None:
    """The infobox bucket a canonical relationship type maps to, or None when the
    type is too weak/specific for the infobox. Shared with the body Evolution index
    so both surfaces scope to the same bonds (STU-664)."""
    return _BUCKET_BY_TYPE.get(token) if token else None


def relationship_infobox_fields(entity: dict, book_config: dict | None = None) -> dict[str, str]:
    """Bucketed ``{token: "[[A]], [[B]] †"}`` infobox rows for one PERSON entity.

    Each typed relationship is grouped by ``bucket_for_type``; within a bucket the
    other party is a ``[[wikilink]]``, qualified by its fine kinship/romance sub-role
    when the classifier assigned one — ``[[James Potter]] (father)`` (STU-665) — and
    deceased ones (``rel['other_deceased']``, stamped at bundle build from
    ``entity_status.json``) carry a ``†``. Ordered by co-occurrence so the most
    prominent bond leads. Empty buckets are omitted.
    """
    own = {entity.get("canonical_name")} | set(entity.get("aliases") or [])
    lang = output_language(book_config)
    buckets: dict[str, list[tuple[int, str, str]]] = {t: [] for t in INFOBOX_BUCKET_TOKENS}
    seen: dict[str, set[str]] = {t: set() for t in INFOBOX_BUCKET_TOKENS}
    for rel in entity.get("relationships") or []:
        rtype = usable_relationship_type(rel.get("relationship_type"))
        bucket = bucket_for_type(canonical_relationship(rtype, book_config=book_config))
        if not bucket:
            continue
        other_is_a = rel.get("entity_a") not in own
        other = (rel["entity_a"] if other_is_a else rel["entity_b"]) or ""
        other = other.strip()
        if not other or other in seen[bucket]:
            continue
        seen[bucket].add(other)
        # The qualifier is the OTHER party's role: sub_role_a is what entity_a is,
        # sub_role_b what entity_b is (STU-665).
        sub_role = rel.get("sub_role_a") if other_is_a else rel.get("sub_role_b")
        qualifier = f" ({sub_role_label(sub_role, lang)})" if sub_role else ""
        deceased = f" {_DECEASED_MARK}" if rel.get("other_deceased") else ""
        entry = f"[[{other}]]{qualifier}{deceased}"
        count = int(rel.get("cooccurrence_count", 0) or 0)
        buckets[bucket].append((count, other, entry))
    fields: dict[str, str] = {}
    for token in INFOBOX_BUCKET_TOKENS:
        rows = buckets[token]
        if rows:
            rows.sort(key=lambda r: (-r[0], r[1]))
            fields[token] = ", ".join(entry for _, _, entry in rows)
    return fields
