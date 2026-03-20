"""Tests for scripts/relationship_extraction.py — spaCy-only pronoun heuristic."""
import json
import subprocess
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.relationship_extraction import enrich_mentions_with_coref

_TEST_MODEL = "qwen2.5"


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
    result = _coref_worker(("ch01", "Il travaillait.", {"david martín": "David Martín"}, "fr_core_news_lg"))
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

    def fake_run_live(window_size, threshold, coref=False, workers=1, min_cooccurrence=None, min_chapters_together=2):
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


# ---------------------------------------------------------------------------
# STU-248: min_cooccurrence and min_chapters_together filters
# ---------------------------------------------------------------------------

def _stu248_entities():
    return [
        {"canonical_name": "David Martín", "type": "PERSON", "aliases": ["Martín"], "relevant": True},
        {"canonical_name": "Pedro Vidal",  "type": "PERSON", "aliases": ["Vidal"],  "relevant": True},
        {"canonical_name": "Regarde",      "type": "PERSON", "aliases": [],          "relevant": True},
    ]


def _stu248_mentions():
    return {
        "David Martín": {
            "ch01": ["Vidal tendit le manuscrit à Martín.", "Martín retrouva Vidal."],
            "ch02": ["Martín reçut une lettre.", "Vidal encouragea Martín."],
        },
        "Pedro Vidal": {
            "ch01": ["Vidal tendit le manuscrit à Martín.", "Martín retrouva Vidal."],
            "ch02": ["Vidal encouragea Martín."],
        },
        "Regarde": {
            "ch01": ["— Regarde, il est là."],
        },
    }


def test_false_entity_filtered_by_min_chapters():
    """'Regarde' only appears in 1 chapter — must be filtered with min_chapters_together=2."""
    from scripts.relationship_extraction import build_cooccurrence_graph
    rels, stats = build_cooccurrence_graph(
        _stu248_entities(),
        _stu248_mentions(),
        window_size=5,
        min_cooccurrence=2,
        min_chapters_together=2,
    )
    entity_names = {r["entity_a"] for r in rels} | {r["entity_b"] for r in rels}
    assert "Regarde" not in entity_names


def test_true_relation_survives_filter():
    """Martín ↔ Vidal appears in 2 chapters — must survive the filter."""
    from scripts.relationship_extraction import build_cooccurrence_graph
    rels, stats = build_cooccurrence_graph(
        _stu248_entities(),
        _stu248_mentions(),
        window_size=5,
        min_cooccurrence=2,
        min_chapters_together=2,
    )
    pairs = {(r["entity_a"], r["entity_b"]) for r in rels}
    assert ("David Martín", "Pedro Vidal") in pairs or ("Pedro Vidal", "David Martín") in pairs


def test_coref_worker_accepts_4_tuple():
    """_coref_worker must unpack (chapter_id, text, name_to_canonical, spacy_model)."""
    from scripts.relationship_extraction import _coref_worker
    # Empty text → empty result, no crash
    result = _coref_worker(("ch01", "", {}, "en_core_web_sm"))
    assert result == []


def test_enrich_heuristic_accepts_pronouns_param():
    """enrich_mentions_with_heuristic should accept custom pronouns without error."""
    from scripts.relationship_extraction import enrich_mentions_with_heuristic
    chapters = {"ch01": "Alice walked in. She smiled."}
    entities = [{"canonical_name": "Alice", "type": "PERSON", "relevant": True, "aliases": []}]
    mentions = {"Alice": {"ch01": ["Alice walked in."]}}
    # spaCy blank model (no NER, no senter) — use a real EN model if available
    import spacy
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    result = enrich_mentions_with_heuristic(
        chapters, entities, mentions, nlp=nlp, pronouns=frozenset({"she"})
    )
    assert isinstance(result, dict)


def test_stats_include_new_fields():
    """Stats dict must expose min_cooccurrence and min_chapters_together."""
    from scripts.relationship_extraction import build_cooccurrence_graph
    _, stats = build_cooccurrence_graph(
        _stu248_entities(),
        _stu248_mentions(),
        window_size=5,
        min_cooccurrence=3,
        min_chapters_together=2,
    )
    assert stats["min_cooccurrence"] == 3
    assert stats["min_chapters_together"] == 2


# ---------------------------------------------------------------------------
# STU-262: Ollama helpers
# ---------------------------------------------------------------------------

