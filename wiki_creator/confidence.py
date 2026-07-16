"""Confidence tiers for signals transmitted to the wiki writer.

A human analyst distinguishes explicit textual facts from strong inferences and
from critical interpretation. The pipeline mirrors that with three tiers:

- ``explicit``        — named in the text, anchored by verbatim evidence
- ``inferred``        — strong co-occurrence, no explicit interaction attested
- ``interpretation``  — derived by reasoning (e.g. indirect graph paths)

Synergy with deterministic grounding: an unanchored claim (a classified type
with no textual evidence) is NOT an explicit fact — it degrades to ``inferred``.

Evidence *presence* is not evidence *strength* (STU-476): "their eyes met and he
smiled" anchors a type as verbatim as a kiss does, and typing a romance off it is
an interpretation. Only the classifier reads the excerpts, so it grades the tier
(``relationships.confidence`` in base.yaml); this module keeps the deterministic
floor no grade may lift — an ungrounded type is never explicit, whatever it claims.
"""
from __future__ import annotations

from wiki_creator.page_templates import confidence_tokens
from wiki_creator.relationship_types import usable_relationship_type

EXPLICIT = "explicit"
INFERRED = "inferred"
INTERPRETATION = "interpretation"

# Weakest to strongest. Order is semantics, not presentation — it decides what
# counts as over-grading a relationship (STU-476), so it lives here rather than
# riding on the key order of base.yaml.
TIER_ORDER = (INTERPRETATION, INFERRED, EXPLICIT)


def is_stronger(tier: str, than: str) -> bool:
    """True when ``tier`` claims more than ``than``. Unknown tiers are weakest."""
    rank = {name: i for i, name in enumerate(TIER_ORDER)}
    return rank.get(tier, -1) > rank.get(than, -1)


def relationship_confidence(rel: dict) -> str:
    """Confidence tier of a direct (co-occurrence) relationship.

    No classified ``relationship_type``, or a type without ``evidence`` quoting the
    text, is ``inferred``. Otherwise the classifier's graded ``confidence`` stands.
    Pre-STU-476 artifacts carry no grade and keep their original reading (evidence
    present ⇒ ``explicit``).
    """
    rtype = usable_relationship_type(rel.get("relationship_type"))
    evidence = str(rel.get("evidence") or "").strip()
    if not (rtype and evidence):
        return INFERRED
    graded = str(rel.get("confidence") or "").strip().lower()
    if graded in confidence_tokens():
        return graded
    return EXPLICIT
