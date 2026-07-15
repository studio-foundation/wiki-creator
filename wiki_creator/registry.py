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
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wiki_creator.naming import NamingPolicy

from wiki_creator.entity_taxonomy import resolution_types

REGISTRY_VERSION = 1


@dataclass(frozen=True)
class Mention:
    surface: str
    chapter_id: str
    source: str = "ner"  # "ner" | "coref" | "pattern"
    # Character offsets into the chapter content (the text saved to
    # chapters.json), persisted by extraction since STU-489
    # (mention_spans_by_chapter in *_full.json). None on artifacts predating
    # that field, and raw_label stays None until extraction feeds the
    # registry directly (pas 2+).
    start: int | None = None
    end: int | None = None
    raw_label: str | None = None
    context: str | None = None  # context sentence from *_full.json
    # Provenance par livre (STU-484): tome d'où provient la mention (slug du
    # livre, cf. book_paths_from_epub). None quand la provenance est inconnue
    # (registres antérieurs / reconstruction sans book_id).
    book_id: str | None = None

    def window(self, chapter_text: str, radius: int = 200) -> str | None:
        """Context window of ±``radius`` characters centered on the mention,
        sliced from the chapter text the offsets index into (chapters.json
        content). The precise window the embedding strategies need (STU-489):
        unlike ``context`` (sentence ±1), it stays anchored on the mention.
        None when offsets were not persisted (pre-STU-489 artifacts)."""
        if self.start is None or self.end is None:
            return None
        text = str(chapter_text)
        return text[max(0, self.start - radius) : min(len(text), self.end + radius)]


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
    # Provenance par livre (STU-484): tomes où l'entité apparaît, dans l'ordre de
    # première apparition. Aligné sur les nœuds/arêtes du graphe série (liste
    # `books`). Vide quand la provenance est inconnue. ``first_book`` = books[0].
    books: list[str] = field(default_factory=list)
    first_book: str | None = None


