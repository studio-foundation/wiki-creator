from dataclasses import dataclass, field
from typing import Literal


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
class ExtractedEntity:
    name: str
    type: Literal["PERSON", "PLACE", "ORG", "EVENT", "OTHER"]
    mentions: int
    context: list[str] = field(default_factory=list)


@dataclass
class ResolvedEntity(ExtractedEntity):
    canonical_name: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass
class WikiPageDraft:
    title: str
    content: str
    entity: ResolvedEntity


@dataclass
class EntityRegistryEntry:
    raw_mentions: list[str]
    type: Literal["PERSON", "PLACE", "ORG", "EVENT", "OTHER"]
    first_seen: str
    mentions_by_chapter: dict[str, list[str]]


@dataclass
class EntityRegistry:
    entities: dict[str, EntityRegistryEntry]
