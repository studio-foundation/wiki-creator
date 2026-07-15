"""Name-collision policy (STU-506): what happens when two entities want the
same name, and how a title namespace stays collision-free.

Pure module, no I/O (same pattern as editorial_stance.py / collation.py).

The historical registry merged two entities sharing a ``canonical_name``
regardless of type — a PERSON and a PLACE homonym became one entity, a
coherent, well-written, false page (registry.py::_merge_duplicate_canonicals).
This declares the policy instead of leaving it implicit:

* ``merge_requires_same_type`` puts ``entity_type`` in the merge key, so
  different-type homonyms coexist rather than collapse (the registry's
  invariant 1 goes from "true by construction" to "true by policy");
* ``collision_policy`` decides what to do with two entities that still render
  to the same page title — ``disambiguate`` (append a type label), ``fail``
  (raise), or ``merge`` (legacy: collapse them);
* ``alias_arbitration`` orders the tie-break when several entities claim the
  same alias within a type.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from wiki_creator.export_helpers import page_filename

POLICIES = ("merge", "disambiguate", "fail")
ARBITRATION_KEYS = ("canonical_owner", "mention_count", "first_seen")
_DEFAULT_ORDER = ("canonical_owner", "mention_count", "first_seen")
_DEFAULT_TEMPLATE = "{name} ({type_label})"


@dataclass(frozen=True)
class NamingPolicy:
    """Defaults are the safe posture STU-506 introduces: different-type
    homonyms never merge, and a title collision is disambiguated rather than
    silently accepted. A book keeps the legacy behavior with
    ``collision_policy: merge`` (or ``merge_requires_same_type: false``)."""

    collision_policy: str = "disambiguate"
    merge_requires_same_type: bool = True
    disambiguator_template: str = _DEFAULT_TEMPLATE
    alias_arbitration: tuple[str, ...] = _DEFAULT_ORDER

    @property
    def merges_cross_type(self) -> bool:
        """Whether the registry may fold two different-type homonyms into one."""
        return self.collision_policy == "merge" or not self.merge_requires_same_type

    @property
    def fails_on_collision(self) -> bool:
        return self.collision_policy == "fail"

    def disambiguate(self, name: str, type_label: str) -> str:
        return self.disambiguator_template.format(name=name, type_label=type_label)


def naming_policy(book_cfg: dict) -> NamingPolicy:
    raw = (book_cfg or {}).get("naming") or {}

    policy = str(raw.get("collision_policy", "disambiguate"))
    if policy not in POLICIES:
        raise ValueError(f"naming.collision_policy must be one of {POLICIES}, got {policy!r}")

    order = tuple(str(k) for k in ((raw.get("alias_arbitration") or {}).get("order") or _DEFAULT_ORDER))
    unknown = [k for k in order if k not in ARBITRATION_KEYS]
    if unknown:
        raise ValueError(
            f"unknown naming.alias_arbitration.order keys: {unknown} (known: {list(ARBITRATION_KEYS)})"
        )

    template = str((raw.get("disambiguator") or {}).get("template") or _DEFAULT_TEMPLATE)
    return NamingPolicy(
        collision_policy=policy,
        merge_requires_same_type=bool(raw.get("merge_requires_same_type", True)),
        disambiguator_template=template,
        alias_arbitration=order,
    )


def disambiguate_page_titles(
    pages: list[dict], policy: NamingPolicy, type_labels: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """Rewrite ``page['title']`` in place so no two pages of different types
    render to the same ``page_filename`` (the flat MediaWiki title namespace,
    checked by the ``unique-page-title`` validator). Only acts under
    ``collision_policy == "disambiguate"``; ``fail`` lets the validator reject
    the run, ``merge`` should have collapsed the pages upstream.

    Same-type collisions are left untouched — they are a real duplicate, not an
    ambiguity a type label could resolve. ``type_labels`` maps entity_type to
    the label injected by ``disambiguator.template`` (falls back to the raw
    entity_type). Returns the (old_title, new_title) rewrites, in page order."""
    if policy.collision_policy != "disambiguate":
        return []

    type_labels = type_labels or {}
    by_filename: dict[str, list[dict]] = defaultdict(list)
    for page in pages:
        by_filename[page_filename(str(page.get("title") or ""))].append(page)

    rewrites: list[tuple[str, str]] = []
    for claimants in by_filename.values():
        types = {p.get("entity_type") for p in claimants}
        if len(claimants) < 2 or len(types) < 2:
            continue
        for page in claimants:
            old = str(page.get("title") or "")
            etype = str(page.get("entity_type") or "")
            new = policy.disambiguate(old, type_labels.get(etype, etype))
            page["title"] = new
            rewrites.append((old, new))
    return rewrites