def normalize_name(text: str) -> str:
    """Canonical name normalization for tolerant identity matching (STU-450).

    The single source of truth: grounding, clustering and page-validation all
    route here, so a name that matches in one module matches in every other.
    Casefold (aggressive caseless folding) + strip accents (NFKD) + trim.
    NOT for display, NOT for ids — use entity_slug for stable slugs.
    """
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.casefold().strip()


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

    def bind_identity(self, entity: dict) -> bool:
        """Rewrite ``entity['canonical_name']`` and ``entity['aliases']`` to the
        registry's authoritative record (looked up by the entity's current
        canonical_name / any surface it already carries).

        Downstream single-source-of-truth binding (spec §3.5 pas 4): preparation
        and generation consult the registry instead of trusting the identity
        re-derived through intermediate artifacts. ``aliases`` excludes the
        canonical_name (invariant 3 keeps it inside ``record.aliases``, but the
        batch convention lists only the *other* surfaces). Returns True when a
        record was found and applied, False otherwise (caller keeps prior fields).
        """
        record = self.lookup(str(entity.get("canonical_name", "")))
        if record is None:
            return False
        entity["canonical_name"] = record.canonical_name
        entity["aliases"] = [a for a in record.aliases if a != record.canonical_name]
        # Provenance par livre (STU-486): expose the registry's book tracking
        # so generation can render per-tome categories / an appearance line.
        entity["books"] = list(record.books)
        entity["first_book"] = record.first_book
        return True

    def audit_log(self) -> list[MergeDecision]:
        return sorted(self.decisions.values(), key=lambda d: d.decision_id)

    def seed_table(self) -> dict[str, "EntityRecord"]:
        """normalize_name(alias) → owning record — the seeding view (STU-485).

        Book-N resolution (clustering / alias-resolution) starts from the
        entities already known to the series instead of re-deriving identity
        from scratch. Normalization is the tolerant STU-450 matching (casefold
        + accents stripped); on the rare post-normalization collision between
        two records the first record in registry order wins (deterministic).
        """
        table: dict[str, EntityRecord] = {}
        for record in self.entities:
            for alias in record.aliases:
                table.setdefault(normalize_name(alias), record)
        return table

    def accumulate(self, book: "Registry", *, later_tome_overrides: bool = False) -> dict:
        """Fold a per-book registry into this series registry (STU-485).

        The series-accumulation counterpart of ``CharacterGraph.merge_book``:
        ``self`` is the series registry (tomes 1..N-1), ``book`` the registry
        written for tome N. ``later_tome_overrides`` is the series canon's
        ``cross_tome`` policy (STU-512): when set, tome N's ``entity_type`` wins
        a cross-tome disagreement instead of the earlier tome's. Guarantees:

        * entity_id **stability** — a book entity whose aliases match an
          existing series entity (normalize_name comparison, STU-450) keeps the
          series ``entity_id``; nothing existing is overwritten (canonical name
          always wins for the series record, entity_type per the cross-tome
          policy; mismatches warn either way);
        * **new** entities are added; on entity_id collision with an unrelated
          series entity the new record gets a deterministic ``_<n>`` suffix
          and its decisions are re-emitted against the new id;
        * aliases / mentions / ``books`` provenance are **unioned**; mentions
          carrying one of the incoming ``book_id`` are replaced (re-running a
          tome replaces its contribution instead of duplicating it);
        * every alias newly attached to an existing record is justified by a
          ``MergeDecision(strategy="series_accumulation")`` — invariants hold
          (``validate()`` passes after every accumulation).

        Returns the per-book accumulation delta (the ``book_graph_delta``
        counterpart): matched/added entities, aliases added, decision ids
        emitted and warnings. Accumulating the same book registry twice is
        idempotent.
        """
        delta: dict = {
            "book_ids": [],
            "matched": [],
            "added": [],
            "aliases_added": {},
            "decisions_added": [],
            "warnings": [],
        }

        incoming_books: list[str] = []
        for record in book.entities:
            for b in record.books:
                if b not in incoming_books:
                    incoming_books.append(b)
            for mention in record.mentions:
                if mention.book_id and mention.book_id not in incoming_books:
                    incoming_books.append(mention.book_id)
        delta["book_ids"] = list(incoming_books)

        def _warn(message: str) -> None:
            delta["warnings"].append(message)
            if message not in self.warnings:
                self.warnings.append(message)

        # Invariant-1 ownership is casefold; identity matching is the more
        # tolerant normalize_name (casefold ⊂ normalize, so a casefold
        # collision always surfaces as a normalized match first).
        by_normalized: dict[str, EntityRecord] = self.seed_table()
        owners_casefold: dict[str, EntityRecord] = {
            alias.casefold(): record
            for record in self.entities
            for alias in record.aliases
        }
        order = {id(record): i for i, record in enumerate(self.entities)}
        used_entity_ids = {record.entity_id for record in self.entities}

        for incoming in book.entities:
            matches: list[EntityRecord] = []
            overlap: dict[int, int] = {}
            for alias in incoming.aliases:
                found = by_normalized.get(normalize_name(alias))
                if found is None:
                    continue
                if found not in matches:
                    matches.append(found)
                overlap[id(found)] = overlap.get(id(found), 0) + 1

            if matches:
                canonical_owner = by_normalized.get(normalize_name(incoming.canonical_name))
                if canonical_owner is not None:
                    target = canonical_owner
                else:
                    target = min(matches, key=lambda r: (-overlap[id(r)], order[id(r)]))
                if len(matches) > 1:
                    others = ", ".join(
                        f"'{r.entity_id}'" for r in matches if r is not target
                    )
                    _warn(
                        f"series accumulation: '{incoming.entity_id}' also overlaps "
                        f"{others}; folded into '{target.entity_id}'"
                    )
                self._accumulate_into(
                    target, incoming, incoming_books, by_normalized,
                    owners_casefold, delta, _warn, later_tome_overrides,
                )
                delta["matched"].append(
                    {"book_entity_id": incoming.entity_id, "series_entity_id": target.entity_id}
                )
                continue

            # New entity — keep the id when free, else deterministic suffix.
            entity_id = incoming.entity_id
            counter = 1
            while entity_id in used_entity_ids:
                counter += 1
                entity_id = f"{incoming.entity_id}_{counter}"
            used_entity_ids.add(entity_id)

            decision_ids: list[str] = []
            for d_id in incoming.decisions:
                decision = book.decisions.get(d_id)
                if decision is None:
                    continue
                if entity_id != incoming.entity_id:
                    inputs = (entity_id, decision.inputs[1])
                    new_id = _decision_id(decision.strategy, inputs, decision.evidence)
                    decision = MergeDecision(
                        decision_id=new_id,
                        strategy=decision.strategy,
                        inputs=inputs,
                        evidence=decision.evidence,
                        confidence=decision.confidence,
                        reversible=decision.reversible,
                    )
                if decision.decision_id not in self.decisions:
                    delta["decisions_added"].append(decision.decision_id)
                self.decisions[decision.decision_id] = decision
                decision_ids.append(decision.decision_id)

            record = EntityRecord(
                entity_id=entity_id,
                canonical_name=incoming.canonical_name,
                entity_type=incoming.entity_type,
                aliases=list(incoming.aliases),
                mentions=list(incoming.mentions),
                decisions=decision_ids,
                books=list(incoming.books),
                first_book=incoming.first_book,
            )
            self.entities.append(record)
            order[id(record)] = len(self.entities) - 1
            for alias in record.aliases:
                by_normalized.setdefault(normalize_name(alias), record)
                owners_casefold[alias.casefold()] = record
            delta["added"].append(
                {"book_entity_id": incoming.entity_id, "series_entity_id": entity_id}
            )

        return delta

    def _accumulate_into(
        self,
        target: EntityRecord,
        incoming: EntityRecord,
        incoming_books: list[str],
        by_normalized: dict[str, "EntityRecord"],
        owners_casefold: dict[str, "EntityRecord"],
        delta: dict,
        warn: Callable[[str], None],
        later_tome_overrides: bool = False,
    ) -> None:
        """Union one matched book record into its series record (accumulate helper)."""
        book_label = ", ".join(incoming.books) or "unknown book"
        if incoming.entity_type != target.entity_type:
            if later_tome_overrides:
                warn(
                    f"series accumulation: entity_type of '{target.entity_id}' overridden "
                    f"to '{incoming.entity_type}' by book '{book_label}' "
                    f"(was '{target.entity_type}')"
                )
                target.entity_type = incoming.entity_type
            else:
                warn(
                    f"series accumulation: kept entity_type '{target.entity_type}' for "
                    f"'{target.entity_id}' (book '{book_label}' says '{incoming.entity_type}')"
                )

        added_aliases: list[str] = []
        existing = {alias.casefold() for alias in target.aliases}
        for alias in incoming.aliases:
            if alias.casefold() in existing:
                continue
            owner = owners_casefold.get(alias.casefold())
            if owner is not None and owner is not target:
                warn(
                    f"series accumulation: alias '{alias}' of '{incoming.entity_id}' "
                    f"already belongs to '{owner.entity_id}'; not moved to "
                    f"'{target.entity_id}'"
                )
                continue
            target.aliases.append(alias)
            existing.add(alias.casefold())
            owners_casefold[alias.casefold()] = target
            by_normalized.setdefault(normalize_name(alias), target)
            added_aliases.append(alias)

            evidence = (
                f"series accumulation from book '{book_label}': alias '{alias}' of "
                f"'{incoming.canonical_name}' unified under '{target.canonical_name}'"
            )
            d_id = _decision_id(
                "series_accumulation", (target.entity_id, entity_slug(alias)), evidence
            )
            if d_id not in self.decisions:
                delta["decisions_added"].append(d_id)
            self.decisions[d_id] = MergeDecision(
                decision_id=d_id,
                strategy="series_accumulation",
                inputs=(target.entity_id, entity_slug(alias)),
                evidence=evidence,
                confidence="high",
            )
            if d_id not in target.decisions:
                target.decisions.append(d_id)
        target.aliases.sort(key=lambda a: (a.casefold(), a))
        if added_aliases:
            delta["aliases_added"][target.entity_id] = added_aliases

        # Re-running a tome replaces its mentions instead of duplicating them.
        target.mentions = [
            m for m in target.mentions if m.book_id not in incoming_books
        ] + list(incoming.mentions)

        for b in incoming.books:
            if b not in target.books:
                target.books.append(b)
        if target.first_book is None:
            target.first_book = incoming.first_book

    def validate(self) -> None:
        seen_ids: set[str] = set()
        # Ownership is keyed by (casefold alias, entity_type): invariant 1 is
        # "an alias belongs to exactly one entity OF A GIVEN TYPE" (STU-506).
        # Two different-type homonyms (a PERSON and a PLACE both named "X") are
        # accepted by policy — they coexist, disambiguated at the title layer,
        # instead of being silently merged into one false entity.
        owners: dict[tuple[str, str], str] = {}
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
                key = (alias.casefold(), record.entity_type)
                owner = owners.get(key)
                if owner is not None and owner != record.entity_id:
                    raise ValueError(
                        f"invariant 1 violated: alias '{alias}' ({record.entity_type}) "
                        f"belongs to both '{owner}' and '{record.entity_id}'"
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
                    "books": list(r.books),
                    "first_book": r.first_book,
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
            books = [str(b) for b in e.get("books") or []]
            first_book = e.get("first_book")
            entities.append(
                EntityRecord(
                    entity_id=str(e["entity_id"]),
                    canonical_name=str(e.get("canonical_name") or ""),
                    entity_type=str(e.get("entity_type") or "OTHER"),
                    aliases=[str(a) for a in e.get("aliases") or []],
                    mentions=[Mention(**m) for m in e.get("mentions") or []],
                    decisions=[str(d) for d in e.get("decisions") or []],
                    books=books,
                    first_book=str(first_book) if first_book else None,
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
    def load_from_processing(cls, processing_dir: Path | str) -> "Registry | None":
        """Load ``<processing_dir>/registry.json`` for downstream consumers, or
        None when it is absent/unreadable (graceful degradation — the strangler
        migration must not harden a hard dependency on the registry before it is
        universally present, spec §3.5 pas 4)."""
        path = Path(processing_dir) / "registry.json"
        if not path.exists():
            return None
        try:
            return cls.load(path)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @classmethod
    def load_seed_table(cls, path: Path | str) -> dict[str, "EntityRecord"]:
        """Load ``path`` (the series registry) and return its ``seed_table()``,
        or {} when the file is absent or unreadable — single-book runs and
        pre-STU-485 series degrade gracefully to unseeded resolution."""
        p = Path(path)
        if not p.exists():
            return {}
        try:
            return cls.load(p).seed_table()
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    @classmethod
    def from_artifacts(
        cls,
        splits: dict | None,
        alias_output: dict | None,
        full_registries: dict | None = None,
        book_id: str | None = None,
        policy: "NamingPolicy | None" = None,
    ) -> "Registry":
        """Rebuild the registry from existing artifacts (pas 1 — read only).

        splits: parsed splits.json (multi-entity JW clusters per type).
        alias_output: alias-resolution stage output ({"entities": [...]});
            entities_classified.json carries the same entity dicts and works too.
        full_registries: merged *_full.json registries ({"entity_001": {...}}),
            used to rebuild mentions and to break alias-collision ties.
        book_id: provenance stamp (STU-484). When set, every mention carries it
            and every record lists it in ``books`` / ``first_book``; None leaves
            the provenance fields empty (single-book, pre-multi-tome behaviour).
        policy: name-collision policy (STU-506). Defaults to the safe posture
            (different-type homonyms never merge). ``collision_policy: merge``
            or ``merge_requires_same_type: false`` restores the legacy fold.
        """
        from wiki_creator.naming import NamingPolicy

        policy = policy or NamingPolicy()
        splits = splits or {}
        full = full_registries or {}
        entities_raw = [
            e for e in (alias_output or {}).get("entities") or [] if isinstance(e, dict)
        ]

        by_type = splits.get("by_type") or {}
        jw_names = {
            str(name).casefold()
            for etype in resolution_types()
            for cluster in (by_type.get(etype) or [])
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
                    mentions=_mentions_from_full(canonical, source_ids, full, book_id),
                    decisions=decision_ids,
                    books=[book_id] if book_id else [],
                    first_book=book_id,
                )
            )

        records = _merge_duplicate_canonicals(
            records, decisions, mention_counts, warnings, policy
        )
        _resolve_alias_collisions(records, decisions, mention_counts, warnings, policy)

        referenced: set[str] = set()
        for record in records:
            referenced.update(record.decisions)
        decisions = {d_id: d for d_id, d in decisions.items() if d_id in referenced}

        return cls(entities=records, decisions=decisions, warnings=warnings)


def _mentions_from_full(
    canonical: str, source_ids: list[str], full: dict, book_id: str | None = None
) -> list[Mention]:
    """When extraction persisted offsets (mention_spans_by_chapter, STU-489):
    one Mention per occurrence, carrying surface + start/end; the preserved
    context sentences pair with the first spans of each chapter (extraction
    appends both in occurrence order, contexts capped at 3). Artifacts
    predating that field degrade to one Mention per preserved context
    sentence; surface = longest raw mention found in the sentence (offsets
    stay None)."""
    mentions: list[Mention] = []
    for sid in source_ids:
        record = full.get(sid) or {}
        surfaces = [str(m) for m in (record.get("raw_mentions") or []) if str(m).strip()]
        by_length = sorted(surfaces, key=len, reverse=True)
        by_chapter = record.get("mentions_by_chapter") or {}
        spans_by_chapter = record.get("mention_spans_by_chapter") or {}
        for chapter_id in sorted(set(by_chapter) | set(spans_by_chapter)):
            contexts = [str(s) for s in (by_chapter.get(chapter_id) or [])]
            spans = [
                s for s in (spans_by_chapter.get(chapter_id) or []) if isinstance(s, dict)
            ]
            if spans:
                for i, span in enumerate(spans):
                    start, end = span.get("start"), span.get("end")
                    mentions.append(
                        Mention(
                            surface=str(span.get("surface") or "").strip()
                            or (surfaces[0] if surfaces else canonical),
                            chapter_id=str(chapter_id),
                            source="ner",
                            start=int(start) if isinstance(start, int) else None,
                            end=int(end) if isinstance(end, int) else None,
                            context=contexts[i] if i < len(contexts) else None,
                            book_id=book_id,
                        )
                    )
                continue
            for text in contexts:
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
                        book_id=book_id,
                    )
                )
    return mentions


