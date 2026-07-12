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
                justified.add(decision.inputs[1])
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

    @classmethod
    def from_artifacts(
        cls,
        splits: dict | None,
        alias_output: dict | None,
        full_registries: dict | None = None,
    ) -> "Registry":
        """Rebuild the registry from existing artifacts (pas 1 — read only).

        splits: parsed splits.json (multi-entity JW clusters per type).
        alias_output: alias-resolution stage output ({"entities": [...]});
            entities_classified.json carries the same entity dicts and works too.
        full_registries: merged *_full.json registries ({"entity_001": {...}}),
            used to rebuild mentions and to break alias-collision ties.
        """
        splits = splits or {}
        full = full_registries or {}
        entities_raw = [
            e for e in (alias_output or {}).get("entities") or [] if isinstance(e, dict)
        ]

        jw_names = {
            str(name).casefold()
            for etype in ENTITY_TYPES
            for cluster in (splits.get(etype) or [])
            for name in (cluster.get("all_mentions") or [])
        }

        records: list[EntityRecord] = []
        decisions: dict[str, MergeDecision] = {}
        warnings: list[str] = []
        mention_counts: dict[str, int] = {}
        used_slugs: dict[str, int] = {}
        used_entity_ids: set[str] = set()

        for raw in entities_raw:
            canonical = str(raw.get("canonical_name") or "").strip()
            if not canonical:
                warnings.append("skipped entity without canonical_name")
                continue

            slug = entity_slug(canonical)
            used_slugs[slug] = used_slugs.get(slug, 0) + 1
            counter = used_slugs[slug]
            entity_id = slug if counter == 1 else f"{slug}_{counter}"
            while entity_id in used_entity_ids:
                counter += 1
                used_slugs[slug] = counter
                entity_id = f"{slug}_{counter}"
            used_entity_ids.add(entity_id)

            aliases = sorted(
                {str(a) for a in (raw.get("aliases") or []) if str(a).strip()}
                | {canonical},
                key=lambda a: (a.casefold(), a),
            )
            source_ids = [str(s) for s in (raw.get("source_ids") or [])]

            recorded = raw.get("alias_resolution") or {}
            merged_from = {str(m).casefold() for m in (recorded.get("merged_from") or [])}
            method = str(recorded.get("method") or "unknown")
            method_confidence = str(recorded.get("confidence") or "medium")
            snippets = "; ".join(
                s
                for s in (
                    str(e.get("snippet") or "")
                    for e in (recorded.get("evidence") or [])
                    if isinstance(e, dict)
                )
                if s
            )

            decision_ids: list[str] = []
            for alias in aliases:
                if alias == canonical:
                    continue
                alias_slug = entity_slug(alias)
                if alias.casefold() in merged_from:
                    strategy, conf = method, method_confidence
                    evidence = snippets or (
                        f"alias-resolution merge of '{alias}' into '{canonical}'"
                    )
                elif alias.casefold() in jw_names:
                    strategy, conf = "cluster_jw", "medium"
                    evidence = (
                        f"reconstructed (pas 1) from splits cluster: "
                        f"'{alias}' co-clustered with '{canonical}'"
                    )
                else:
                    strategy, conf = "extraction_grouping", "medium"
                    evidence = (
                        f"reconstructed (pas 1) from extraction surface variants: "
                        f"'{alias}' grouped under '{canonical}'"
                    )
                d_id = _decision_id(strategy, (entity_id, alias_slug), evidence)
                decisions[d_id] = MergeDecision(
                    decision_id=d_id,
                    strategy=strategy,
                    inputs=(entity_id, alias_slug),
                    evidence=evidence,
                    confidence=conf,
                )
                if d_id not in decision_ids:
                    decision_ids.append(d_id)

            mention_counts[entity_id] = sum(
                int((full.get(sid) or {}).get("mention_count") or 0) for sid in source_ids
            )
            records.append(
                EntityRecord(
                    entity_id=entity_id,
                    canonical_name=canonical,
                    entity_type=str(raw.get("type") or "OTHER"),
                    aliases=aliases,
                    mentions=_mentions_from_full(canonical, source_ids, full),
                    decisions=decision_ids,
                )
            )

        records = _merge_duplicate_canonicals(records, decisions, mention_counts, warnings)
        _resolve_alias_collisions(records, decisions, mention_counts, warnings)

        referenced: set[str] = set()
        for record in records:
            referenced.update(record.decisions)
        decisions = {d_id: d for d_id, d in decisions.items() if d_id in referenced}

        return cls(entities=records, decisions=decisions, warnings=warnings)