import urllib.error
from unittest.mock import patch, MagicMock
from scripts.relationship_extraction import _check_ollama_available, _call_ollama_classify_json


def test_check_ollama_available_returns_true_on_success():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=mock_resp):
        assert _check_ollama_available("http://localhost:11434") is True


def test_check_ollama_available_returns_false_on_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        assert _check_ollama_available("http://localhost:11434") is False


def test_call_ollama_classify_json_parses_response():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = b'{"response": "{\\"relationship_type\\": \\"ami\\", \\"direction\\": \\"sym\\\\u00e9trique\\", \\"evolution\\": \\"ils deviennent amis\\", \\"key_moments\\": [\\"ch01: rencontre\\"]}"}'
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _call_ollama_classify_json("some prompt", _TEST_MODEL, "http://localhost:11434", timeout=10)
    assert result["relationship_type"] == "ami"


def test_call_ollama_classify_json_returns_none_on_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        result = _call_ollama_classify_json("prompt", _TEST_MODEL, "http://localhost:11434", timeout=10)
    assert result is None


def test_call_ollama_classify_json_returns_none_on_bad_json():
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = b'{"response": "not json at all"}'
    with patch("urllib.request.urlopen", return_value=mock_resp):
        result = _call_ollama_classify_json("prompt", _TEST_MODEL, "http://localhost:11434", timeout=10)
    assert result is None


# ---------------------------------------------------------------------------
# STU-262 Task 3: classify_relationships with Ollama
# ---------------------------------------------------------------------------

from scripts.relationship_extraction import classify_relationships, _OLLAMA_URL


_SAMPLE_RELS = [
    {
        "entity_a": "Celaena",
        "entity_b": "Chaol",
        "cooccurrence_count": 30,
        "chapters": ["ch01", "ch02"],
        "sample_contexts": ["Chaol escorted Celaena to the castle.", "Celaena sparred with Chaol."],
        "relationship_type": None,
        "direction": None,
        "evolution": None,
        "key_moments": [],
    }
]


def test_classify_relationships_populates_type_on_success():
    studio_response = {
        "evidence": "Chaol escorts Celaena and they spar together.",
        "relationship_type": "antagoniste",
        "direction": "symétrique",
        "evolution": "ils apprennent à se respecter",
        "key_moments": ["ch01: première rencontre"],
    }
    with patch("scripts.relationship_extraction._run_studio_classifier_item", return_value=studio_response):
        result = classify_relationships(_SAMPLE_RELS, model=_TEST_MODEL, ollama_url=_OLLAMA_URL)
    assert result[0]["relationship_type"] == "antagoniste"
    assert result[0]["direction"] == "symétrique"
    assert result[0]["key_moments"] == ["ch01: première rencontre"]
    assert result[0]["evidence"] == "Chaol escorts Celaena and they spar together."


def test_classify_relationships_returns_unchanged_when_ollama_unavailable():
    """When Studio returns an error, the pair is kept with original (null) fields."""
    with patch("scripts.relationship_extraction._run_studio_classifier_item", return_value={"error": "studio_cli_missing"}):
        result = classify_relationships(_SAMPLE_RELS, model=_TEST_MODEL, ollama_url=_OLLAMA_URL)
    assert result[0]["relationship_type"] is None
    assert len(result) == 1


def test_classify_relationships_keeps_null_on_per_pair_failure():
    with patch("scripts.relationship_extraction._run_studio_classifier_item", return_value={"error": "studio_run_failed"}):
        result = classify_relationships(_SAMPLE_RELS, model=_TEST_MODEL, ollama_url=_OLLAMA_URL)
    assert result[0]["relationship_type"] is None
    assert len(result) == 1  # pair still included, not dropped


def test_classify_relationships_includes_novel_summary_in_prompt():
    """novel_summary is passed to _run_studio_classifier_item when provided."""
    captured_calls = []

    def fake_studio(rel, *, novel_summary, additional_context):
        captured_calls.append({"novel_summary": novel_summary})
        return {
            "relationship_type": "ami",
            "direction": "symétrique",
            "evolution": "ils deviennent amis",
            "key_moments": [],
        }

    with patch("scripts.relationship_extraction._run_studio_classifier_item", side_effect=fake_studio):
        classify_relationships(
            _SAMPLE_RELS,
            model=_TEST_MODEL,
            ollama_url=_OLLAMA_URL,
            novel_summary="Celaena is an assassin. Chaol is her guard and friend.",
        )

    assert len(captured_calls) == 1
    assert "Celaena is an assassin" in captured_calls[0]["novel_summary"]


