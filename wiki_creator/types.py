from dataclasses import dataclass, field
from typing import Final, Literal

# STU-505: base.yaml#entity_types is the single authority for the vocabulary, so
# ENTITY_TYPE is a plain `str` (any declared type is a valid value at runtime).
# FROZEN_ENTITY_TYPES is a static snapshot kept for reference and drift
# detection; _assert_taxonomy_in_sync() checks it against base.yaml at import.
ENTITY_TYPE = str
FROZEN_ENTITY_TYPE = Literal[
    "PERSON", "PLACE", "ORG", "EVENT", "FACTION", "OTHER", "SYNOPSIS", "COLLATION"
]
FROZEN_ENTITY_TYPES: Final[tuple[str, ...]] = (
    "PERSON", "PLACE", "ORG", "EVENT", "FACTION", "OTHER", "SYNOPSIS", "COLLATION",
)


def _assert_taxonomy_in_sync() -> None:
    """Fail fast if the frozen snapshot drifts from base.yaml#entity_types."""
    from wiki_creator.entity_taxonomy import declared_types

    declared = set(declared_types())
    if declared != set(FROZEN_ENTITY_TYPES):
        raise ValueError(
            "types.FROZEN_ENTITY_TYPES is out of sync with base.yaml#entity_types: "
            f"declared={sorted(declared)} frozen={sorted(FROZEN_ENTITY_TYPES)}"
        )


_assert_taxonomy_in_sync()

IMPORTANCE = Literal["principal", "secondary", "figurant", "ignored"]
TEMPORAL = Literal["present", "flashback", "mixed", "unknown"]


@dataclass
class EpubChapter:
    id: str
    title: str
    content: str


@dataclass
class ParsedBook:
    title: str
    chapters: list[EpubChapter]
    author: str | None = None


@dataclass
class MentionSpan:
    surface: str
    start: int
    end: int


@dataclass
class EntityFull:
    type: ENTITY_TYPE
    raw_mentions: list[str]
    first_seen: str
    mention_count: int
    mentions_by_chapter: dict = field(default_factory=dict)
    mention_spans_by_chapter: dict[str, list[MentionSpan]] = field(default_factory=dict)


@dataclass
class SplitSingle:
    canonical_name: str
    type: ENTITY_TYPE
    aliases: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    relevant: bool = True


@dataclass
class SplitCluster:
    type: ENTITY_TYPE
    canonical_candidate: str
    entity_ids: list[str] = field(default_factory=list)
    all_mentions: list[str] = field(default_factory=list)
    entity_count: int = 0
    cluster_id: str = ""
    first_seen: str = ""
    total_mentions: int = 0


@dataclass
class Splits:
    # STU-505: per-type multi-clusters live under `by_type`, keyed by entity
    # type, so a new resolution type needs no field here — the key set follows
    # base.yaml#entity_types (entity_taxonomy.resolution_types()).
    singles_resolved: list[SplitSingle] = field(default_factory=list)
    by_type: dict[str, list[SplitCluster]] = field(default_factory=dict)
    stats: dict = field(default_factory=dict)
    pov_detection: dict | None = None


@dataclass
class ClassifiedEntity:
    canonical_name: str
    type: ENTITY_TYPE
    total_mentions: int
    chapters_present: int
    importance: IMPORTANCE
    source_ids: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    relevant: bool = True
    # STU-285 provenance: alias_resolution._merge_entities stamps this block
    # ({merged_from, evidence, confidence, method}) onto merged PERSON entities.
    # Registry.from_artifacts reads it for audit trail, so it must survive the
    # entities_classified.json round-trip — never stripped. Absent on unmerged
    # entities.
    alias_resolution: dict | None = None


@dataclass
class Relationship:
    entity_a: str
    entity_b: str
    cooccurrence_count: int
    chapters: list[str] = field(default_factory=list)
    sample_contexts: list[str] = field(default_factory=list)
    relationship_type: str | None = None
    direction: str | None = None
    evolution: str | None = None
    evidence: str | None = None
    confidence: str | None = None
    key_moments: list[str] = field(default_factory=list)


@dataclass
class ClassifiedBundle:
    entities: list[ClassifiedEntity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    narrator: str | None = None


@dataclass
class RelationshipBundle:
    # entities is pass-through from relationship-extraction, which runs before
    # entity-classification — it does NOT carry importance/total_mentions/
    # chapters_present yet, so it can't be ClassifiedEntity. It's the resolved
    # entity shape from resolve_clusters.cluster_to_entity → SplitSingle.
    entities: list[SplitSingle] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    narrator: str | None = None


@dataclass
class ChapterSummary:
    chapter_id: str
    chapter_title: str
    summary_bullets: list[str] = field(default_factory=list)
    summary_method: str = ""
    quality_flags: list[str] = field(default_factory=list)
    temporal_context: TEMPORAL = "present"
    flashback_anchor: str | None = None
    pov: str = "unknown"
    pov_confidence: str = "unknown"
    pov_character: str | None = None
    pov_character_confidence: str = "low"
    pov_character_source: str = "none"


@dataclass
class WikiPage:
    title: str
    importance: str
    entity_type: str
    books: list[str] = field(default_factory=list)
    infobox_fields: dict = field(default_factory=dict)
    content: str = ""
    _failed: bool | None = None
    _insufficient_data: bool | None = None
    # STU-447: _force_correct_identity/_recover_identity_rejected_page and the
    # forbidden-names retry in generate_wiki_pages.py stamp these telemetry
    # flags directly onto real page dicts before they're persisted.
    _identity_corrected: bool | None = None
    _spoiler_rejected: bool | None = None
    # _execute_wiki_page_item's success return spreads {**page, "run_metadata": ...}
    # for every non-PERSON entity (PERSON pages are built fresh, section by
    # section, and never carry this key). Free-form: shape is producer telemetry.
    run_metadata: dict | None = None
    # Per-section revelation provenance (STU-491/492/493): generate_wiki_pages.py
    # stamps these onto pages after generation; wiki_export/spoiler_blocks consume
    # them to gate spoiler sections. Free-form lists, absent on stub/failed pages.
    content_units: list | None = None
    relation_units: list | None = None
    relationship_index: list | None = None


@dataclass
class Event:
    chapter: int
    description: str
    event_id: str
    participants: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    outcome: str | None = None
    salience: float = 0.0
    source_bullets: list[str] = field(default_factory=list)


@dataclass
class EventBundle:
    events: list[Event] = field(default_factory=list)
