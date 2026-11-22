import json
import subprocess
import sys
from pathlib import Path
import pytest

import scripts.classify_relationships as clf
from scripts.classify_relationships import (
    _batched,
    _BATCH_SIZE,
    _entity_role_contexts,
    _merge_classification,
    _save,
    _select_input,
)
from wiki_creator import studio_io
from wiki_creator.registry import EntityRecord, Mention, Registry
from wiki_creator.types import RelationshipBundle


def test_select_input_prefers_discovered(tmp_path):
    """STU-556: the schema-discovered typed graph wins over co-occurrence."""
    (tmp_path / "relationships.json").write_text("{}")
    (tmp_path / "relationships_discovered.json").write_text("{}")
    path, pre_typed = _select_input(tmp_path)
    assert path.name == "relationships_discovered.json"
    assert pre_typed is True


def test_select_input_falls_back_to_cooccurrence(tmp_path):
    """No discovery artifact → the deterministic co-occurrence graph, untyped."""
    (tmp_path / "relationships.json").write_text("{}")
    path, pre_typed = _select_input(tmp_path)
    assert path.name == "relationships.json"
    assert pre_typed is False


def test_merge_pretyped_keeps_discovery_type_and_takes_prose():
    """A discovered pair's type/direction is authoritative; the classifier only
    contributes prose — it cannot overwrite the type."""
    pair = {"entity_a": "A", "entity_b": "B", "relationship_type": "mentor",
            "direction": "A→B", "evidence": "discovered quote"}
    classification = {"relationship_type": "friend", "direction": "symmetric",
                      "evidence": "other", "evolution": "grows warmer",
                      "key_moments": ["ch1: meet"], "confidence": "inferred"}
    merged = _merge_classification(pair, classification, pre_typed=True)
    assert merged["relationship_type"] == "mentor"
    assert merged["direction"] == "A→B"
    assert merged["evidence"] == "discovered quote"
    assert merged["evolution"] == "grows warmer"
    assert merged["key_moments"] == ["ch1: meet"]


def test_merge_pretyped_ignores_classifier_confidence():
    """STU-751: a discovered pair's confidence is derived deterministically
    upstream (relationship_discovery.aggregate) and carried on the pair itself —
    even a stray classifier-supplied grade must not override it."""
    pair = {"entity_a": "A", "entity_b": "B", "relationship_type": "mentor",
            "direction": "A→B", "confidence": "explicit"}
    classification = {"evolution": "grows warmer", "key_moments": [], "confidence": "interpretation"}
    merged = _merge_classification(pair, classification, pre_typed=True)
    assert merged["confidence"] == "explicit"


def test_merge_untyped_takes_classifier_type():
    """The co-occurrence fallback pair has no type; the classifier types it (legacy)."""
    pair = {"entity_a": "A", "entity_b": "B", "relationship_type": None}
    classification = {"relationship_type": "friend", "direction": "symmetric",
                      "evolution": "grows", "key_moments": [], "confidence": "inferred"}
    merged = _merge_classification(pair, classification, pre_typed=False)
    assert merged["relationship_type"] == "friend"
    assert merged["direction"] == "symmetric"


def test_main_persists_classifier_fingerprint(tmp_path, monkeypatch):
    """STU-589: main() stamps the artifact with the config fingerprint so the next run
    can tell whether the prompt/vocabulary it would resume was produced under."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    input_bundle = RelationshipBundle(relationships=[clf.Relationship(
        entity_a="Celaena", entity_b="Chaol", cooccurrence_count=9,
        chapters=["ch01"], sample_contexts=["they spoke"],
    )])
    studio_io.save_artifact(processing / "relationships.json", input_bundle, RelationshipBundle)

    monkeypatch.setattr(sys, "argv",
                        ["classify_relationships.py", "--book", str(book_yaml), "--dry-run"])
    clf.main()

    written = json.loads((processing / "relationships_classified.json").read_text())
    assert written["stats"]["classifier_prompt"] == clf._classifier_fingerprint(
        book_config={"novel_summary": "A tale."}, novel_summary="A tale.", pre_typed=False
    )


def test_save_writes_valid_json(tmp_path):
    output = tmp_path / "out.json"
    base = {"entities": [], "stats": {}, "narrator": None}
    pairs = [{"entity_a": "A", "entity_b": "B", "cooccurrence_count": 5}]
    _save(output, base, pairs)
    written = json.loads(output.read_text())
    assert written["relationships"][0]["entity_a"] == "A"
    assert written["relationships"][0]["entity_b"] == "B"
    assert written["relationships"][0]["cooccurrence_count"] == 5
    assert written["entities"] == []


def test_stray_llm_key_does_not_crash_save(tmp_path, monkeypatch):
    """A classifier returning an extra top-level key (freeform LLM JSON) must not
    brick the incremental _save via Relationship(**r) — the stray key is dropped."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    input_bundle = RelationshipBundle(relationships=[clf.Relationship(
        entity_a="Celaena", entity_b="Chaol", cooccurrence_count=9,
        chapters=["ch01"], sample_contexts=["they spoke"],
    )])
    studio_io.save_artifact(processing / "relationships.json", input_bundle, RelationshipBundle)

    monkeypatch.setattr(clf, "_run_classify_fanout", lambda batches, fp: ({
        "total": 1, "succeeded": 1, "failed": 0, "resumed": 0,
        "results": [{"index": 0, "status": "success", "output": {"classifications": [{
            "relationship_type": "allies", "direction": "mutual", "evolution": None,
            "key_moments": [], "evidence": "they train together",
            "reasoning": "stray freeform key the LLM invented",  # not in Relationship
        }]}}],
    }, None))
    monkeypatch.setattr(sys, "argv", ["classify_relationships.py", "--book", str(book_yaml)])

    clf.main()  # must not raise

    out = studio_io.load_artifact(
        processing / "relationships_classified.json", RelationshipBundle
    )
    rel = out.relationships[0]
    assert rel.relationship_type == "allies"
    assert rel.evidence == "they train together"
    assert not hasattr(rel, "reasoning")


