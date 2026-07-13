from dataclasses import dataclass, field
from typing import Literal

ENTITY_TYPE = Literal["PERSON", "PLACE", "ORG", "EVENT", "OTHER"]
IMPORTANCE = Literal["principal", "secondary", "figurant", "ignored"]
TEMPORAL = Literal["present", "flashback", "unknown"]


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
    mention_spans_by_chapter: dict = field(default_factory=dict)


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
    singles_resolved: list[SplitSingle] = field(default_factory=list)
    PERSON: list[SplitCluster] = field(default_factory=list)
    PLACE: list[SplitCluster] = field(default_factory=list)
    ORG: list[SplitCluster] = field(default_factory=list)
    EVENT: list[SplitCluster] = field(default_factory=list)
    OTHER: list[SplitCluster] = field(default_factory=list)
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
