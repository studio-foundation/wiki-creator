from wiki_creator.types import EntityRegistryEntry, EntityRegistry


def test_entity_registry_entry_has_required_fields():
    entry = EntityRegistryEntry(
        raw_mentions=["Alice"],
        type="PERSON",
        first_seen="ch01",
        mentions_by_chapter={"ch01": ["Alice walked into the room."]},
    )
    assert entry.raw_mentions == ["Alice"]
    assert entry.first_seen == "ch01"
    assert "ch01" in entry.mentions_by_chapter


def test_entity_registry_wraps_entries():
    entry = EntityRegistryEntry(raw_mentions=["Alice"], type="PERSON", first_seen="ch01", mentions_by_chapter={})
    registry = EntityRegistry(entities={"entity_001": entry})
    assert "entity_001" in registry.entities