def _merge_duplicate_canonicals(
    records: list[EntityRecord],
    decisions: dict[str, MergeDecision],
    mention_counts: dict[str, int],
    warnings: list[str],
    policy: "NamingPolicy",
) -> list[EntityRecord]:
    """Artifacts occasionally carry two entities with the same canonical name;
    fold the later into the first so invariant 1 can hold (deterministic).

    The merge key is ``(canonical, entity_type)`` under the STU-506 default:
    a PERSON and a PLACE homonym coexist instead of collapsing into one false
    entity. ``collision_policy: merge`` (or ``merge_requires_same_type: false``)
    keys on the name alone (legacy fold); ``collision_policy: fail`` raises the
    moment two different-type homonyms are seen."""
    by_canonical: dict[object, EntityRecord] = {}
    first_by_name: dict[str, EntityRecord] = {}
    kept: list[EntityRecord] = []
    for record in records:
        name_key = record.canonical_name.casefold()
        key: object = name_key if policy.merges_cross_type else (name_key, record.entity_type)

        homonym = first_by_name.get(name_key)
        if homonym is not None and homonym.entity_type != record.entity_type and not policy.merges_cross_type:
            if policy.fails_on_collision:
                raise ValueError(
                    f"name collision: '{record.canonical_name}' is both "
                    f"{homonym.entity_type} ('{homonym.entity_id}') and "
                    f"{record.entity_type} ('{record.entity_id}') "
                    "(naming.collision_policy: fail)"
                )
            warnings.append(
                f"name collision: '{record.canonical_name}' kept as distinct "
                f"{homonym.entity_type} ('{homonym.entity_id}') and "
                f"{record.entity_type} ('{record.entity_id}')"
            )

        first = by_canonical.get(key)
        if first is None:
            by_canonical[key] = record
            first_by_name.setdefault(name_key, record)
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
        for book in record.books:
            if book not in first.books:
                first.books.append(book)
        if first.first_book is None:
            first.first_book = record.first_book
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