def test_pretyped_discovered_graph_survives_fold_end_to_end(tmp_path, monkeypatch):
    """STU-583 wiring: classify_relationships folds the discovered graph before
    classifying (registry present), and the fold must not wipe the discovered
    type. Dry-run passes the folded pair through, so the artifact pins that the
    type/direction reached the output."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    Registry(entities=[
        EntityRecord(entity_id="peter", canonical_name="Peter",
                     entity_type="PERSON", aliases=["Peter"]),
        EntityRecord(entity_id="susan", canonical_name="Susan",
                     entity_type="PERSON", aliases=["Susan"]),
    ]).save(processing / "registry.json")

    discovered = RelationshipBundle(relationships=[clf.Relationship(
        entity_a="Peter", entity_b="Susan", cooccurrence_count=3,
        chapters=["ch01"], sample_contexts=["they are siblings"],
        relationship_type="family", direction="symmetric",
    )])
    studio_io.save_artifact(
        processing / "relationships_discovered.json", discovered, RelationshipBundle
    )

    monkeypatch.setattr(
        sys, "argv",
        ["classify_relationships.py", "--book", str(book_yaml), "--dry-run"],
    )
    clf.main()

    out = studio_io.load_artifact(
        processing / "relationships_classified.json", RelationshipBundle
    )
    rel = out.relationships[0]
    assert rel.relationship_type == "family"
    assert rel.direction == "symmetric"


def test_studio_error_is_marked_in_artifact(tmp_path, monkeypatch):
    """STU-562: a pair the classifier never judged (Studio error) is stamped with
    classification_error, so it is distinguishable from a real decline (both untyped)."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    input_bundle = RelationshipBundle(relationships=[clf.Relationship(
        entity_a="Celaena", entity_b="Chaol", cooccurrence_count=9,
        chapters=["ch01"], sample_contexts=["they spoke"],
    )])
    studio_io.save_artifact(processing / "relationships.json", input_bundle, RelationshipBundle)

    monkeypatch.setattr(clf, "_run_classify_fanout", lambda items, fp: ({
        "total": 1, "succeeded": 0, "failed": 1, "resumed": 0,
        "results": [{"index": 0, "status": "failed", "error": "child run failed"}],
    }, None))
    monkeypatch.setattr(sys, "argv", ["classify_relationships.py", "--book", str(book_yaml)])

    clf.main()

    out = studio_io.load_artifact(
        processing / "relationships_classified.json", RelationshipBundle
    )
    rel = out.relationships[0]
    assert rel.relationship_type is None
    assert rel.classification_error == "child run failed"


