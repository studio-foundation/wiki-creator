import json
import pathlib
import subprocess
import sys

from wiki_creator.types import (
    ChapterSummary,
    ClassifiedEntity,
    Event,
    EventBundle,
    EntityFull,
    MentionSpan,
    Relationship,
    SplitCluster,
    SplitSingle,
    Splits,
)


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


def test_entity_full_construction():
    e = EntityFull(type="PERSON", raw_mentions=["Celaena"], first_seen="ch1", mention_count=3)
    assert e.mentions_by_chapter == {}
    assert e.mention_spans_by_chapter == {}


def test_mention_span_fields():
    m = MentionSpan(surface="Celaena", start=10, end=17)
    assert m.surface == "Celaena"
    assert m.end - m.start == 7


def test_split_single_defaults():
    s = SplitSingle(canonical_name="Celaena", type="PERSON")
    assert s.aliases == []
    assert s.source_ids == []
    assert s.relevant is True


def test_split_cluster_defaults():
    c = SplitCluster(type="PERSON", canonical_candidate="Celaena")
    assert c.entity_ids == []
    assert c.all_mentions == []
    assert c.entity_count == 0


def test_splits_container_defaults():
    splits = Splits()
    assert splits.singles_resolved == []
    assert splits.PERSON == []
    assert splits.pov_detection is None


def test_classified_entity_importance_literal():
    c = ClassifiedEntity(
        canonical_name="Celaena",
        type="PERSON",
        total_mentions=40,
        chapters_present=10,
        importance="principal",
    )
    assert c.importance == "principal"


def test_relationship_has_evidence_field():
    r = Relationship(entity_a="A", entity_b="B", cooccurrence_count=1)
    assert r.evidence is None
    assert r.key_moments == []


def test_chapter_summary_pov_defaults():
    cs = ChapterSummary(chapter_id="ch01", chapter_title="Chapter One")
    assert cs.temporal_context == "present"
    assert cs.pov == "unknown"
    assert cs.pov_character is None
    assert cs.pov_character_source == "none"


def test_event_and_bundle_construction():
    ev = Event(chapter=1, description="Celaena escapes", event_id="e_ch1_0")
    bundle = EventBundle(events=[ev])
    assert bundle.events[0].event_id == "e_ch1_0"
    assert bundle.events[0].participants == []