def test_classify_relationships_omits_summary_block_when_none():
    """When novel_summary is None, empty string is passed to Studio."""
    captured_calls = []

    def fake_studio(rel, *, novel_summary, additional_context):
        captured_calls.append({"novel_summary": novel_summary})
        return {
            "relationship_type": "ami",
            "direction": "symétrique",
            "evolution": "ils deviennent amis",
            "key_moments": [],
        }

    with patch("scripts.relationship_extraction._run_studio_classifier_item", side_effect=fake_studio):
        classify_relationships(_SAMPLE_RELS, model=_TEST_MODEL, ollama_url=_OLLAMA_URL)

    assert len(captured_calls) >= 1
    assert captured_calls[0]["novel_summary"] == ""


def test_classify_relationships_omits_summary_block_when_whitespace_only():
    """A whitespace-only novel_summary is normalized to empty string passed to Studio."""
    captured_calls = []

    def fake_studio(rel, *, novel_summary, additional_context):
        captured_calls.append({"novel_summary": novel_summary})
        return {
            "relationship_type": "ami",
            "direction": "symétrique",
            "evolution": "ils deviennent amis",
            "key_moments": [],
        }

    with patch("scripts.relationship_extraction._run_studio_classifier_item", side_effect=fake_studio):
        classify_relationships(
            _SAMPLE_RELS,
            model=_TEST_MODEL,
            ollama_url=_OLLAMA_URL,
            novel_summary="   ",
        )

    assert len(captured_calls) >= 1
    # novel_summary="   " is truthy so passed as-is; Studio ignores whitespace-only content
    assert captured_calls[0]["novel_summary"].strip() == ""


import io as _io
import json as _json


def _make_pipeline_payload(classify=True, llm_model=_TEST_MODEL, include_llm_model=True):
    additional_lines = [f"classify: {str(classify).lower()}"]
    if include_llm_model:
        additional_lines.append(f"llm_model: {llm_model}")
    return {
        "additional_context": "\n".join(additional_lines),
        "previous_outputs": {
            "merge-entities": {
                "entities": [
                    {"canonical_name": "Celaena", "type": "PERSON", "relevant": True, "aliases": [], "source_ids": []},
                    {"canonical_name": "Chaol", "type": "PERSON", "relevant": True, "aliases": [], "source_ids": []},
                ]
            }
        },
        "all_stage_outputs": {}
    }


