import json
import pathlib
import subprocess
import sys

from wiki_creator.types import EntityRegistryEntry, EntityRegistry, ExtractedRelationship


def test_studio_mode_missing_entities():
    """Studio mode with empty previous_outputs returns error JSON, exit 1."""
    project_root = pathlib.Path(__file__).parent.parent
    payload = json.dumps({"previous_outputs": {}, "additional_context": ""})
    result = subprocess.run(
        [sys.executable, "scripts/relationship_extraction.py"],
        input=payload,
        capture_output=True,
        text=True,
        cwd=str(project_root),
    )
    assert result.returncode == 1
    out = json.loads(result.stdout)
    assert "error" in out


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


def test_extracted_relationship_has_evidence_field():
    r = ExtractedRelationship(entity_a="A", entity_b="B", cooccurrence_count=1)
    assert r.evidence is None
