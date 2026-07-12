"""Tests for scripts/relationship_extraction.py — spaCy-only pronoun heuristic."""
import json
import subprocess
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from scripts.relationship_extraction import enrich_mentions_with_coref

_TEST_MODEL = "qwen2.5"


from _markers import requires_fastcoref, requires_fr_lg


@requires_fastcoref
@requires_fr_lg
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
    result = _coref_worker(("ch01", "Il travaillait.", {"david martín": "David Martín"}, "fr_core_news_lg", 8000, frozenset({"il"})))
    assert isinstance(result, list)
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


def test_enrich_fastcoref_accepts_max_chars_param():
    """enrich_mentions_with_fastcoref accepts max_chars with default 8000."""
    import inspect
    from scripts.relationship_extraction import enrich_mentions_with_fastcoref
    sig = inspect.signature(enrich_mentions_with_fastcoref)
    assert "max_chars" in sig.parameters
    assert sig.parameters["max_chars"].default == 8000


def test_main_parses_workers_flag(monkeypatch):
    """--workers N is parsed and passed through to run_live_mode."""
    import sys
    import scripts.relationship_extraction as rel

    captured = {}

    def fake_run_live(window_size, threshold, coref=False, workers=1, min_cooccurrence=None, min_chapters_together=2, coref_max_chars=8000):
        captured["workers"] = workers

    monkeypatch.setattr(rel, "run_live_mode", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["rel.py", "--live", "--coref", "--workers", "4"])
    rel.main()

    assert captured["workers"] == 4


def test_main_parses_coref_max_chars_flag(monkeypatch):
    """--coref-max-chars N is parsed and passed through to run_live_mode."""
    import sys
    import scripts.relationship_extraction as rel

    captured = {}

    def fake_run_live(window_size, threshold, coref=False, workers=1, min_cooccurrence=None, min_chapters_together=2, coref_max_chars=8000):
        captured["coref_max_chars"] = coref_max_chars

    monkeypatch.setattr(rel, "run_live_mode", fake_run_live)
    monkeypatch.setattr(sys, "argv", ["rel.py", "--live", "--coref", "--coref-max-chars", "0"])
    rel.main()

    assert captured["coref_max_chars"] == 0


