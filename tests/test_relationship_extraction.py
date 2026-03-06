"""Tests for scripts/relationship_extraction.py — spaCy-only pronoun heuristic."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.relationship_extraction import enrich_mentions_with_coref


def test_enrich_mentions_adds_pronoun_sentence():
    """Pronoun sentence after a named entity must be added to its mentions."""
    chapters = {
        "ch01": (
            "David Martín était un écrivain qui vivait à Barcelone. "
            "Il travaillait chaque nuit dans son atelier. "
            "Il écrivait des romans sombres et poétiques."
        ),
    }
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín", "David"], "relevant": True},
    ]
    mentions_by_entity = {
        "David Martín": {"ch01": ["David Martín était un écrivain qui vivait à Barcelone."]}
    }

    enriched = enrich_mentions_with_coref(chapters, entities, mentions_by_entity)

    ch01_sentences = enriched.get("David Martín", {}).get("ch01", [])
    pronoun_sentences = [s for s in ch01_sentences if "Il" in s or "il" in s]
    assert len(pronoun_sentences) >= 1, (
        f"Expected at least one pronoun sentence added, got: {ch01_sentences}"
    )


def test_enrich_mentions_no_crash_on_empty_chapters():
    """If chapters dict is empty, function returns mentions_by_entity unchanged."""
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    mentions_by_entity = {"David Martín": {"ch01": ["David Martín entra."]}}
    result = enrich_mentions_with_coref({}, entities, mentions_by_entity)
    assert result == mentions_by_entity


def test_enrich_mentions_no_duplicate_sentences():
    """Already-present sentences must not be added again."""
    # This sentence has no pronouns, so it won't be re-added via coref logic.
    # We just verify existing sentences are not duplicated.
    sentence = "David Martín était un écrivain qui vivait à Barcelone."
    chapters = {"ch01": sentence}
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
    ]
    mentions_by_entity = {"David Martín": {"ch01": [sentence]}}

    enriched = enrich_mentions_with_coref(chapters, entities, mentions_by_entity)
    assert enriched["David Martín"]["ch01"].count(sentence) == 1


def test_enrich_mentions_resets_after_silence():
    """Active entity resets after silence_window sentences with no PERSON."""
    # After 6 sentences with no entity, the active entity resets
    # and pronouns in a later sentence should NOT be attributed
    silence_sentences = " ".join([f"La pluie tombait sur la ville." for _ in range(6)])
    chapters = {
        "ch01": (
            "David Martín entra dans la pièce. "  # sets active_entity = David Martín
            + silence_sentences +                   # 6 sentences, resets after 5
            " Il pleuvait encore."                  # pronoun but active_entity is None
        ),
    }
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
    ]
    mentions_by_entity: dict = {}

    enriched = enrich_mentions_with_coref(chapters, entities, mentions_by_entity, silence_window=5)

    # "Il pleuvait encore." should NOT be in David Martín's mentions
    dm_mentions = enriched.get("David Martín", {}).get("ch01", [])
    assert "Il pleuvait encore." not in dm_mentions


def test_narrator_passthrough_in_output():
    """narrator from entity-resolution is passed through to output unchanged."""
    import json
    import subprocess
    import sys
    import os

    narrator = {
        "entity": "David Martín",
        "pov": "first_person",
        "reliability": "unreliable",
        "evidence": ["ch20: hallucinations"],
    }
    resolution_output = {
        "entities": [
            {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}
        ],
        "narrator": narrator,
    }
    payload = {
        "previous_outputs": {
            "entity-resolution": resolution_output,
            "epub-parse": {"title": "Test", "author": None, "chapters": [], "pov_detection": {"pov": "first_person", "first_person_count": 100, "total_tokens": 500, "confidence": "high"}},
        },
        "additional_context": "",
    }
    result = subprocess.run(
        [sys.executable, "scripts/relationship_extraction.py"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert "narrator" in output, "narrator key missing from output"
    assert output["narrator"] == narrator


def test_narrator_passthrough_null_when_absent():
    """If entity-resolution has no narrator, output narrator is None."""
    import json
    import subprocess
    import sys
    import os

    resolution_output = {
        "entities": [
            {"canonical_name": "David Martín", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}
        ],
        # no narrator key
    }
    payload = {
        "previous_outputs": {
            "entity-resolution": resolution_output,
            "epub-parse": {"title": "Test", "author": None, "chapters": [], "pov_detection": {"pov": "omniscient", "first_person_count": 0, "total_tokens": 500, "confidence": "high"}},
        },
        "additional_context": "",
    }
    result = subprocess.run(
        [sys.executable, "scripts/relationship_extraction.py"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), ".."),
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    output = json.loads(result.stdout)
    assert output.get("narrator") is None


def test_coref_worker_returns_list():
    """_coref_worker returns a list (empty when fastcoref not available)."""
    from scripts.relationship_extraction import _coref_worker
    result = _coref_worker(("ch01", "Il travaillait.", {"david martín": "David Martín"}))
    assert isinstance(result, list)
    # Each item is (canonical, chapter_id, sentence)
    for item in result:
        assert len(item) == 3
        assert isinstance(item[0], str)
        assert isinstance(item[1], str)
        assert isinstance(item[2], str)


def test_enrich_fastcoref_accepts_workers_param():
    """enrich_mentions_with_fastcoref accepts workers param without crashing."""
    import inspect
    from scripts.relationship_extraction import enrich_mentions_with_fastcoref
    sig = inspect.signature(enrich_mentions_with_fastcoref)
    assert "workers" in sig.parameters
    assert sig.parameters["workers"].default == 1


def test_main_parses_workers_flag(monkeypatch):
    """--workers N is parsed and passed through to run_live_mode."""
    import sys
    import scripts.relationship_extraction as rel

    captured = {}

    def fake_run_live(window_size, threshold, coref=False, workers=1):
        captured["workers"] = workers

    monkeypatch.setattr(rel, "run_live_mode", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["rel.py", "--live", "--coref", "--workers", "4"])
    rel.main()

    assert captured["workers"] == 4


def test_parallel_merge_matches_direct_process_chapters():
    """Parallel path merge produces same sentences as _process_chapter_clusters directly.

    We mock ProcessPoolExecutor.map to return pre-computed results from
    _process_chapter_clusters, then verify enrich_mentions_with_fastcoref
    (workers=2) merges them into mentions_by_entity identically.
    """
    from unittest.mock import patch, MagicMock
    import scripts.relationship_extraction as rel

    chapters = {
        "ch01": "David Martín entra dans la pièce. Il ferma la porte derrière lui.",
        "ch02": "Pedro Vidal écrivit toute la nuit. Il signa le contrat au matin.",
    }
    entities = [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín", "David"], "relevant": True},
        {"canonical_name": "Pedro Vidal", "type": "PERSON", "aliases": ["Vidal"], "relevant": True},
    ]

    # Build the name_to_canonical map the same way the function does
    name_to_canonical: dict[str, str] = {}
    for entity in entities:
        if entity.get("type") == "PERSON" and entity.get("relevant", True):
            canonical = entity["canonical_name"]
            name_to_canonical[canonical.lower()] = canonical
            for alias in entity.get("aliases", []):
                if len(alias) >= 3:
                    name_to_canonical[alias.lower()] = canonical

    # What _process_chapter_clusters would return for each chapter
    # (We compute it directly here so the test doesn't depend on fastcoref)
    # Since fastcoref isn't available in CI, raw_clusters will be empty → []
    # We simulate non-empty results manually.
    # Simulate a worker returning the same sentence twice (e.g., from overlapping clusters)
    # The merge should deduplicate — only one copy should end up in mentions_by_entity
    simulated_worker_results = {
        "ch01": [
            ("David Martín", "ch01", "Il ferma la porte derrière lui."),
            ("David Martín", "ch01", "Il ferma la porte derrière lui."),  # duplicate
        ],
        "ch02": [("Pedro Vidal", "ch02", "Il signa le contrat au matin.")],
    }

    # Fake executor that returns pre-computed results without loading the model
    class FakeExecutor:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def map(self, fn, items):
            return [simulated_worker_results.get(item[0], []) for item in items]

    mentions = {"David Martín": {}, "Pedro Vidal": {}}
    with patch("concurrent.futures.ProcessPoolExecutor", return_value=FakeExecutor()):
        result = rel.enrich_mentions_with_fastcoref(chapters, entities, mentions, workers=2)

    # Verify the expected sentences are present (from simulated worker results)
    dm_sentences = result.get("David Martín", {}).get("ch01", [])
    pv_sentences = result.get("Pedro Vidal", {}).get("ch02", [])

    assert "Il ferma la porte derrière lui." in dm_sentences, (
        f"Expected David Martín ch01 sentence, got: {dm_sentences}"
    )
    assert "Il signa le contrat au matin." in pv_sentences, (
        f"Expected Pedro Vidal ch02 sentence, got: {pv_sentences}"
    )

    # Verify deduplication: same sentence returned twice by worker → only once in result
    assert dm_sentences.count("Il ferma la porte derrière lui.") == 1, (
        f"Expected exactly 1 copy after dedup, got: {dm_sentences}"
    )
    assert pv_sentences.count("Il signa le contrat au matin.") == 1, (
        f"Expected exactly 1 copy after dedup, got: {pv_sentences}"
    )