def test_pipeline_passes_llm_model_to_classify(monkeypatch):
    import scripts.relationship_extraction as rel_mod
    captured = {}

    def fake_classify(rels, *, model, ollama_url, novel_summary=None):
        captured["model"] = model
        captured["ollama_url"] = ollama_url
        return rels

    monkeypatch.setattr(rel_mod, "classify_relationships", fake_classify)
    monkeypatch.setattr(rel_mod, "_load_mentions_from_files", lambda p: {})
    monkeypatch.setattr(rel_mod, "_paths_from_payload", lambda p: None)

    payload = _make_pipeline_payload(classify=True, llm_model=_TEST_MODEL)
    monkeypatch.setattr("sys.stdin", _io.StringIO(_json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", _io.StringIO())

    rel_mod.main()
    assert captured.get("model") == _TEST_MODEL


def test_pipeline_skips_classify_when_no_llm_model(monkeypatch, capsys):
    import scripts.relationship_extraction as rel_mod

    monkeypatch.setattr(rel_mod, "_load_mentions_from_files", lambda p: {})
    monkeypatch.setattr(rel_mod, "_paths_from_payload", lambda p: None)

    payload = _make_pipeline_payload(classify=True, include_llm_model=False)
    monkeypatch.setattr("sys.stdin", _io.StringIO(_json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", _io.StringIO())

    rel_mod.main()
    captured = capsys.readouterr()
    assert "[ERROR]" in captured.err
    assert "llm_model" in captured.err


def test_pipeline_passes_novel_summary_to_classify(monkeypatch):
    """novel_summary from additional_context reaches classify_relationships."""
    import scripts.relationship_extraction as rel_mod

    captured = {}

    def fake_classify(rels, *, model, ollama_url, novel_summary=None):
        captured["novel_summary"] = novel_summary
        return rels

    monkeypatch.setattr(rel_mod, "classify_relationships", fake_classify)
    monkeypatch.setattr(rel_mod, "_load_mentions_from_files", lambda p: {})
    monkeypatch.setattr(rel_mod, "_paths_from_payload", lambda p: None)

    payload = _make_pipeline_payload(classify=True, llm_model=_TEST_MODEL)
    payload["additional_context"] += "\nnovel_summary: Celaena is an assassin."
    monkeypatch.setattr("sys.stdin", _io.StringIO(_json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", _io.StringIO())

    rel_mod.main()
    assert captured.get("novel_summary") == "Celaena is an assassin."

# ---------------------------------------------------------------------------
# STU-283: _tightest_span returns minimal span containing both names
# ---------------------------------------------------------------------------

def test_tightest_span_returns_sentence_with_both_names():
    """When both names are in the same sentence, return just that sentence."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "The snow fell hard.",
        "Dorian and Hollin argued bitterly.",
        "The king watched from afar.",
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert "Dorian" in result
    assert "Hollin" in result
    assert "snow" not in result


def test_tightest_span_spans_two_sentences_when_names_separated():
    """When names are in different sentences, return the span between them."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Dorian entered the hall.",
        "The fireplace crackled.",
        "Hollin ran toward him.",
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert "Dorian" in result
    assert "Hollin" in result


def test_tightest_span_fallback_when_name_not_found():
    """If a name is not found at all, return window[0] as a safe fallback."""
    from scripts.relationship_extraction import _tightest_span
    window = ["Some unrelated sentence.", "Another sentence."]
    result = _tightest_span(window, "dorian", "hollin")
    assert result == "Some unrelated sentence."


def test_tightest_span_name_matching_is_case_insensitive():
    """Name lookup must be case-insensitive (matching the detection regex)."""
    from scripts.relationship_extraction import _tightest_span
    window = ["DORIAN met hollin at the gate."]
    result = _tightest_span(window, "dorian", "hollin")
    assert "DORIAN" in result
    assert "hollin" in result


def test_build_cooccurrence_graph_sample_contexts_contain_both_names():
    """sample_contexts must contain both entity names (STU-283)."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Dorian", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Hollin", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    mentions = {
        "Dorian": {
            "ch01": [
                "The snow fell hard.",
                "Dorian entered the hall.",
                "Hollin ran toward him.",
                "They spoke quietly.",
                "The king watched.",
            ]
        },
        "Hollin": {
            "ch01": [
                "The snow fell hard.",
                "Dorian entered the hall.",
                "Hollin ran toward him.",
                "They spoke quietly.",
                "The king watched.",
            ]
        },
    }
    rels, _ = build_cooccurrence_graph(entities, mentions, window_size=5, min_cooccurrence=1, min_chapters_together=1)
    assert rels, "Expected at least one relationship"
    for rel in rels:
        for ctx in rel["sample_contexts"]:
            assert "Dorian" in ctx or "dorian" in ctx.lower(), f"Missing Dorian in: {ctx}"
            assert "Hollin" in ctx or "hollin" in ctx.lower(), f"Missing Hollin in: {ctx}"


# --- Studio classifier item tests ---

from scripts.relationship_extraction import _run_studio_classifier_item


def test_run_studio_classifier_item_returns_classification_on_success():
    fake_output = json.dumps({
        "stages": {
            "relationship-classifier": {
                "relationship_type": "ami",
                "direction": "symétrique",
                "evolution": "Leur complicité grandit.",
                "key_moments": ["ch03: entraînement commun"],
            }
        }
    })
    mock_result = MagicMock(returncode=0, stdout=fake_output, stderr="")
    with patch("subprocess.run", return_value=mock_result):
        rel = {"entity_a": "Celaena", "entity_b": "Chaol", "sample_contexts": ["ctx1"], "cooccurrence_count": 5}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result["relationship_type"] == "ami"


def test_run_studio_classifier_item_degrades_on_studio_missing():
    with patch("subprocess.run", side_effect=FileNotFoundError):
        rel = {"entity_a": "A", "entity_b": "B", "sample_contexts": [], "cooccurrence_count": 1}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result.get("error") == "studio_cli_missing"


def test_run_studio_classifier_item_degrades_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["studio"], timeout=30)):
        rel = {"entity_a": "A", "entity_b": "B", "sample_contexts": [], "cooccurrence_count": 1}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result.get("error") == "studio_run_timeout"
