"""Merge strategies — turn detector signals into normalized MergeDecisions.

Pas 2 (STU-442): the merge mechanisms (Jaro-Winkler clustering, title/pure-title/
role-symmetric/pattern/cooccurrence alias resolution, Ollama confirmation) become
MergeStrategy objects that *propose* MergeDecisions to the registry. This module
owns the single strategy-name vocabulary and the evidence-composition helpers.

Pure module, no I/O. Spec: docs/superpowers/specs/2026-07-12-stu-442-merge-strategies-design.md
"""
from __future__ import annotations

from typing import Protocol

from wiki_creator.registry import MergeDecision, _decision_id

# recorded alias-resolution method → spec strategy name. Identity entries are
# listed explicitly so registry.json's vocabulary is readable in one place.
STRATEGY_VOCABULARY: dict[str, str] = {
    "title_alias": "title_apposition",
    "llm": "llm_confirm",
    "pure_title": "pure_title",
    "role_symmetric": "role_symmetric",
    "pattern": "pattern",
    "cooccurrence": "cooccurrence",
}


def normalize_method(method: str) -> str:
    """Map a recorded method to its strategy name (identity for the unmapped)."""
    if not method:
        return "unknown"
    return STRATEGY_VOCABULARY.get(method, method)


class MergeStrategy(Protocol):
    name: str

    def propose(
        self, survivor_id: str, absorbed_slug: str, *, evidence: str, confidence: str
    ) -> MergeDecision:
        ...


class _NamedStrategy:
    """All strategies share behavior; they differ only by name + evidence
    fidelity (set by the caller). One class keeps the layer DRY."""

    def __init__(self, name: str) -> None:
        self.name = name

    def propose(
        self, survivor_id: str, absorbed_slug: str, *, evidence: str, confidence: str
    ) -> MergeDecision:
        d_id = _decision_id(self.name, (survivor_id, absorbed_slug), evidence)
        return MergeDecision(
            decision_id=d_id,
            strategy=self.name,
            inputs=(survivor_id, absorbed_slug),
            evidence=evidence,
            confidence=confidence,
        )


CLUSTER_JW = _NamedStrategy("cluster_jw")
TITLE_APPOSITION = _NamedStrategy("title_apposition")
PURE_TITLE = _NamedStrategy("pure_title")
ROLE_SYMMETRIC = _NamedStrategy("role_symmetric")
LLM_CONFIRM = _NamedStrategy("llm_confirm")
PATTERN = _NamedStrategy("pattern")
COOCCURRENCE = _NamedStrategy("cooccurrence")
EXTRACTION_GROUPING = _NamedStrategy("extraction_grouping")
MANUAL = _NamedStrategy("manual")

_STRATEGIES: dict[str, MergeStrategy] = {
    s.name: s
    for s in (
        CLUSTER_JW, TITLE_APPOSITION, PURE_TITLE, ROLE_SYMMETRIC, LLM_CONFIRM,
        PATTERN, COOCCURRENCE, EXTRACTION_GROUPING, MANUAL,
    )
}


def strategy_for(name: str) -> MergeStrategy:
    """Return the named strategy, minting one for any unmapped identifier so the
    layer never crashes on an unexpected recorded method."""
    return _STRATEGIES.get(name) or _NamedStrategy(name)


def recover_chapter_id(snippet: str, full_registries: dict) -> str | None:
    """Best-effort: find the chapter whose preserved sentence contains the
    recorded snippet. Deterministic (first match in insertion order); None on miss."""
    if not snippet:
        return None
    for record in full_registries.values():
        for chapter_id, sentences in (record.get("mentions_by_chapter") or {}).items():
            for sentence in sentences or []:
                if snippet in str(sentence):
                    return str(chapter_id)
    return None


def compose_evidence(snippet: str, chapter_id: str | None) -> str:
    """Evidence = snippet + chapter_id (spec §3.2)."""
    if chapter_id:
        return f"{snippet} [chapter={chapter_id}]"
    return snippet
