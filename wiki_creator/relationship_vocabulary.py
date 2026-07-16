"""Relationship types only one novel has, declared in its book YAML (STU-472).

The generic enum in ``base.yaml`` names bonds any novel can hold. The bonds that
*define* a world are exactly the ones it cannot name: the Rider–dragon link, a
mating bond, parabatai. Flattened into ``ally`` or ``other``, the wiki loses the
relationship its readers came for.

The name is the reader-facing term, not a token — a book type carries no ``labels``
map. A book declares one output language and the person writing that YAML has read
the novel, so ``name: lien de Dragonnier`` is both what the classifier returns and
what the page prints.
"""

from __future__ import annotations

from typing import Collection


def book_relationship_types(
    book_config: dict | None, reserved: Collection[str] = ()
) -> list[dict[str, str]]:
    """The ``classification.relationship_types`` a book declares, as prompt entries.

    Raises on an incomplete or shadowing entry rather than dropping it: a type the
    config declares and the pipeline silently ignores is the STU-470 shape.
    """
    classification = (book_config or {}).get("classification") or {}
    declared = classification.get("relationship_types") or []

    types: list[dict[str, str]] = []
    seen = set()
    for entry in declared:
        name = str((entry or {}).get("name") or "").strip()
        description = str((entry or {}).get("description") or "").strip()
        if not name:
            raise ValueError(f"relationship_types: entry without a name: {entry!r}")
        if not description:
            raise ValueError(
                f"relationship_types: '{name}' has no description — a type with no "
                "criterion cannot be applied consistently"
            )
        if name in reserved:
            raise ValueError(
                f"relationship_types: '{name}' already names a generic type; "
                "pick a name specific to this book"
            )
        if name in seen:
            raise ValueError(f"relationship_types: '{name}' declared twice")
        seen.add(name)
        types.append({"name": name, "description": description})
    return types
