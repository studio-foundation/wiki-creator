"""Ground-truth corpus loading and linting (STU-465/716/717/719).

The corpus lives in <series_dir>/books/ground-truth/ — flat for a single-tome
series, one <NN-slug>/ subdirectory per tome for a multi-tome one. Field names
stay suffixed _book1 in every tome; the directory disambiguates the tome.

Two GT file formats are accepted:
- flat:   {"entity": "...", "canonical_aliases_book1": [...], ...}
- nested: {"dinah": {...}, "alice": {...}} — any non-dict value (e.g. "_note")
  is ignored.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GtEntry:
    entity: str
    canonical_aliases: list[str]
    known_facts: list[str]
    known_relations: dict[str, str]
    forbidden: list[tuple[str, str]]  # (term, category)
    hallucination_signals: list[str]
    identity_confusion_forbidden: list[str]
    source_file: str = ""
    raw: dict = field(default_factory=dict)


def resolve_gt_dir(series_dir: Path | str, slug: str) -> Path | None:
    """Tome subdirectory when it exists, else the flat corpus, else None."""
    base = Path(series_dir) / "books" / "ground-truth"
    tome = base / slug
    if tome.is_dir():
        return tome
    if base.is_dir() and any(base.glob("*.json")):
        return base
    return None


def load_entries(gt_dir: Path | str) -> tuple[list[GtEntry], dict[str, dict]]:
    """Normalize every GT file under gt_dir into uniform entries.

    Returns (entries, by_entity) where by_entity maps the canonical entity name
    to the raw sub-object (needed by the structured-relation check, STU-717).
    """
    entries: list[GtEntry] = []
    by_entity: dict[str, dict] = {}
    for gf in sorted(Path(gt_dir).glob("*.json")):
        gt = json.loads(gf.read_text())
        if "entity" in gt:
            sub_objects = [(gt["entity"], gt)]
        else:
            sub_objects = [(k, v) for k, v in gt.items() if isinstance(v, dict)]
        for name, obj in sub_objects:
            canonical = obj.get("canonical_aliases_book1", [])
            forbidden = [
                (item, cat)
                for cat, items in (obj.get("forbidden_book1") or {}).items()
                if isinstance(items, list)
                for item in items
            ]
            entity_name = canonical[0] if canonical else name
            entries.append(
                GtEntry(
                    entity=entity_name,
                    canonical_aliases=canonical if canonical else [name],
                    known_facts=obj.get("known_facts_book1", []),
                    known_relations=obj.get("known_relations_book1", {}),
                    forbidden=forbidden,
                    hallucination_signals=obj.get("hallucination_signals", []),
                    identity_confusion_forbidden=obj.get(
                        "identity_confusion_forbidden", []
                    ),
                    source_file=str(gf),
                    raw=obj,
                )
            )
            by_entity[entity_name] = obj
    return entries, by_entity


def alias_lookup(entries: list[GtEntry]) -> dict[str, str]:
    """alias_lower -> entity_name, over every entry."""
    return {
        a.lower(): e.entity for e in entries for a in e.canonical_aliases
    }


def lint_corpus(
    entries: list[GtEntry], book_text: str
) -> list[tuple[str, str]]:
    """Mechanical corpus checks against the book's own text.

    Returns (level, message) with level FAIL or WARN. Every FAIL is a corpus
    bug; a WARN is fixed or justified in the corpus README. Rules, each learned
    from an observed false positive/negative — see the add-book skill:
    - aliases must exist and occur in the text (dead adaptation forms warn,
      an entity with no live alias fails);
    - forbidden terms are discriminating phrases that must NOT occur in text;
    - hallucination_signals are literal comma-free substrings, never the
      entity's own name, and must not occur in the text;
    - cross-entity alias containment (Mouse in Dormouse) needs same-file,
      shorter-binding-first ordering.
    """
    low = book_text.lower()
    out: list[tuple[str, str]] = []

    for e in entries:
        if not e.canonical_aliases or not e.raw.get("canonical_aliases_book1"):
            out.append(("FAIL", f"{e.entity}: no canonical_aliases_book1"))
        any_alias_in_text = any(a.lower() in low for a in e.canonical_aliases)
        for a in e.canonical_aliases:
            if len(a) <= 4:
                out.append(
                    ("WARN", f"{e.entity}: alias {a!r} is <=4 chars — substring noise risk")
                )
            if a.lower() not in low:
                level = "WARN" if any_alias_in_text else "FAIL"
                out.append(
                    (level, f"{e.entity}: alias {a!r} absent from the book text")
                )
        if not e.known_facts:
            out.append(("FAIL", f"{e.entity}: no known_facts_book1"))
        for term, cat in e.forbidden:
            if len(term) <= 4:
                out.append(("FAIL", f"{e.entity}: forbidden {term!r} too short"))
            if term.lower() in low:
                out.append(
                    ("FAIL", f"{e.entity}: forbidden {term!r} OCCURS in the book text")
                )
        for s in e.hallucination_signals:
            if "," in s:
                out.append(
                    ("FAIL", f"{e.entity}: signal {s!r} contains a comma (loader splits it)")
                )
            if s.lower() in low:
                out.append(
                    ("FAIL", f"{e.entity}: signal {s!r} OCCURS in the book text (false-positive machine)")
                )
            if any(s.strip().lower() == a.lower() for a in e.canonical_aliases):
                out.append(
                    ("FAIL", f"{e.entity}: signal {s!r} is just the entity name")
                )

    pairs = [(e.entity, a) for e in entries for a in e.canonical_aliases]
    for i, (n1, a1) in enumerate(pairs):
        for n2, a2 in pairs[i + 1 :]:
            if n1 != n2 and (
                a1.lower() in a2.lower() or a2.lower() in a1.lower()
            ):
                out.append(
                    (
                        "WARN",
                        f"alias collision {n1}:{a1!r} <-> {n2}:{a2!r} — same file, shorter-binding first?",
                    )
                )
    return out
