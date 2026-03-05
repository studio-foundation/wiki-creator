from wiki_creator.types import EntityRegistryEntry, EntityRegistry, ExtractedRelationship


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


def test_extracted_relationship_fields():
    rel = ExtractedRelationship(
        entity_a="David Martín",
        entity_b="Pedro Vidal",
        cooccurrence_count=45,
        chapters=["ch01", "ch03"],
        sample_contexts=["Vidal tendit le manuscrit à Martín..."],
    )
    assert rel.entity_a == "David Martín"
    assert rel.cooccurrence_count == 45
    assert rel.relationship_type is None
    assert rel.direction is None
    assert rel.evolution is None
    assert rel.key_moments == []
    assert rel.entity_b == "Pedro Vidal"
    assert rel.chapters == ["ch01", "ch03"]
    assert rel.sample_contexts == ["Vidal tendit le manuscrit à Martín..."]
