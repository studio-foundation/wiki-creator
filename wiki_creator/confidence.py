"""Confidence tiers for signals transmitted to the wiki writer.

A human analyst distinguishes explicit textual facts from strong inferences and
from critical interpretation. The pipeline mirrors that with three tiers:

- ``explicit``        — named in the text, anchored by verbatim evidence
- ``inferred``        — strong co-occurrence, no explicit interaction attested
- ``interpretation``  — derived by reasoning (e.g. indirect graph paths)

Synergy with deterministic grounding: an unanchored claim (a classified type
with no textual evidence) is NOT an explicit fact — it degrades to ``inferred``.
"""
from __future__ import annotations

from wiki_creator.relationship_types import usable_relationship_type

EXPLICIT = "explicit"
INFERRED = "inferred"
INTERPRETATION = "interpretation"


def relationship_confidence(rel: dict) -> str:
    """Confidence tier of a direct (co-occurrence) relationship.

    ``explicit`` only when the relationship carries both a classified
    ``relationship_type`` and non-empty ``evidence`` quoting the text.
    Everything else (no classified type, or a type without grounding) is
    ``inferred``.
    """
    rtype = usable_relationship_type(rel.get("relationship_type"))
    evidence = str(rel.get("evidence") or "").strip()
    if rtype and evidence:
        return EXPLICIT
    return INFERRED