def _arbitrate(
    claimants: list[EntityRecord],
    alias_cf: str,
    order: tuple[str, ...],
    mention_counts: dict[str, int],
) -> EntityRecord:
    """Pick the entity that keeps a contested alias, applying the
    ``alias_arbitration`` criteria in priority order (STU-506). ``claimants`` is
    in artifact order, so ``first_seen`` is a no-op tie-break; stable sorts
    applied from lowest to highest priority leave the winner first."""
    ranked = list(claimants)
    for criterion in reversed(order):
        if criterion == "canonical_owner":
            ranked.sort(key=lambda r: r.canonical_name.casefold() != alias_cf)
        elif criterion == "mention_count":
            ranked.sort(key=lambda r: -mention_counts.get(r.entity_id, 0))
        # "first_seen" == artifact order, already the incoming order
    return ranked[0]


def _resolve_alias_collisions(
    records: list[EntityRecord],
    decisions: dict[str, MergeDecision],
    mention_counts: dict[str, int],
    warnings: list[str],
    policy: "NamingPolicy",
) -> None:
    """Invariant 1 pre-pass: within a single entity_type, an alias claimed by
    several entities stays with the arbitration winner (canonical owner, then
    mention_count, then artifact order — configurable via alias_arbitration).
    Cross-type claimants are left alone: a shared surface across types is a
    legitimate homonym (STU-506), resolved at the title layer, not here."""
    claims: dict[tuple[str, str], list[EntityRecord]] = {}
    for record in records:
        for alias in record.aliases:
            bucket = claims.setdefault((alias.casefold(), record.entity_type), [])
            if not bucket or bucket[-1] is not record:
                bucket.append(record)

    for (alias_cf, _etype), claimants in claims.items():
        if len(claimants) < 2:
            continue
        winner = _arbitrate(claimants, alias_cf, policy.alias_arbitration, mention_counts)
        for loser in claimants:
            if loser is winner:
                continue
            dropped = [a for a in loser.aliases if a.casefold() == alias_cf]
            loser.aliases = [a for a in loser.aliases if a.casefold() != alias_cf]
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