def test_fanout_level_failure_stamps_every_pair(tmp_path, monkeypatch):
    """The whole fan-out failing (CLI missing, timeout) stamps every classifiable
    pair rather than writing nothing — downstream still gets an artifact, and a
    re-run retries them all (the engine cached no failure)."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    input_bundle = RelationshipBundle(relationships=[clf.Relationship(
        entity_a="Celaena", entity_b="Chaol", cooccurrence_count=9,
        chapters=["ch01"], sample_contexts=["they spoke"],
    )])
    studio_io.save_artifact(processing / "relationships.json", input_bundle, RelationshipBundle)

    monkeypatch.setattr(clf, "_run_classify_fanout", lambda items, fp: (None, "studio_cli_missing"))
    monkeypatch.setattr(sys, "argv", ["classify_relationships.py", "--book", str(book_yaml)])

    clf.main()

    out = studio_io.load_artifact(
        processing / "relationships_classified.json", RelationshipBundle
    )
    assert out.relationships[0].classification_error == "studio_cli_missing"


# ---------------------------------------------------------------------------
# STU-751: batching pairs per classify-relationships map item
# ---------------------------------------------------------------------------

def _item(name, contexts=1, context_chars=400):
    return {"entity_a": name, "entity_b": "X", "sample_contexts": ["c" * context_chars] * contexts,
            "role_contexts_a": [], "role_contexts_b": []}


def test_batched_caps_pairs_per_batch_under_a_large_window():
    items = [_item(f"E{i}") for i in range(8)]
    batches = _batched(items, budget=100_000)
    assert [len(b) for b in batches] == [_BATCH_SIZE, 2]


def test_batched_empty_input():
    assert _batched([], budget=1000) == []


def test_batched_small_window_never_exceeds_budget_and_keeps_every_pair():
    """STU-2021: six Alice pairs filled a 32k local window; packing is by tokens."""
    items = [_item(f"E{i}", contexts=4) for i in range(10)]
    budget = 1200
    batches = _batched(items, budget=budget)
    assert len(batches) > 2
    assert all(sum(clf._item_tokens(p) for p in b) <= budget for b in batches)
    assert [p["entity_a"] for b in batches for p in b] == [f"E{i}" for i in range(10)]


def test_batched_trims_an_oversized_pair_instead_of_dropping_it():
    big = _item("Big", contexts=20)
    small = _item("Small")
    batches = _batched([big, small], budget=1200)
    flat = [p for b in batches for p in b]
    assert [p["entity_a"] for p in flat] == ["Big", "Small"]
    assert 0 < len(flat[0]["sample_contexts"]) < 20
    assert clf._item_tokens(flat[0]) <= 1200
    assert len(big["sample_contexts"]) == 20


def test_batch_budget_follows_the_declared_window(monkeypatch):
    monkeypatch.delenv("STUDIO_BULK_CONTEXT_TOKENS", raising=False)
    assert clf._batch_token_budget() == 32768 // 2
    monkeypatch.setenv("STUDIO_BULK_CONTEXT_TOKENS", "200000")
    assert clf._batch_token_budget() == 100_000


def _pairs(n):
    return [
        clf.Relationship(entity_a=f"E{i}", entity_b=f"F{i}", cooccurrence_count=1,
                          chapters=["ch01"], sample_contexts=["ctx"])
        for i in range(n)
    ]


def test_batches_unbatch_to_the_right_pair_by_position(tmp_path, monkeypatch):
    """classifications[j] of batch i must merge onto to_classify[i*_BATCH_SIZE+j],
    never scrambled across a batch boundary."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    n = _BATCH_SIZE + 2
    input_bundle = RelationshipBundle(relationships=_pairs(n))
    studio_io.save_artifact(processing / "relationships.json", input_bundle, RelationshipBundle)

    def fake_fanout(batches, fp):
        assert [len(b) for b in batches] == [_BATCH_SIZE, 2]
        results = []
        for i, batch in enumerate(batches):
            classifications = [
                {"relationship_type": f"{pair['entity_a']}_typed", "direction": "symmetric",
                 "evolution": None, "key_moments": [], "evidence": "ev", "confidence": "inferred"}
                for pair in batch
            ]
            results.append({"index": i, "status": "success", "output": {"classifications": classifications}})
        return {"total": n, "results": results, "resumed": 0}, None

    monkeypatch.setattr(clf, "_run_classify_fanout", fake_fanout)
    monkeypatch.setattr(sys, "argv", ["classify_relationships.py", "--book", str(book_yaml)])

    clf.main()

    out = studio_io.load_artifact(processing / "relationships_classified.json", RelationshipBundle)
    by_entity_a = {r.entity_a: r.relationship_type for r in out.relationships}
    for i in range(n):
        assert by_entity_a[f"E{i}"] == f"E{i}_typed"


