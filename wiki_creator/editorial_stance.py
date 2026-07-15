"""Editorial stance (STU-507): whether pages speak from inside the fiction.

Orthogonal to grounding ("invent nothing", ``GROUNDING_BLOCK``), which is
unconditional — no stance may relax it. Every out-of-universe surface is
authorized by an explicit key here, never as a side effect of a prompt rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from wiki_creator.sections import SECTION_TITLES

MODES = ("in_universe", "out_of_universe", "hybrid")

# Sections that necessarily address the reader from outside the fiction, mapped
# to the hybrid_exceptions key that authorizes each.
OUT_OF_UNIVERSE_SECTIONS = {
    "references": "references_section",
    "narrative_role": "narrative_role_section",
}

_DEFAULT_EXCEPTIONS = frozenset(OUT_OF_UNIVERSE_SECTIONS.values())

GROUNDING_BLOCK = (
    "GROUNDING — this is a fictional world, and the GROUNDING EXCERPTS below are its "
    "ONLY authoritative source of truth:\n"
    "- Ignore any prior knowledge you have of this book, series, or author: whatever you "
    "recall of its plot, characters, or ending is not evidence.\n"
    "- Every factual claim in your output must be directly supported by one of the "
    "GROUNDING EXCERPTS. If you cannot point to a supporting excerpt, do not write the claim."
)

_MODE_RULES = {
    "in_universe": (
        "- Write from inside the fictional world, as if it were real. Never refer to the "
        "text as a novel, a book or a story, never mention chapters or narration, never "
        "address the reader."
    ),
    "out_of_universe": (
        "- Write as an external encyclopedia about a work of fiction: you may name the "
        "work, call it a novel, and describe its narrative as narrative."
    ),
    "hybrid": (
        "- Default to writing from inside the fictional world, as if it were real: never "
        "refer to the text as a novel, a book or a story, and never address the reader."
    ),
}

_AUTHOR_RULE = (
    "- Never mention the real-world author, publisher, publication date, or edition."
)


@dataclass(frozen=True)
class EditorialStance:
    """Defaults reproduce the posture the pipeline drifted into before STU-507:
    hybrid, both out-of-universe sections allowed, run metadata and importance
    tier published. An unconfigured book keeps its output unchanged."""

    mode: str = "hybrid"
    hybrid_exceptions: frozenset[str] = _DEFAULT_EXCEPTIONS
    expose_pipeline_metadata: bool = True
    expose_importance_tier: bool = True
    forbid_author_mentions: bool = True

    def allows_section(self, section: str) -> bool:
        key = OUT_OF_UNIVERSE_SECTIONS.get(section)
        if key is None:
            return True
        if self.mode == "out_of_universe":
            return True
        if self.mode == "in_universe":
            return False
        return key in self.hybrid_exceptions

    def prompt_block(self, sections: list[str] | None = None) -> str:
        """``sections`` = what this call actually writes; the hybrid exception line
        names only the exceptions among them, so a section-scoped prompt never
        advertises a section it is not generating."""
        lines = [f"EDITORIAL STANCE — {self.mode.replace('_', '-')}:", _MODE_RULES[self.mode]]
        if self.mode == "hybrid":
            allowed = [
                SECTION_TITLES[s]
                for s, key in OUT_OF_UNIVERSE_SECTIONS.items()
                if key in self.hybrid_exceptions
                and (sections is None or s in sections)
            ]
            if allowed:
                lines.append(
                    "- Exception — these sections are written from outside the fiction, "
                    f"and only these: {', '.join(allowed)}."
                )
        if self.forbid_author_mentions:
            lines.append(_AUTHOR_RULE)
        return "\n".join(lines)


def editorial_stance(book_cfg: dict) -> EditorialStance:
    raw = ((book_cfg.get("generation") or {}).get("editorial_stance") or {})
    mode = str(raw.get("mode", "hybrid"))
    if mode not in MODES:
        raise ValueError(f"editorial_stance.mode must be one of {MODES}, got {mode!r}")
    exceptions = frozenset(raw.get("hybrid_exceptions", _DEFAULT_EXCEPTIONS))
    unknown = exceptions - _DEFAULT_EXCEPTIONS
    if unknown:
        raise ValueError(
            f"unknown editorial_stance.hybrid_exceptions: {sorted(unknown)} "
            f"(known: {sorted(_DEFAULT_EXCEPTIONS)})"
        )
    return EditorialStance(
        mode=mode,
        hybrid_exceptions=exceptions,
        expose_pipeline_metadata=bool(raw.get("expose_pipeline_metadata", True)),
        expose_importance_tier=bool(raw.get("expose_importance_tier", True)),
        forbid_author_mentions=bool(raw.get("forbid_author_mentions", True)),
    )
