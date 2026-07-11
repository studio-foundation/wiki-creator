"""Entity identity registry — single source of truth for « qui est qui ».

Pure module, no pipeline side effects (same pattern as page_templates.py).

Pas 1 (STU-441): read-only reconstruction from existing pipeline artifacts
(splits.json + alias-resolution output + *_full.json mention registries).
Nothing consumes registry.json yet — the first consumer is STU-435 (pas 3).

Spec: docs/superpowers/specs/2026-07-11-refondation-wiki-creator-design.md §3
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

REGISTRY_VERSION = 1
ENTITY_TYPES = ("PERSON", "PLACE", "ORG", "EVENT", "OTHER")


@dataclass(frozen=True)
class Mention:
    surface: str
    chapter_id: str
    source: str = "ner"  # "ner" | "coref" | "pattern"
    # None when rebuilt from artifacts: extraction does not preserve character
    # offsets nor the raw model label — real values arrive when extraction
    # feeds the registry directly (pas 2+).
    start: int | None = None
    end: int | None = None
    raw_label: str | None = None
    context: str | None = None  # context sentence from *_full.json


@dataclass(frozen=True)
class MergeDecision:
    decision_id: str
    strategy: str  # "cluster_jw" | "extraction_grouping" | recorded method | "manual"
    inputs: tuple[str, str]  # (surviving entity_id, absorbed entity_id / alias slug)
    evidence: str
    confidence: str  # "high" | "medium" | "low" | "certain" (manual)
    reversible: bool = True


@dataclass
class EntityRecord:
    entity_id: str  # stable slug derived from the canonical name
    canonical_name: str
    entity_type: str  # PERSON | PLACE | ORG | EVENT | OTHER
    aliases: list[str] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)  # decision_ids


def entity_slug(name: str) -> str:
    """Deterministic ascii slug for entity ids (invariant 4: no randomness)."""
    # Normalize to decomposed form (é -> e + accent)
    slug = unicodedata.normalize("NFKD", str(name or ""))
    # Process each character: keep ASCII, skip combining marks, treat non-ASCII as separators
    result = []
    for c in slug:
        if ord(c) < 128:
            result.append(c)
        elif unicodedata.category(c).startswith("M"):
            # Skip combining marks (accents, diacritics)
            pass
        else:
            # Non-ASCII non-combining: treat as separator
            result.append(" ")
    slug = "".join(result)
    # Convert separators and non-alphanumeric to underscores, collapse multiple
    slug = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    return slug or "unnamed"


def _decision_id(strategy: str, inputs: tuple[str, str], evidence: str) -> str:
    """Content-derived id: identical decision content ⇒ identical id across runs."""
    payload = json.dumps([strategy, list(inputs), evidence], ensure_ascii=False)
    return "d_" + hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


class Registry:
    """In-memory registry. Invariants (spec §3.2) are enforced by validate():

    1. an alias belongs to exactly one entity (casefold comparison);
    2. every alias ≠ canonical_name is justified by ≥1 MergeDecision
       (its slug appears in the inputs of a decision attached to the record);
    3. canonical_name ∈ aliases;
    4. entity_id determinism — structural (ids derive only from content,
       see entity_slug/_decision_id) and covered by tests, not checkable
       within a single instance.
    """

    def __init__(
        self,
        entities: list[EntityRecord] | None = None,
        decisions: dict[str, MergeDecision] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        self.entities: list[EntityRecord] = list(entities or [])
        self.decisions: dict[str, MergeDecision] = dict(decisions or {})
        self.warnings: list[str] = list(warnings or [])

    def lookup(self, surface: str) -> EntityRecord | None:
        key = str(surface).casefold()
        for record in self.entities:
            if any(alias.casefold() == key for alias in record.aliases):
                return record
        return None

    def alias_table(self) -> dict[str, str]:
        """surface → entity_id (the STU-435 consumer API)."""
        table: dict[str, str] = {}
        for record in self.entities:
            for alias in record.aliases:
                table[alias] = record.entity_id
        return table

    def audit_log(self) -> list[MergeDecision]:
        return sorted(self.decisions.values(), key=lambda d: d.decision_id)

    def validate(self) -> None:
        seen_ids: set[str] = set()
        owners: dict[str, str] = {}
        for record in self.entities:
            if record.entity_id in seen_ids:
                raise ValueError(f"duplicate entity_id '{record.entity_id}'")
            seen_ids.add(record.entity_id)

            if record.canonical_name not in record.aliases:
                raise ValueError(
                    "invariant 3 violated: canonical_name "
                    f"'{record.canonical_name}' not in aliases of '{record.entity_id}'"
                )
            for alias in record.aliases:
                key = alias.casefold()
                owner = owners.get(key)
                if owner is not None and owner != record.entity_id:
                    raise ValueError(
                        f"invariant 1 violated: alias '{alias}' belongs to "
                        f"both '{owner}' and '{record.entity_id}'"
                    )
                owners[key] = record.entity_id

            justified: set[str] = set()
            for d_id in record.decisions:
                decision = self.decisions.get(d_id)
                if decision is None:
                    raise ValueError(
                        f"unknown decision_id '{d_id}' on entity '{record.entity_id}'"
                    )
                justified.update(decision.inputs)
            for alias in record.aliases:
                if alias == record.canonical_name:
                    continue
                if entity_slug(alias) not in justified:
                    raise ValueError(
                        f"invariant 2 violated: alias '{alias}' of "
                        f"'{record.entity_id}' has no MergeDecision"
                    )

    def to_dict(self) -> dict:
        return {
            "version": REGISTRY_VERSION,
            "entities": [
                {
                    "entity_id": r.entity_id,
                    "canonical_name": r.canonical_name,
                    "entity_type": r.entity_type,
                    "aliases": list(r.aliases),
                    "mentions": [asdict(m) for m in r.mentions],
                    "decisions": list(r.decisions),
                }
                for r in self.entities
            ],
            "decisions": [
                {
                    "decision_id": d.decision_id,
                    "strategy": d.strategy,
                    "inputs": list(d.inputs),
                    "evidence": d.evidence,
                    "confidence": d.confidence,
                    "reversible": d.reversible,
                }
                for d in self.audit_log()
            ],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Registry":
        decisions: dict[str, MergeDecision] = {}
        for d in raw.get("decisions") or []:
            inputs = list(d.get("inputs") or ["", ""])
            decisions[str(d["decision_id"])] = MergeDecision(
                decision_id=str(d["decision_id"]),
                strategy=str(d.get("strategy") or ""),
                inputs=(str(inputs[0]), str(inputs[1])),
                evidence=str(d.get("evidence") or ""),
                confidence=str(d.get("confidence") or ""),
                reversible=bool(d.get("reversible", True)),
            )
        entities: list[EntityRecord] = []
        for e in raw.get("entities") or []:
            entities.append(
                EntityRecord(
                    entity_id=str(e["entity_id"]),
                    canonical_name=str(e.get("canonical_name") or ""),
                    entity_type=str(e.get("entity_type") or "OTHER"),
                    aliases=[str(a) for a in e.get("aliases") or []],
                    mentions=[Mention(**m) for m in e.get("mentions") or []],
                    decisions=[str(d) for d in e.get("decisions") or []],
                )
            )
        return cls(
            entities=entities,
            decisions=decisions,
            warnings=[str(w) for w in raw.get("warnings") or []],
        )

    def save(self, path: Path | str) -> None:
        """Serialize to JSON. Invariants are verified on every save (spec §3.2)."""
        self.validate()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            f.write("\n")

    @classmethod
    def load(cls, path: Path | str) -> "Registry":
        with open(path, encoding="utf-8") as f:
            registry = cls.from_dict(json.load(f))
        registry.validate()
        return registry