def test_batch_level_failure_stamps_every_pair_in_that_batch(tmp_path, monkeypatch):
    """A failed batch (status != success) stamps EVERY pair still in it, not just
    one — the STU-562 per-pair error path, one level up now that a map item is a
    batch (STU-751: resume/failure granularity coarsened from pair to batch)."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    n = _BATCH_SIZE + 2
    input_bundle = RelationshipBundle(relationships=_pairs(n))
    studio_io.save_artifact(processing / "relationships.json", input_bundle, RelationshipBundle)

    def fake_fanout(batches, fp):
        results = [
            {"index": 0, "status": "success", "output": {"classifications": [
                {"relationship_type": "friend", "direction": "symmetric", "evolution": None,
                 "key_moments": [], "evidence": "ev", "confidence": "inferred"}
                for _ in batches[0]
            ]}},
            {"index": 1, "status": "failed", "error": "child run failed"},
        ]
        return {"total": n, "results": results, "resumed": 0}, None

    monkeypatch.setattr(clf, "_run_classify_fanout", fake_fanout)
    monkeypatch.setattr(sys, "argv", ["classify_relationships.py", "--book", str(book_yaml)])

    clf.main()

    out = studio_io.load_artifact(processing / "relationships_classified.json", RelationshipBundle)
    by_entity_a = {r.entity_a: r for r in out.relationships}
    for i in range(_BATCH_SIZE):
        assert by_entity_a[f"E{i}"].relationship_type == "friend"
    for i in range(_BATCH_SIZE, n):
        assert by_entity_a[f"E{i}"].classification_error == "child run failed"


def test_confidence_survives_dry_run_passthrough_without_classifier(tmp_path, monkeypatch):
    """STU-751: a discovered pair's deterministic confidence needs no classifier
    call at all — it must reach the artifact through the fold + dry-run
    passthrough path untouched."""
    series = tmp_path / "library" / "author" / "series"
    processing = series / "processing_output" / "01-book"
    processing.mkdir(parents=True)
    book_yaml = series / "books" / "01-book.yaml"
    book_yaml.parent.mkdir(parents=True)
    book_yaml.write_text("novel_summary: A tale.\n", encoding="utf-8")

    Registry(entities=[
        EntityRecord(entity_id="peter", canonical_name="Peter",
                     entity_type="PERSON", aliases=["Peter"]),
        EntityRecord(entity_id="susan", canonical_name="Susan",
                     entity_type="PERSON", aliases=["Susan"]),
    ]).save(processing / "registry.json")

    discovered = RelationshipBundle(relationships=[clf.Relationship(
        entity_a="Peter", entity_b="Susan", cooccurrence_count=3,
        chapters=["ch01"], sample_contexts=["they are siblings"],
        relationship_type="family", direction="symmetric", confidence="explicit",
    )])
    studio_io.save_artifact(
        processing / "relationships_discovered.json", discovered, RelationshipBundle
    )

    monkeypatch.setattr(
        sys, "argv",
        ["classify_relationships.py", "--book", str(book_yaml), "--dry-run"],
    )
    clf.main()

    out = studio_io.load_artifact(
        processing / "relationships_classified.json", RelationshipBundle
    )
    assert out.relationships[0].confidence == "explicit"


# ---------------------------------------------------------------------------
# STU-496: per-entity role contexts surfaced to the classifier
# ---------------------------------------------------------------------------

def _rec(name, contexts):
    return EntityRecord(
        entity_id=name.lower(),
        canonical_name=name,
        entity_type="PERSON",
        mentions=[Mention(surface=name, chapter_id="ch01", context=c) for c in contexts],
    )


def test_entity_role_contexts_collects_distinct_sentences():
    registry = Registry(entities=[
        _rec("Xavier", ["Xavier—the thief from Melisande.", "Xavier was a Champion."]),
    ])
    ctx = _entity_role_contexts(registry)
    assert ctx["Xavier"] == ["Xavier—the thief from Melisande.", "Xavier was a Champion."]


def test_entity_role_contexts_dedupes_and_keeps_first():
    registry = Registry(entities=[
        _rec("Brullo", ["Brullo the Weapons Master.", "Brullo the Weapons Master.", "He drilled them."]),
    ])
    ctx = _entity_role_contexts(registry)
    assert ctx["Brullo"][0] == "Brullo the Weapons Master."
    assert ctx["Brullo"] == ["Brullo the Weapons Master.", "He drilled them."]


def test_entity_role_contexts_samples_when_over_cap():
    many = [f"context {i}" for i in range(20)]
    registry = Registry(entities=[_rec("Celaena", many)])
    ctx = _entity_role_contexts(registry, max_per_entity=6)
    assert len(ctx["Celaena"]) == 6
    assert ctx["Celaena"][0] == "context 0"  # first mention (introduction) always kept


def test_entity_role_contexts_ignores_empty_context():
    registry = Registry(entities=[_rec("Cain", ["", "  ", "Cain the demon-summoner."])])
    ctx = _entity_role_contexts(registry)
    assert ctx["Cain"] == ["Cain the demon-summoner."]


def test_dry_run_with_missing_book_exits_nonzero():
    result = subprocess.run(
        [sys.executable, "scripts/classify_relationships.py",
         "--book", "nonexistent.yaml", "--dry-run"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode != 0