def test_executor_parses_coref_max_chars(monkeypatch, tmp_path, capsys):
    """coref_max_chars in additional_context reaches enrich_mentions_with_fastcoref."""
    import io
    import json
    import sys
    from types import SimpleNamespace
    import scripts.relationship_extraction as rel

    (tmp_path / "chapters.json").write_text(json.dumps({"chapters": {"ch01": "Celaena walked. She smiled."}}), encoding="utf-8")

    captured = {}

    def fake_enrich(chapters, entities, mentions_by_entity, workers=1, spacy_model="fr_core_news_lg", max_chars=8000):
        captured["max_chars"] = max_chars
        return mentions_by_entity

    monkeypatch.setattr(rel, "enrich_mentions_with_fastcoref", fake_enrich)
    monkeypatch.setattr(rel.studio_io, "paths_from_payload", lambda payload, strict=False: SimpleNamespace(processing=tmp_path))

    payload = {
        "previous_outputs": {
            "entity-resolution": {
                "entities": [{"canonical_name": "Celaena", "type": "PERSON", "aliases": [], "source_ids": [], "relevant": True}],
            },
        },
        "additional_context": "coref: true\ncoref_max_chars: 4321\n",
    }
    monkeypatch.setattr(sys, "argv", ["rel.py"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    rel.main()

    assert captured["max_chars"] == 4321
    out = capsys.readouterr().out
    assert json.loads(out)  # executor still emits valid JSON


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


def test_coref_worker_accepts_6_tuple():
    """_coref_worker must unpack (chapter_id, text, name_to_canonical, spacy_model, max_chars, pronouns)."""
    from scripts.relationship_extraction import _coref_worker
    result = _coref_worker(("ch01", "", {}, "en_core_web_sm", 8000, frozenset({"she"})))
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
    monkeypatch.setattr(rel_mod.studio_io, "paths_from_payload", lambda p, strict=False: None)

    payload = _make_pipeline_payload(classify=True, llm_model=_TEST_MODEL)
    monkeypatch.setattr("sys.stdin", _io.StringIO(_json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", _io.StringIO())

    rel_mod.main()
    assert captured.get("model") == _TEST_MODEL


def test_pipeline_skips_classify_when_no_llm_model(monkeypatch, capsys):
    import scripts.relationship_extraction as rel_mod

    monkeypatch.setattr(rel_mod, "_load_mentions_from_files", lambda p: {})
    monkeypatch.setattr(rel_mod.studio_io, "paths_from_payload", lambda p, strict=False: None)

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
    monkeypatch.setattr(rel_mod.studio_io, "paths_from_payload", lambda p, strict=False: None)

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
    """Names in adjacent sentences (gap=1) must be returned as a 2-sentence span, excluding non-adjacent name occurrences."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Dorian entered the hall.",    # Dorian @ 0
        "Hollin ran toward him.",      # Hollin @ 1 — gap=1, best pair
        "Dorian watched from afar.",   # Dorian @ 2 — farther, should NOT expand span
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert result is not None
    assert "Dorian" in result
    assert "Hollin" in result
    assert "watched from afar" not in result   # sent 2 not part of closest pair span


def test_tightest_span_excludes_sentences_with_neither_name():
    """Names more than 1 sentence apart must return None — no direct interaction evidence."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Dorian entered the hall.",
        "The fireplace crackled.",
        "The prince watched from afar.",
        "Hollin ran toward him.",          # gap=3 from Dorian
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert result is None


def test_tightest_span_returns_closest_pair_span():
    """When names appear multiple times, return the span around the closest pair."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Dorian entered the hall.",        # Dorian @ 0
        "Dorian looked at Hollin.",        # both @ 1 — gap=0, best pair
        "Hollin did not answer.",          # Hollin @ 2
    ]
    result = _tightest_span(window, "dorian", "hollin")
    assert result is not None
    # Best pair is sentence 1 (gap=0), so only that sentence is returned
    assert "Dorian" in result
    assert "Hollin" in result
    assert "did not answer" not in result   # sent 2 not included (best gap is 0, not 1)


def test_tightest_span_returns_none_when_name_not_found():
    """If either name is absent from the window, return None — no evidence possible."""
    from scripts.relationship_extraction import _tightest_span
    window = ["Some unrelated sentence.", "Another sentence."]
    result = _tightest_span(window, "dorian", "hollin")
    assert result is None


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


def test_build_cooccurrence_graph_sample_contexts_prefer_same_sentence():
    """gap=0 contexts (both names same sentence) must appear before gap=1 (adjacent sentences)."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Alice", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Bob", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # ch01..ch10: gap=1 (Alice in sentence 1, Bob in sentence 2 — no same-sentence occurrence)
    # ch11..ch20: gap=0 (Alice and Bob in the same sentence)
    mentions: dict = {"Alice": {}, "Bob": {}}
    for i in range(1, 11):
        ch = f"ch{i:02d}"
        mentions["Alice"][ch] = ["Alice entered the room.", "Bob followed behind."]
        mentions["Bob"][ch] = ["Alice entered the room.", "Bob followed behind."]
    for i in range(11, 21):
        ch = f"ch{i:02d}"
        mentions["Alice"][ch] = ["Alice and Bob spoke quietly together."]
        mentions["Bob"][ch] = ["Alice and Bob spoke quietly together."]

    rels, _ = build_cooccurrence_graph(
        entities, mentions, window_size=3, min_cooccurrence=1, min_chapters_together=1
    )
    assert rels, "Expected at least one relationship"
    contexts = rels[0]["sample_contexts"]
    # All gap=0 contexts should appear before any gap=1
    gap0_texts = {c for c in contexts if "Alice and Bob" in c}
    gap1_texts = {c for c in contexts if "Alice and Bob" not in c}
    assert gap0_texts, "Expected at least one same-sentence (gap=0) context in results"
    if gap1_texts:
        # gap=0 entries must fill the front of the list before gap=1 entries
        first_gap1_idx = next(i for i, c in enumerate(contexts) if c in gap1_texts)
        last_gap0_idx = max(i for i, c in enumerate(contexts) if c in gap0_texts)
        assert last_gap0_idx < first_gap1_idx or len(gap0_texts) == 12, (
            "gap=0 contexts must be exhausted before gap=1 contexts are included"
        )


def test_build_cooccurrence_graph_sample_contexts_distributed_across_chapters():
    """sample_contexts must draw from early and late chapters, not just the first 3."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Alice", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Bob", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # 20 chapters, each with one co-occurrence sentence
    mentions: dict = {"Alice": {}, "Bob": {}}
    for i in range(1, 21):
        ch = f"ch{i:02d}"
        sentence = f"Alice met Bob in chapter {i}."
        mentions["Alice"][ch] = [sentence]
        mentions["Bob"][ch] = [sentence]

    rels, _ = build_cooccurrence_graph(
        entities, mentions, window_size=3, min_cooccurrence=1, min_chapters_together=1
    )
    assert rels, "Expected at least one relationship"
    contexts = rels[0]["sample_contexts"]
    assert len(contexts) <= 12, f"Expected at most 12 contexts, got {len(contexts)}"
    # Must include contexts from late chapters (chapter 15+)
    late_contexts = [c for c in contexts if any(f"chapter {i}" in c for i in range(15, 21))]
    assert late_contexts, "sample_contexts must include contexts from late chapters"


def test_tightest_span_returns_none_when_names_too_far_apart():
    """Names separated by more than 1 sentence (gap=2) must return None."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Nehemia entered the hall.",
        "The crowd murmured.",          # neither name
        "Cain flexed his arms.",        # gap=2 from Nehemia
    ]
    result = _tightest_span(window, "cain", "nehemia")
    assert result is None


def test_tightest_span_uses_closest_pair_when_multiple_occurrences():
    """When a name appears multiple times, use the pair with minimum gap."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Cain entered first.",          # Cain @ 0 — gap=3 from Nehemia @ 3
        "The hall was silent.",
        "Cain looked up.",              # Cain @ 2 — gap=1 from Nehemia @ 3
        "Nehemia stepped forward.",     # Nehemia @ 3
    ]
    result = _tightest_span(window, "cain", "nehemia")
    assert result is not None
    # Should use the closest pair: Cain@2 + Nehemia@3 (gap=1)
    assert "Cain looked up" in result
    assert "Nehemia stepped forward" in result
    assert "Cain entered first" not in result   # farther pair not included


def test_tightest_span_returns_none_when_name_appears_only_in_artifact_genitive():
    """'Eye of Elena' — 'Elena' after 'of' is an artifact reference, not the character. Must return None."""
    from scripts.relationship_extraction import _tightest_span
    window = ["Celaena grabbed the Eye of Elena from the altar."]
    result = _tightest_span(window, "Celaena", "Elena")
    assert result is None, f"Expected None when Elena only appears as artifact genitive, got: {result!r}"


def test_tightest_span_uses_standalone_name_even_when_artifact_also_present():
    """If 'Elena' appears both in 'Eye of Elena' and standalone, the standalone counts."""
    from scripts.relationship_extraction import _tightest_span
    window = [
        "Celaena entered the chamber.",      # Celaena @ 0
        "Elena spoke to her from the mist.", # Elena @ 1 — standalone, gap=1
        "The Eye of Elena glowed.",          # Elena @ 2 — artifact only, should not count
    ]
    result = _tightest_span(window, "Celaena", "Elena")
    assert result is not None
    assert "Celaena" in result
    assert "Elena spoke" in result


def test_build_cooccurrence_graph_excludes_pairs_without_proximity_context():
    """Pairs whose names never appear within 1 sentence of each other must be excluded."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Cain", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Nehemia", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # Names appear in same window but always gap>=2 apart
    mentions = {
        "Cain": {"ch01": [
            "Nehemia watched the competition.",   # Nehemia @ 0
            "The crowd cheered loudly.",          # gap filler @ 1
            "Cain flexed his arms.",              # Cain @ 2 — gap=2 from Nehemia
        ]},
        "Nehemia": {"ch01": [
            "Nehemia watched the competition.",
            "The crowd cheered loudly.",
            "Cain flexed his arms.",
        ]},
    }
    rels, _ = build_cooccurrence_graph(
        entities, mentions, window_size=5, min_cooccurrence=1, min_chapters_together=1
    )
    names_in_output = {(r["entity_a"], r["entity_b"]) for r in rels}
    assert ("Cain", "Nehemia") not in names_in_output
    assert ("Nehemia", "Cain") not in names_in_output


# --- Studio classifier item tests ---

from scripts.relationship_extraction import _run_studio_classifier_item


def test_run_studio_classifier_item_returns_classification_on_success():
    fake_output = json.dumps({
        "stages": [
            {
                "stage_name": "relationship-classifier",
                "status": "success",
                "output": {
                    "relationship_type": "ami",
                    "direction": "symétrique",
                    "evolution": "Leur complicité grandit.",
                    "key_moments": ["ch03: entraînement commun"],
                },
            }
        ]
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


# ---------------------------------------------------------------------------
# STU-286: filter PLACE/OTHER entities before classification
# ---------------------------------------------------------------------------

from scripts.relationship_extraction import _should_classify_pair


def test_should_classify_pair_allows_person_person():
    rel = {"entity_a": "Celaena", "entity_b": "Chaol"}
    entity_types = {"Celaena": "PERSON", "Chaol": "PERSON"}
    assert _should_classify_pair(rel, entity_types) is True


def test_should_classify_pair_skips_when_entity_b_is_place():
    rel = {"entity_a": "Chaol Westfall", "entity_b": "White Fang Mountains"}
    entity_types = {"Chaol Westfall": "PERSON", "White Fang Mountains": "PLACE"}
    assert _should_classify_pair(rel, entity_types) is False


def test_should_classify_pair_skips_when_entity_b_is_other():
    rel = {"entity_a": "King of Adarlan", "entity_b": "Nothung"}
    entity_types = {"King of Adarlan": "PERSON", "Nothung": "OTHER"}
    assert _should_classify_pair(rel, entity_types) is False


def test_should_classify_pair_skips_when_entity_a_is_place():
    rel = {"entity_a": "White Fang Mountains", "entity_b": "Celaena"}
    entity_types = {"White Fang Mountains": "PLACE", "Celaena": "PERSON"}
    assert _should_classify_pair(rel, entity_types) is False


def test_should_classify_pair_allows_unknown_type_entity():
    """If an entity is not in entity_types, default to allowing classification."""
    rel = {"entity_a": "Celaena", "entity_b": "Chaol"}
    assert _should_classify_pair(rel, {}) is True


def test_classify_relationships_skips_place_entity_without_calling_studio():
    """Studio must NOT be called for PLACE entities — not just result left null."""
    studio_calls = []

    def fake_studio(rel, *, novel_summary, additional_context):
        studio_calls.append(rel)
        return {"relationship_type": "ami", "direction": "symétrique", "evolution": "x", "key_moments": []}

    rels = [
        {
            "entity_a": "Chaol Westfall", "entity_b": "White Fang Mountains",
            "cooccurrence_count": 10, "chapters": ["ch01"],
            "sample_contexts": [], "relationship_type": None,
            "direction": None, "evolution": None, "key_moments": [],
        }
    ]
    entity_types = {"Chaol Westfall": "PERSON", "White Fang Mountains": "PLACE"}

    with patch("scripts.relationship_extraction._run_studio_classifier_item", side_effect=fake_studio):
        result = classify_relationships(
            rels, model=_TEST_MODEL, ollama_url=_OLLAMA_URL, entity_types=entity_types
        )

    assert studio_calls == [], "Studio must not be called for PLACE entities"
    assert result[0]["relationship_type"] is None


def test_classify_relationships_skips_other_entity_without_calling_studio():
    """Studio must NOT be called for OTHER (object) entities."""
    studio_calls = []

    def fake_studio(rel, *, novel_summary, additional_context):
        studio_calls.append(rel)
        return {"relationship_type": "allié", "direction": "symétrique", "evolution": "x", "key_moments": []}

    rels = [
        {
            "entity_a": "Chaol Westfall", "entity_b": "Nothung",
            "cooccurrence_count": 5, "chapters": ["ch02"],
            "sample_contexts": [], "relationship_type": None,
            "direction": None, "evolution": None, "key_moments": [],
        }
    ]
    entity_types = {"Chaol Westfall": "PERSON", "Nothung": "OTHER"}

    with patch("scripts.relationship_extraction._run_studio_classifier_item", side_effect=fake_studio):
        result = classify_relationships(
            rels, model=_TEST_MODEL, ollama_url=_OLLAMA_URL, entity_types=entity_types
        )

    assert studio_calls == [], "Studio must not be called for OTHER entities"
    assert result[0]["relationship_type"] is None


def test_classify_relationships_still_classifies_person_pairs_with_entity_types():
    """Person↔person pairs must still be classified when entity_types is provided."""
    studio_calls = []

    def fake_studio(rel, *, novel_summary, additional_context):
        studio_calls.append(rel)
        return {"relationship_type": "ami", "direction": "symétrique", "evolution": "x", "key_moments": []}

    entity_types = {"Celaena": "PERSON", "Chaol": "PERSON"}

    with patch("scripts.relationship_extraction._run_studio_classifier_item", side_effect=fake_studio):
        result = classify_relationships(
            _SAMPLE_RELS, model=_TEST_MODEL, ollama_url=_OLLAMA_URL, entity_types=entity_types
        )

    assert len(studio_calls) == 1
    assert result[0]["relationship_type"] == "ami"


def test_build_cooccurrence_graph_stores_at_most_one_context_per_chapter():
    """When the same pair co-appears multiple times in the same chapter, only one context is stored."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Cain", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Chaol", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # 5 sentences in same chapter, all with tight proximity (gap=0 or gap=1)
    # This would normally produce 3 contexts without per-chapter cap
    mentions = {
        "Cain": {"ch01": [
            "Cain faced Chaol.",
            "The hall was silent.",
            "Cain and Chaol exchanged glares.",
            "Someone else spoke.",
            "Cain watched Chaol leave.",
        ]},
        "Chaol": {"ch01": [
            "Cain faced Chaol.",
            "The hall was silent.",
            "Cain and Chaol exchanged glares.",
            "Someone else spoke.",
            "Cain watched Chaol leave.",
        ]},
    }
    rels, _ = build_cooccurrence_graph(
        entities, mentions, window_size=3, min_cooccurrence=1, min_chapters_together=1
    )
    assert len(rels) == 1
    assert len(rels[0]["sample_contexts"]) == 1  # only 1 context from ch01


def test_is_negating_relationship_detects_it_wasnt_with():
    """'it wasn't with [name]' must be identified as a negation-of-relationship context."""
    from scripts.relationship_extraction import _is_negating_relationship
    assert _is_negating_relationship("Whatever Nehemia's involvement was, it wasn't with Cain.") is True


def test_is_negating_relationship_detects_nothing_to_do_with():
    from scripts.relationship_extraction import _is_negating_relationship
    assert _is_negating_relationship("Chaol had nothing to do with Dorian's scheme.") is True


def test_is_negating_relationship_does_not_filter_genuine_antagonism():
    """'Cain wasn't amused by Celaena' is an interaction — must NOT be filtered."""
    from scripts.relationship_extraction import _is_negating_relationship
    assert _is_negating_relationship("Cain wasn't amused by Celaena's performance.") is False


def test_build_cooccurrence_graph_excludes_negation_of_relationship_contexts():
    """Contexts explicitly negating a direct connection must be excluded from sample_contexts."""
    from scripts.relationship_extraction import build_cooccurrence_graph

    entities = [
        {"canonical_name": "Nehemia", "type": "PERSON", "aliases": [], "relevant": True},
        {"canonical_name": "Cain", "type": "PERSON", "aliases": [], "relevant": True},
    ]
    # Only evidence is a sentence that explicitly negates their relationship
    mentions = {
        "Nehemia": {"ch01": [
            "Whatever Nehemia's involvement was, it wasn't with Cain.",
        ]},
        "Cain": {"ch01": [
            "Whatever Nehemia's involvement was, it wasn't with Cain.",
        ]},
    }
    rels, _ = build_cooccurrence_graph(
        entities, mentions, window_size=3, min_cooccurrence=1, min_chapters_together=1
    )
    # The pair may still co-occur, but must have 0 valid contexts
    for r in rels:
        if {r["entity_a"], r["entity_b"]} == {"Nehemia", "Cain"}:
            assert r["sample_contexts"] == [], (
                f"Negation context must be excluded, got: {r['sample_contexts']}"
            )


def test_run_studio_classifier_item_degrades_on_timeout():
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["studio"], timeout=30)):
        rel = {"entity_a": "A", "entity_b": "B", "sample_contexts": [], "cooccurrence_count": 1}
        result = _run_studio_classifier_item(rel, novel_summary="", additional_context="")
    assert result.get("error") == "studio_run_timeout"


def test_span_contains_both_returns_false_when_name_absent():
    """_span_contains_both must return False if either name is absent from span."""
    from scripts.relationship_extraction import _span_contains_both
    assert _span_contains_both("Chaol stood. Crown Prince entered.", "Chaol", "Crown Prince") is True
    assert _span_contains_both("Chaol stood. Crown Prince entered.", "Chaol", "Philippa") is False
    assert _span_contains_both("Chaol stood. Crown Prince entered.", "Elena", "Crown Prince") is False


def test_patch_datasets_pickler_py314_makes_signature_compatible():
    """On py3.14 with datasets < 4.4, the patch must make Pickler._batch_setitems
    accept the stdlib's (items, obj) call; it must no-op cleanly otherwise."""
    import inspect
    import sys as _sys

    import pytest as _pytest

    from scripts.relationship_extraction import _patch_datasets_pickler_py314

    _patch_datasets_pickler_py314()  # must never raise

    if _sys.version_info < (3, 14):
        return
    ds_dill = _pytest.importorskip("datasets.utils._dill")
    params = inspect.signature(ds_dill.Pickler._batch_setitems).parameters
    accepts_obj = len(params) > 2 or any(
        p.kind is inspect.Parameter.VAR_POSITIONAL for p in params.values()
    )
    assert accepts_obj, "Pickler._batch_setitems still incompatible with py3.14 pickle"


def test_pronouns_for_model_derives_language():
    """Pronoun set for coref must follow the book's language, not default to fr."""
    from scripts.relationship_extraction import _pronouns_for_model

    en = _pronouns_for_model("models/wiki-ner-en/model-best")
    assert "she" in en and "he" in en
    fr = _pronouns_for_model("fr_core_news_lg")
    assert "elle" in fr and "il" in fr


def test_process_chapter_clusters_english_pronouns():
    """An English pronoun in a cluster with a known entity is attributed to it."""
    from scripts.relationship_extraction import _process_chapter_clusters

    chunk = "Celaena walked into the hall. She smiled at Dorian."
    clusters = [[(0, 7), (30, 33)]]  # "Celaena", "She"
    out = _process_chapter_clusters(
        clusters, chunk, "ch01", {"celaena": "Celaena"}, frozenset({"she", "he"})
    )
    assert ("Celaena", "ch01", "She smiled at Dorian.") in out