def _mentions_from_full(
    canonical: str, source_ids: list[str], full: dict
) -> list[Mention]:
    """One Mention per preserved context sentence; surface = longest raw
    mention found in the sentence (offsets/raw labels were never persisted)."""
    mentions: list[Mention] = []
    for sid in source_ids:
        record = full.get(sid) or {}
        surfaces = [str(m) for m in (record.get("raw_mentions") or []) if str(m).strip()]
        by_length = sorted(surfaces, key=len, reverse=True)
        by_chapter = record.get("mentions_by_chapter") or {}
        for chapter_id in sorted(by_chapter):
            for sentence in by_chapter[chapter_id] or []:
                text = str(sentence)
                surface = next(
                    (s for s in by_length if s in text),
                    surfaces[0] if surfaces else canonical,
                )
                mentions.append(
                    Mention(
                        surface=surface,
                        chapter_id=str(chapter_id),
                        source="ner",
                        context=text,
                    )
                )
    return mentions


def _merge_duplicate_canonicals(
    records: list[EntityRecord],
    decisions: dict[str, MergeDecision],
    mention_counts: dict[str, int],
    warnings: list[str],
) -> list[EntityRecord]:
    """Artifacts occasionally carry two entities with the same canonical name;
    fold the later into the first so invariant 1 can hold (deterministic)."""
    by_canonical: dict[str, EntityRecord] = {}
    kept: list[EntityRecord] = []
    for record in records:
        key = record.canonical_name.casefold()
        first = by_canonical.get(key)
        if first is None:
            by_canonical[key] = record
            kept.append(record)
            continue
        warnings.append(
            f"duplicate canonical_name '{record.canonical_name}': "
            f"merged '{record.entity_id}' into '{first.entity_id}'"
        )
        for alias in record.aliases:
            if alias not in first.aliases:
                first.aliases.append(alias)
        first.aliases.sort(key=lambda a: (a.casefold(), a))
        first.mentions.extend(record.mentions)
        for d_id in record.decisions:
            if d_id not in first.decisions:
                first.decisions.append(d_id)
        mention_counts[first.entity_id] = mention_counts.get(
            first.entity_id, 0
        ) + mention_counts.get(record.entity_id, 0)
        if record.canonical_name != first.canonical_name:
            alias_slug = entity_slug(record.canonical_name)
            evidence = (
                f"reconstructed (pas 1): duplicate canonical "
                f"'{record.canonical_name}' folded into '{first.canonical_name}'"
            )
            d_id = _decision_id(
                "extraction_grouping", (first.entity_id, alias_slug), evidence
            )
            decisions[d_id] = MergeDecision(
                decision_id=d_id,
                strategy="extraction_grouping",
                inputs=(first.entity_id, alias_slug),
                evidence=evidence,
                confidence="medium",
            )
            first.decisions.append(d_id)
    return kept


def _resolve_alias_collisions(
    records: list[EntityRecord],
    decisions: dict[str, MergeDecision],
    mention_counts: dict[str, int],
    warnings: list[str],
) -> None:
    """Invariant 1 pre-pass: an alias claimed by several entities stays with
    its canonical owner, else the highest mention_count, else artifact order."""
    claims: dict[str, list[EntityRecord]] = {}
    for record in records:
        for alias in record.aliases:
            bucket = claims.setdefault(alias.casefold(), [])
            if not bucket or bucket[-1] is not record:
                bucket.append(record)

    for key, claimants in claims.items():
        if len(claimants) < 2:
            continue
        canonical_owners = [
            r for r in claimants if r.canonical_name.casefold() == key
        ]
        if canonical_owners:
            winner = canonical_owners[0]  # unique after duplicate-canonical merge
        else:
            winner = max(claimants, key=lambda r: mention_counts.get(r.entity_id, 0))
        for loser in claimants:
            if loser is winner:
                continue
            dropped = [a for a in loser.aliases if a.casefold() == key]
            loser.aliases = [a for a in loser.aliases if a.casefold() != key]
            dropped_slugs = {entity_slug(a) for a in dropped}
            still_needed = {entity_slug(a) for a in loser.aliases}
            loser.decisions = [
                d_id
                for d_id in loser.decisions
                if decisions[d_id].inputs[1] not in dropped_slugs
                or decisions[d_id].inputs[1] in still_needed
            ]
            warnings.append(
                f"alias '{dropped[0]}' claimed by multiple entities: kept on "
                f"'{winner.entity_id}', dropped from '{loser.entity_id}'"
            )
